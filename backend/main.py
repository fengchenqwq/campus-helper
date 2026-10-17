# 校园百事通助手后端入口
# 启动：uv run uvicorn main:app --reload --port 8000
import json
import re

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import get_db
from ai_service import chat_stream, recognize_image, summarize_title
import speech_service

app = FastAPI(title='校园百事通助手')

# 允许前端跨域访问（前端以 file:// 或独立端口打开）
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{3,20}$')
EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    user_id: int | None = None
    content: str
    conversation_id: int | None = None


def ok(data=None, message='ok'):
    return {'code': 0, 'message': message, 'data': data}


def fail(code, message):
    return {'code': code, 'message': message, 'data': None}


def _sse(payload):
    return 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'


def _update_title(conversation_id):
    """总结会话内容，更新会话标题（失败不影响主流程）。"""
    try:
        conn = get_db()
        rows = conn.execute(
            'SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id',
            (conversation_id,),
        ).fetchall()
        conn.close()
        if not rows:
            return
        dialog = '\n'.join(
            ('用户：' if r['role'] == 'user' else '助手：') + (r['content'] or '')
            for r in rows
        )
        title = summarize_title(dialog)
        if title:
            conn = get_db()
            conn.execute('UPDATE conversations SET title=? WHERE id=?', (title, conversation_id))
            conn.commit()
            conn.close()
    except Exception:
        pass


@app.post('/api/register')
def register(req: RegisterRequest):
    username = req.username.strip()
    password = req.password
    email = req.email.strip()

    # 格式校验
    if not USERNAME_RE.fullmatch(username):
        return fail(1001, '用户名需为3-20位字母、数字或下划线')
    if not 6 <= len(password) <= 20:
        return fail(1001, '密码需为6-20个字符')
    if not EMAIL_RE.fullmatch(email):
        return fail(1001, '邮箱格式不正确')

    conn = get_db()
    cur = conn.cursor()
    try:
        if cur.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone():
            return fail(1002, '用户名已存在')
        if cur.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone():
            return fail(1003, '邮箱已被注册')

        cur.execute(
            'INSERT INTO users (username, password, email) VALUES (?, ?, ?)',
            (username, password, email)
        )
        user_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    return ok({'user_id': user_id, 'username': username}, '注册成功')


@app.post('/api/login')
def login(req: LoginRequest):
    username = req.username.strip()
    password = req.password

    if not username or not password:
        return fail(1001, '用户名和密码不能为空')

    conn = get_db()
    cur = conn.cursor()
    row = cur.execute(
        'SELECT id, username FROM users WHERE username = ? AND password = ?',
        (username, password)
    ).fetchone()
    conn.close()

    if row is None:
        return fail(1004, '用户名或密码错误')

    return ok({'user_id': row['id'], 'username': row['username']}, '登录成功')


@app.post('/api/chat')
def chat(req: ChatRequest):
    content = req.content.strip()
    if not content:
        return fail(1001, '消息不能为空')

    conversation_id = None
    if req.user_id is not None:
        conn = get_db()
        cur = conn.cursor()
        try:
            if req.conversation_id is None:
                # 新对话：归档满足条件的 active 会话（对话>3次且字数>100），其余删除
                active_ids = cur.execute(
                    "SELECT id FROM conversations WHERE user_id=? AND status='active'",
                    (req.user_id,),
                ).fetchall()
                for (cid,) in active_ids:
                    stats = cur.execute(
                        "SELECT SUM(CASE WHEN role='user' THEN 1 ELSE 0 END), COALESCE(SUM(LENGTH(content)), 0) FROM messages WHERE conversation_id=?",
                        (cid,),
                    ).fetchone()
                    user_msg_count, total_len = stats[0] or 0, stats[1] or 0
                    if user_msg_count > 3 and total_len > 100:
                        cur.execute("UPDATE conversations SET status='archived' WHERE id=?", (cid,))
                    else:
                        cur.execute("DELETE FROM conversations WHERE id=?", (cid,))
                cur.execute(
                    "INSERT INTO conversations (user_id, title, status) VALUES (?, ?, 'active')",
                    (req.user_id, content[:30]),
                )
                conversation_id = cur.lastrowid
            else:
                # 继续会话：校验归属，并把回溯的 archived 会话置回 active
                row = cur.execute(
                    'SELECT id FROM conversations WHERE id=? AND user_id=?',
                    (req.conversation_id, req.user_id),
                ).fetchone()
                if row is None:
                    return fail(1006, '无权限访问该会话')
                conversation_id = req.conversation_id
                cur.execute(
                    "UPDATE conversations SET status='active' WHERE id=?",
                    (conversation_id,),
                )
            # 保存用户消息
            cur.execute(
                'INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)',
                (conversation_id, 'user', content),
            )
            conn.commit()
        finally:
            conn.close()

    def generate():
        full_reply = ''
        try:
            for event in chat_stream(str(req.user_id or 'anonymous'), content):
                if event['type'] == 'delta':
                    full_reply += event['content']
                    yield _sse({'type': 'delta', 'content': event['content']})
                elif event['type'] == 'done':
                    yield _sse({'type': 'done', 'conversation_id': conversation_id})
                elif event['type'] == 'error':
                    yield _sse({'type': 'error', 'content': event['content']})
        finally:
            # 流结束后保存 AI 回复
            if req.user_id is not None and full_reply:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    'INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)',
                    (conversation_id, 'ai', full_reply),
                )
                cur.execute(
                    'UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?',
                    (conversation_id,),
                )
                conn.commit()
                conn.close()
                # 总结对话内容，更新会话标题
                _update_title(conversation_id)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.get('/api/history')
def get_history(user_id: int, limit: int | None = None):
    """获取用户已归档的历史会话列表，按创建时间倒序。"""
    query = (
        "SELECT id, title, created_at FROM conversations "
        "WHERE user_id=? AND status='archived' ORDER BY created_at DESC"
    )
    params: list = [user_id]
    if limit is not None:
        query += ' LIMIT ?'
        params.append(limit)

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    data = [
        {'conversation_id': r['id'], 'title': r['title'], 'created_at': r['created_at']}
        for r in rows
    ]
    return ok(data)


@app.get('/api/history/{conversation_id}')
def get_history_detail(conversation_id: int, user_id: int):
    """获取某个会话的全部消息，按时间正序（需校验归属）。"""
    conn = get_db()
    row = conn.execute(
        'SELECT id FROM conversations WHERE id=? AND user_id=?',
        (conversation_id, user_id),
    ).fetchone()
    if row is None:
        conn.close()
        return fail(1006, '无权限访问该会话')

    rows = conn.execute(
        'SELECT role, content, created_at FROM messages '
        'WHERE conversation_id=? ORDER BY created_at ASC, id ASC',
        (conversation_id,),
    ).fetchall()
    conn.close()

    data = [
        {'role': r['role'], 'content': r['content'], 'created_at': r['created_at']}
        for r in rows
    ]
    return ok(data)


@app.post('/api/image')
async def image(file: UploadFile = File(...)):
    data = await file.read()
    try:
        text = recognize_image(data, file.filename or 'image.png')
    except Exception as exc:  # noqa: BLE001
        return fail(5000, '图片识别失败：' + str(exc))
    return ok({'text': text})


@app.post('/api/voice')
async def voice(file: UploadFile = File(...)):
    data = await file.read()
    try:
        text = speech_service.transcribe(data)
    except Exception as exc:  # noqa: BLE001
        return fail(5000, '语音识别失败：' + str(exc))
    return ok({'text': text})

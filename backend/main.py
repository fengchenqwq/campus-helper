# 校园百事通助手后端入口
# 启动：uv run uvicorn main:app --reload --port 8000
import json
import re
import time
from collections import defaultdict

from urllib.parse import unquote
from pathlib import Path
import uuid

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import get_db
from ai_service import chat_stream, recognize_image, summarize_title, parse_document
import speech_service

app = FastAPI(title='校园百事通助手')


def _ensure_role_schema():
    """启动时迁移：给 users 表补 role 字段并预置管理员账号（失败不影响启动）。"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cols = [r[1] for r in cur.execute('PRAGMA table_info(users)').fetchall()]
        if 'role' not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        cur.execute(
            "INSERT OR IGNORE INTO users (username, password, email, role) VALUES ('admin', '123456', 'admin@school.com', 'admin')"
        )
        cur.execute("UPDATE users SET role='admin' WHERE username='admin'")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS feedback ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL, "
            "conversation_id INTEGER, "
            "solved INTEGER NOT NULL, "
            "category TEXT, "
            "problem TEXT, "
            "suggestion TEXT, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)"
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


_ensure_role_schema()

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


class FeedbackRequest(BaseModel):
    user_id: int
    conversation_id: int | None = None
    solved: bool
    category: str | None = None
    problem: str | None = None
    suggestion: str | None = None


def ok(data=None, message='ok'):
    return {'code': 0, 'message': message, 'data': data}


def fail(code, message):
    return {'code': code, 'message': message, 'data': None}


def _sse(payload):
    return 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'


# 限流：每个用户每分钟最多 RATE_LIMIT 次对话
RATE_LIMIT = 10
RATE_WINDOW = 60
_rate_records = defaultdict(list)


def check_rate_limit(user_id):
    now = time.time()
    records = [t for t in _rate_records[user_id] if now - t < RATE_WINDOW]
    _rate_records[user_id] = records
    if len(records) >= RATE_LIMIT:
        return False
    records.append(now)
    return True


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
            'INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)',
            (username, password, email, 'user')
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
        'SELECT id, username, role FROM users WHERE username = ? AND password = ?',
        (username, password)
    ).fetchone()
    conn.close()

    if row is None:
        return fail(1004, '用户名或密码错误')

    return ok({'user_id': row['id'], 'username': row['username'], 'role': row['role']}, '登录成功')


@app.post('/api/chat')
def chat(req: ChatRequest):
    content = req.content.strip()
    if not content:
        return fail(1001, '消息不能为空')

    # 登录门槛：必须登录才能提问
    if req.user_id is None:
        return fail(1005, '请先登录后再提问')

    # 限流：每分钟最多 RATE_LIMIT 次
    if not check_rate_limit(req.user_id):
        return fail(1007, '提问过于频繁，请稍后再试')

    conversation_id = None
    conn = get_db()
    cur = conn.cursor()
    try:
        if req.conversation_id is None:
            # 新对话：归档满足条件的 active 会话（用户提问>3次且字数>100），其余删除
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
            for event in chat_stream(str(req.user_id), content):
                if event['type'] == 'delta':
                    full_reply += event['content']
                    yield _sse({'type': 'delta', 'content': event['content']})
                elif event['type'] == 'done':
                    yield _sse({'type': 'done', 'conversation_id': conversation_id})
                elif event['type'] == 'error':
                    yield _sse({'type': 'error', 'content': event['content']})
        finally:
            # 流结束后保存 AI 回复
            if full_reply:
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


@app.get('/api/conversations')
def get_conversations(user_id: int):
    """获取用户所有会话（含 active 进行中 和 archived 历史），按更新时间倒序。"""
    conn = get_db()
    rows = conn.execute(
        'SELECT id, title, status, created_at, updated_at FROM conversations '
        'WHERE user_id=? ORDER BY updated_at DESC, id DESC',
        (user_id,),
    ).fetchall()
    conn.close()
    data = [
        {
            'conversation_id': r['id'],
            'title': r['title'],
            'status': r['status'],
            'created_at': r['created_at'],
        }
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


@app.post('/api/document')
async def document(file: UploadFile = File(...)):
    data = await file.read()
    text = parse_document(data, file.filename or 'document')
    if not text.strip():
        return fail(5000, '文档解析失败或内容为空')
    return ok({'text': text})


UPLOAD_DIR = Path(__file__).parent / 'uploads'


@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    """上传文件用于在线预览，返回公网 URL。"""
    UPLOAD_DIR.mkdir(exist_ok=True)
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else ''
    name = uuid.uuid4().hex + ('.' + ext if ext else '')
    data = await file.read()
    (UPLOAD_DIR / name).write_bytes(data)
    return ok({'url': f'http://124.221.22.10:8000/uploads/{name}'})


@app.post('/api/voice')
async def voice(file: UploadFile = File(...)):
    data = await file.read()
    try:
        text = speech_service.transcribe(data)
    except Exception as exc:  # noqa: BLE001
        return fail(5000, '语音识别失败：' + str(exc))
    return ok({'text': text})


@app.post('/api/feedback')
def submit_feedback(req: FeedbackRequest):
    """提交问题反馈（用户对 AI 回答的评价/问题/建议）。"""
    if req.user_id is None:
        return fail(1005, '请先登录后再反馈')

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO feedback (user_id, conversation_id, solved, category, problem, suggestion) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (
                req.user_id,
                req.conversation_id,
                1 if req.solved else 0,
                req.category,
                req.problem,
                req.suggestion,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return ok(None, '反馈提交成功')


@app.get('/api/feedback')
def get_feedback(user_id: int):
    """获取所有问题反馈（仅管理员）。"""
    conn = get_db()
    row = conn.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
    if row is None or row['role'] != 'admin':
        conn.close()
        return fail(1006, '无权限访问')
    rows = conn.execute(
        'SELECT f.id, f.solved, f.category, f.problem, f.suggestion, f.created_at, u.username '
        'FROM feedback f LEFT JOIN users u ON f.user_id = u.id '
        'ORDER BY f.created_at DESC, f.id DESC'
    ).fetchall()
    conn.close()
    data = [
        {
            'feedback_id': r['id'],
            'username': r['username'],
            'solved': bool(r['solved']),
            'category': r['category'],
            'problem': r['problem'],
            'suggestion': r['suggestion'],
            'created_at': r['created_at'],
        }
        for r in rows
    ]
    return ok(data)


@app.post('/api/feedback/{feedback_id}/resolve')
def resolve_feedback(feedback_id: int, user_id: int):
    """标记反馈为已解决（仅管理员）。"""
    conn = get_db()
    row = conn.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
    if row is None or row['role'] != 'admin':
        conn.close()
        return fail(1006, '无权限访问')
    conn.execute('UPDATE feedback SET solved=1 WHERE id=?', (feedback_id,))
    conn.commit()
    conn.close()
    return ok(None, '已标记为已解决')


@app.delete('/api/feedback/{feedback_id}')
def delete_feedback(feedback_id: int, user_id: int):
    """删除反馈（仅管理员，且只能删除已解决的反馈）。"""
    conn = get_db()
    row = conn.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
    if row is None or row['role'] != 'admin':
        conn.close()
        return fail(1006, '无权限访问')
    fb = conn.execute('SELECT solved FROM feedback WHERE id=?', (feedback_id,)).fetchone()
    if fb is None:
        conn.close()
        return fail(1001, '反馈不存在')
    if not fb['solved']:
        conn.close()
        return fail(1008, '只能删除已解决的反馈')
    conn.execute('DELETE FROM feedback WHERE id=?', (feedback_id,))
    conn.commit()
    conn.close()
    return ok(None, '反馈已删除')


# ===== 移动端自动识别：手机访问返回移动端页面，电脑访问返回电脑端 =====
MOBILE_DIR = Path(__file__).parent / 'static_mobile'
MOBILE_UA = ('Android', 'iPhone', 'iPad', 'Mobile', 'MicroMessenger')
MOBILE_FILES = {
    '/': '主页面.html',
    '/index.html': '主页面.html',
    '/主页面.html': '主页面.html',
    '/登录注册.html': '登录注册.html',
    '/对话页.html': '对话页.html',
    '/历史记录.html': '历史记录.html',
    '/问题反馈.html': '问题反馈.html',
}


@app.middleware('http')
async def mobile_detect(request: Request, call_next):
    path = unquote(request.url.path)
    if path.startswith('/api'):
        return await call_next(request)
    ua = request.headers.get('user-agent', '')
    if not any(k in ua for k in MOBILE_UA):
        return await call_next(request)
    filename = MOBILE_FILES.get(path)
    if filename:
        file = MOBILE_DIR / filename
        if file.exists():
            return HTMLResponse(file.read_text(encoding='utf-8'))
    return await call_next(request)


# 托管上传文件（供 Office 在线预览访问）
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount('/uploads', StaticFiles(directory='uploads'), name='uploads')

# 托管前端静态文件（放在所有 API 路由之后，/api/* 优先匹配）
app.mount('/', StaticFiles(directory='static', html=True), name='frontend')

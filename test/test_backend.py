# 后端全接口测试（注册/登录/对话/历史/图片/语音）
import sqlite3
from pathlib import Path

import httpx

BASE = 'http://127.0.0.1:8000'
DB_PATH = 'C:/Users/14218/Desktop/school/backend/star_dream.db'
TEST_DIR = Path('C:/Users/14218/Desktop/school/test')

TEST_USER = 'test_backend_user'
TEST_EMAIL = 'test_backend@example.com'
TEST_PASSWORD = 'test123456'

results = []


def check(name, cond):
    results.append(cond)
    print(('PASS' if cond else 'FAIL') + ' | ' + name)


def post_json(path, data, timeout=120):
    return httpx.post(BASE + path, json=data, timeout=timeout).json()


def get_json(path, timeout=30):
    return httpx.get(BASE + path, timeout=timeout).json()


def cleanup():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('DELETE FROM users WHERE username = ?', (TEST_USER,))
    conn.commit()
    conn.close()


def test_register():
    r = post_json('/api/register', {'username': TEST_USER, 'password': TEST_PASSWORD, 'email': TEST_EMAIL})
    check('注册成功', r['code'] == 0 and bool(r['data'].get('user_id')))
    uid = r['data']['user_id']

    r2 = post_json('/api/register', {'username': TEST_USER, 'password': 'x' * 8, 'email': 'x@y.com'})
    check('用户名已存在返回1002', r2['code'] == 1002)

    r3 = post_json('/api/register', {'username': 'another_user', 'password': 'x' * 8, 'email': TEST_EMAIL})
    check('邮箱已注册返回1003', r3['code'] == 1003)

    r4 = post_json('/api/register', {'username': 'ab', 'password': 'x' * 8, 'email': 'a@b.com'})
    check('用户名格式错误返回1001', r4['code'] == 1001)

    r5 = post_json('/api/register', {'username': 'ok_user', 'password': '123', 'email': 'a@b.com'})
    check('密码过短返回1001', r5['code'] == 1001)
    return uid


def test_login(uid):
    r = post_json('/api/login', {'username': TEST_USER, 'password': TEST_PASSWORD})
    check('登录成功', r['code'] == 0 and r['data']['user_id'] == uid)
    r2 = post_json('/api/login', {'username': TEST_USER, 'password': 'wrong'})
    check('错误密码返回1004', r2['code'] == 1004)
    r3 = post_json('/api/login', {'username': '', 'password': ''})
    check('空字段返回1001', r3['code'] == 1001)


def test_chat(uid):
    r = post_json('/api/chat', {'content': '图书馆怎么预约座位'})
    check('匿名对话被拦截(1005)', r['code'] == 1005)

    r2 = post_json('/api/chat', {'user_id': uid, 'content': '补考政策是什么'})
    check('新对话成功', r2['code'] == 0 and bool(r2['data'].get('conversation_id')))
    cid1 = r2['data']['conversation_id']

    r3 = post_json('/api/chat', {'user_id': uid, 'content': '奖学金怎么申请'})
    check('第二次新对话（归档上一个）', r3['code'] == 0 and bool(r3['data'].get('conversation_id')))
    cid2 = r3['data']['conversation_id']
    return cid1, cid2


def test_history(uid, cid1):
    r = get_json(f'/api/history?user_id={uid}')
    check('历史列表返回', r['code'] == 0)
    ids = [c['conversation_id'] for c in r['data']]
    check('历史包含已归档会话', cid1 in ids)

    r2 = get_json(f'/api/history/{cid1}?user_id={uid}')
    check('会话详情返回消息', r2['code'] == 0 and len(r2['data']) == 2)

    r3 = get_json(f'/api/history/{cid1}?user_id=99999')
    check('越权访问返回1006', r3['code'] == 1006)


def test_image():
    img = TEST_DIR / 'test_image.png'
    if not img.exists():
        print('SKIP | 图片识别（无测试图片）')
        return
    with open(img, 'rb') as f:
        r = httpx.post(BASE + '/api/image', files={'file': ('t.png', f, 'image/png')}, timeout=120).json()
    check('图片识别', r['code'] == 0 and bool(r['data'].get('text')))


def test_voice():
    audio = TEST_DIR / 'test_audio.wav'
    if not audio.exists():
        print('SKIP | 语音识别（无测试音频）')
        return
    with open(audio, 'rb') as f:
        r = httpx.post(BASE + '/api/voice', files={'file': ('t.wav', f, 'audio/wav')}, timeout=180).json()
    check('语音识别', r['code'] == 0 and bool(r['data'].get('text')))


def main():
    uid = test_register()
    test_login(uid)
    cid1, _cid2 = test_chat(uid)
    test_history(uid, cid1)
    test_image()
    test_voice()

    cleanup()
    print('\n' + str(sum(results)) + '/' + str(len(results)) + ' passed')


if __name__ == '__main__':
    main()

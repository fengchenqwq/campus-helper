# 登录/注册接口测试（仅输出 ASCII，避免 Windows 控制台中文乱码）
import json
import urllib.request

BASE = 'http://127.0.0.1:8000'


def post(path, data):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read().decode('utf-8'))
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)}


cases = [
    ('register username too short (2)', '/api/register', {'username': 'ab', 'password': '123456', 'email': 'a@b.com'}, 1001),
    ('register username bad char', '/api/register', {'username': 'a@b', 'password': '123456', 'email': 'a@b.com'}, 1001),
    ('register password too short (5)', '/api/register', {'username': 'user_ok', 'password': '12345', 'email': 'a@b.com'}, 1001),
    ('register password too long (21)', '/api/register', {'username': 'user_ok', 'password': '1' * 21, 'email': 'a@b.com'}, 1001),
    ('register bad email', '/api/register', {'username': 'user_ok', 'password': '123456', 'email': 'bad'}, 1001),
    ('register email exists', '/api/register', {'username': 'user_ok', 'password': '123456', 'email': 'admin@example.com'}, 1003),
    ('register username exists', '/api/register', {'username': 'admin', 'password': '123456', 'email': 'new@b.com'}, 1002),
    ('login empty fields', '/api/login', {'username': '', 'password': ''}, 1001),
    ('login ok', '/api/login', {'username': 'admin', 'password': '123456'}, 0),
    ('login wrong password', '/api/login', {'username': 'admin', 'password': 'wrong'}, 1004),
]

passed = 0
for name, path, data, expect in cases:
    r = post(path, data)
    code = r.get('code')
    is_ok = code == expect
    if is_ok:
        passed += 1
    print(('PASS' if is_ok else 'FAIL') + ' | ' + name + ' | expect=' + str(expect) + ' got=' + str(code))

print('\n' + str(passed) + '/' + str(len(cases)) + ' passed')

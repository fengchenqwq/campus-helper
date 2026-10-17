# 前端自动化测试：使用系统 Edge 浏览器
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path('C:/Users/14218/Desktop/school/frontend')
login_url = (BASE / '登录注册.html').as_uri()
home_url = (BASE / '主页面.html').as_uri()

results = []


def check(name, ok):
    results.append((name, ok))
    print(('PASS' if ok else 'FAIL') + ' | ' + name)


with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page()

    # ===== 1. 登录成功 → 跳转主页面 =====
    page.goto(login_url)
    page.wait_for_load_state('networkidle')
    page.fill('#loginUser', 'admin')
    page.fill('#loginPwd', '123456')
    page.click('#loginBtn')
    try:
        page.wait_for_url(home_url, timeout=10000)
        check('登录成功跳转主页面', True)
    except Exception:
        check('登录成功跳转主页面', False)
        print('  当前URL:', page.url)
        browser.close()
        raise SystemExit(1)

    # 右上角用户名
    page.wait_for_selector('#userArea .username')
    username = page.text_content('#userArea .username').strip()
    check('主页面右上角显示用户名 admin', username == 'admin')

    # ===== 2. 登录失败 → 显示错误提示 =====
    page.goto(login_url)
    page.wait_for_load_state('networkidle')
    page.fill('#loginUser', 'admin')
    page.fill('#loginPwd', 'wrong')
    page.click('#loginBtn')
    page.wait_for_selector('#loginPwdErr.show', timeout=10000)
    err = page.text_content('#loginPwdErr').strip()
    check('登录失败显示错误提示', len(err) > 0)

    # ===== 3. 注册 tab 切换 + 前端校验（两次密码不一致） =====
    page.goto(login_url)
    page.wait_for_load_state('networkidle')
    page.click('.tab[data-tab="register"]')
    page.wait_for_timeout(300)
    page.fill('#regUser', 'abc123')
    page.fill('#regEmail', 'abc@test.com')
    page.fill('#regPwd', '123456')
    page.fill('#regPwd2', '654321')
    page.click('#regBtn')
    page.wait_for_selector('#regPwd2Err.show', timeout=10000)
    err2 = page.text_content('#regPwd2Err').strip()
    check('注册两次密码不一致提示', len(err2) > 0)

    browser.close()

print('\n' + str(sum(1 for _, ok in results if ok)) + '/' + str(len(results)) + ' passed')

import json
import os
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
OUT = "D:/agent_screenshots"  # 截图输出放 D 盘（大文件习惯）
os.makedirs(OUT, exist_ok=True)

# (key, 左侧导航文本) —— 遍历顺序即点击顺序
TABS = [
    ("dashboard", "仪表盘"),
    ("tickets", "工单看板"),
    ("customers", "客户管理"),
    ("knowledge", "知识库"),
    ("rbac", "权限管理"),
    ("monitoring", "监控大屏"),
    ("channels", "渠道管理"),
    ("sessions", "会话管理"),
    ("satisfaction", "满意度"),
    ("notifications", "通知中心"),
]

# 已下载的 chromium 二进制（playwright 1.62 / v1234）
CHROME = (
    "C:/Users/hai/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe"
)

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path=CHROME,
        args=["--no-sandbox", "--disable-gpu"],
    )
    page = browser.new_page(viewport={"width": 1680, "height": 1000})
    page.set_default_timeout(15000)

    # 先导航到同源落地页，获得合法 origin 后再写 localStorage
    try:
        page.goto(BASE, wait_until="load", timeout=30000)
    except Exception as e:
        errors.append(("goto_base", str(e)[:200]))

    # 通过真实登录 API 拿 JWT，再写入 localStorage 绕过登录墙
    token = None
    user = None
    login_payload = json.dumps({"username": "admin", "password": "admin123"}).encode(
        "utf-8"
    )
    login_req = urllib.request.Request(  # noqa: S310 —— URL 为硬编码 localhost 常量，不接受外部输入
        BASE + "/api/v1/auth/login",
        data=login_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(login_req, timeout=10) as resp:  # noqa: S310 —— URL 为硬编码 localhost 常量，不接受外部输入
            login_data = json.loads(resp.read().decode("utf-8"))
            token = login_data["token"]
            user = login_data["user"]
            print("LOGIN_OK", user.get("username"), user.get("role"))
    except Exception as e:
        errors.append(("login", str(e)[:200]))

    if token and user:
        page.evaluate(
            """({ token, user }) => {
          localStorage.setItem('token', token);
          localStorage.setItem('user', JSON.stringify(user));
        }""",
            {"token": token, "user": user},
        )

    # 进入管理后台
    try:
        page.goto(BASE + "/#/admin", wait_until="load", timeout=30000)
    except Exception as e:
        errors.append(("goto", str(e)[:200]))

    # 强制刷新，让 React 在 /#/admin 下重新挂载并读取 localStorage
    page.reload(wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    debug = page.evaluate("""() => {
      return {
        url: window.location.href,
        token: localStorage.getItem('token')?.slice(0, 30) || null,
        user: localStorage.getItem('user'),
        hasTabs: !!document.querySelector('.admin-tabs'),
        loginText: document.body.innerText.includes('请先登录')
      };
    }""")
    print("DEBUG", debug)
    page.screenshot(path=os.path.join(OUT, "00_entry.png"), full_page=True)

    # 逐屏点击 + 截图
    for key, label in TABS:
        try:
            page.locator(".admin-tabs").get_by_text(label, exact=True).first.click(
                timeout=8000
            )
        except Exception as e:
            errors.append((label + "_click", str(e)[:160]))
        page.wait_for_timeout(2200)  # 等 API 数据渲染
        try:
            page.screenshot(path=os.path.join(OUT, f"{key}.png"), full_page=True)
        except Exception as e:
            errors.append((label + "_shot", str(e)[:160]))

    browser.close()

print("DONE")
for e in errors:
    print("ERR", e)

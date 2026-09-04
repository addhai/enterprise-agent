import { test, expect, type Page } from '@playwright/test'

// -----------------------------------------------------------------------------
// 拦截管理后台依赖的 RBAC 接口：无后端时返回「超级管理员」权限，
// 使全部 Tab 在无真实 API 的情况下也能正常渲染（隔离不稳定外部依赖）。
// -----------------------------------------------------------------------------
async function mockAdminRbac(page: Page) {
  await page.route('**/api/v1/rbac/me/permissions', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        role: 'super_admin',
        role_label: '超级管理员',
        permissions: [
          'dashboard:view', 'ticket:view', 'customer:view', 'satisfaction:view',
          'notification:view', 'agent:workspace', 'user:view', 'channel:view',
          'config:view', 'workflow:view', 'evaluation:view', 'monitor:view',
        ],
      }),
    })
  })
}

test.describe('关键用户旅程 E2E', () => {
  // 1) 落地页：核心卖点可见（冒烟）
  test('落地页加载并展示核心卖点', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByTestId('nav-brand')).toBeVisible()
    await expect(page.locator('.hero-title')).toContainText('智能客服平台')
    await expect(page.locator('a.nav-cta')).toBeVisible()
  })

  // 2) 登录：演示模式（纯前端，不依赖后端）→ 进入已登录态
  test('演示模式登录后进入已登录态', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('nav-login').click()
    await expect(page.getByTestId('auth-modal')).toBeVisible()
    await page.getByTestId('demo-login').click()

    const token = await page.evaluate(() => localStorage.getItem('token'))
    expect(token, '演示登录应将 token 写入 localStorage').toBeTruthy()
    await expect(page.getByTestId('nav-user')).toBeVisible()
  })

  // 3) 主题切换：dark/light 切换生效
  test('主题切换生效', async ({ page }) => {
    await page.goto('/')
    const before = await page.evaluate(() =>
      document.documentElement.classList.contains('dark'),
    )
    await page.getByTestId('theme-toggle').click()
    const after = await page.evaluate(() =>
      document.documentElement.classList.contains('dark'),
    )
    expect(after, '点击主题切换后应改变 dark class').toBe(!before)
  })

  // 4) 聊天窗：可打开并显示输入区（WebSocket 离线也不影响 UI 渲染）
  test('聊天窗可打开并显示输入区', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('chat-toggle').click()
    await expect(page.getByTestId('chat-panel')).toBeVisible()
    await expect(page.getByTestId('chat-input')).toBeVisible()
  })

  // 5) 登录后进入管理后台，并可在 Tab 间切换（RBAC 接口被 mock）
  test('演示登录后进入管理后台并可切换 Tab', async ({ page }) => {
    await mockAdminRbac(page)
    await page.goto('/')
    await page.getByTestId('nav-login').click()
    await page.getByTestId('demo-login').click()
    await page.getByTestId('nav-admin').click()

    await page.waitForFunction(() => location.hash.startsWith('#/admin'))
    await expect(page.getByTestId('admin-dashboard')).toBeVisible()
    await expect(page.getByTestId('admin-tab-dashboard')).toBeVisible()

    await page.getByTestId('admin-tab-tickets').click()
    await page.waitForFunction(() => location.hash.startsWith('#/admin/tickets'))
  })

  // 6) 退出登录：回到未登录态
  test('退出登录回到未登录态', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('nav-login').click()
    await page.getByTestId('demo-login').click()
    await page.getByTestId('nav-user').click()
    await expect(page.getByTestId('nav-logout')).toBeVisible()
    await page.getByTestId('nav-logout').click()
    await expect(page.getByTestId('nav-login')).toBeVisible()
  })
})

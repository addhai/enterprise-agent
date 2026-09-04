import { defineConfig, devices } from '@playwright/test'

// =============================================================================
// Enterprise Agent — 前端 E2E 配置 (Playwright)
// -----------------------------------------------------------------------------
// 关键设计：
//  - 用 vite dev server 起 SPA（webServer），无需后端即可跑通「登录 → 后台导航」，
//    因为登录弹窗的「演示模式」是纯前端写 localStorage，后台 RBAC 接口由测试内
//    page.route mock（见 e2e/critical-paths.spec.ts），符合「隔离不稳定外部依赖」原则。
//  - 真实聊天链路依赖 /ws/chat 后端，不在本套 E2E 范围内（需起全套 docker 后另写）。
//  - 选择器统一用 data-testid（在 App.tsx / AdminDashboard.tsx 已补齐），稳定优先。
// =============================================================================

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [['html', { outputFolder: 'playwright-report' }], ['list']]
    : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run dev -- --host --port 4173',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})

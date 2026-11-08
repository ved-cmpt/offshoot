import { defineConfig, devices } from '@playwright/test';

// The smoke checklist of Blueprint Section 15, against the production image: locally through
// compose.prod.yaml (E2E_BASE_URL=http://localhost:8300), or against the public demo with
// E2E_SKIP_RESET=1. It changes one thing, the approval of the module awaiting approval, which
// the daily reset puts back. Nothing in it needs code execution.
export default defineConfig({
  testDir: './smoke',
  globalSetup: './smoke-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 3 * 60 * 1000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  outputDir: 'test-results-smoke',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8300',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});

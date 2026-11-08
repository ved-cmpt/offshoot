import { defineConfig, devices } from '@playwright/test';

// Captures the README's screenshots from a running deployment (by default the public demo).
// It changes nothing: every page is opened read-only.
export default defineConfig({
  testDir: './readme',
  fullyParallel: false,
  workers: 1,
  timeout: 3 * 60 * 1000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  outputDir: 'test-results-readme',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'https://offshoot-go2y.onrender.com',
    viewport: { width: 1280, height: 900 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } } }],
});

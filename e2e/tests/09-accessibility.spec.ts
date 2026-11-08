import { Page, expect, test } from '@playwright/test';

import { expectAccessible, expectNoSidewaysScroll, openBillRite, SCREENSHOTS, signIn, Theme, useTheme } from '../helpers';

// Blueprint Section 10: zero serious or critical axe violations and no sideways scroll, on
// every screen, in both themes, at desktop width and at 375 px.
const SCREENS: { name: string; open: (page: Page) => Promise<void> }[] = [
  {
    name: 'projects',
    open: async (page) => {
      await page.getByRole('link', { name: 'Projects', exact: true }).click();
      await expect(page.locator('.project').first()).toBeVisible();
    },
  },
  {
    name: 'overview',
    open: async (page) => {
      await openBillRite(page);
      await expect(page.locator('.tile').first()).toBeVisible();
    },
  },
  {
    name: 'inventory',
    open: async (page) => {
      await page.getByRole('link', { name: 'Inventory', exact: true }).click();
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    },
  },
  {
    name: 'rules',
    open: async (page) => {
      await page.getByRole('link', { name: 'Rules', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Business rules' })).toBeVisible();
    },
  },
  {
    name: 'plan',
    open: async (page) => {
      await page.getByRole('link', { name: 'Plan', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Service map' })).toBeVisible();
    },
  },
  {
    name: 'modules',
    open: async (page) => {
      await page.getByRole('link', { name: 'Modules', exact: true }).click();
      await expect(page.locator('tbody tr').first()).toBeVisible();
    },
  },
  {
    name: 'module-modern',
    open: async (page) => {
      await page.getByRole('link', { name: 'MTRVAL' }).click();
      await expect(page.getByRole('heading', { name: 'Routing' })).toBeVisible();
      await expect(page.locator('.summary')).toBeVisible();
    },
  },
  {
    name: 'report',
    open: async (page) => {
      await page.getByRole('link', { name: 'Report', exact: true }).click();
      await expect(page.getByRole('heading', { name: /As-Is/ })).toBeVisible();
    },
  },
  {
    name: 'audit',
    open: async (page) => {
      await page.getByRole('link', { name: 'Audit log' }).click();
      await expect(page.locator('tbody tr').first()).toBeVisible();
    },
  },
];

for (const theme of ['light', 'dark'] as Theme[]) {
  for (const width of [1280, 375]) {
    test(`every screen: ${theme} theme at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await useTheme(page, theme);
      await signIn(page, 'architect');
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expectAccessible(page, `projects, ${theme}, ${width}px`);
      for (const screen of SCREENS) {
        await screen.open(page);
        await expectAccessible(page, `${screen.name}, ${theme}, ${width}px`);
        await expectNoSidewaysScroll(page, `${screen.name}, ${theme}, ${width}px`);
        if (width === 375 || theme === 'dark') {
          await page.screenshot({ path: `${SCREENSHOTS}/${screen.name}-${theme}-${width}.png`, fullPage: true });
        }
      }
    });
  }
}

test('the sign-in page in both themes', async ({ page }) => {
  for (const theme of ['light', 'dark'] as Theme[]) {
    await useTheme(page, theme);
    await page.goto('/login');
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    await expectAccessible(page, `login, ${theme}`);
  }
});

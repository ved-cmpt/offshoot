import { Page, expect, test } from '@playwright/test';

import { expectAccessible, expectNoSidewaysScroll, SCREENSHOTS, signIn, skipTour, Theme, useTheme } from '../helpers';

// Blueprint Section 10 and the Run 07 brief: zero serious or critical axe violations and no
// sideways scroll on every page, in both themes, at 375, 768, 1280 and 1440 px. Pages are opened
// by address (the name-based links of ADR-052), so the sweep does not depend on navigation.
const SCREENS: { name: string; path: string; ready: (page: Page) => Promise<void> }[] = [
  { name: 'projects', path: '/app/projects', ready: (p) => expect(p.locator('.project').first()).toBeVisible() },
  { name: 'overview', path: '/app/open/overview', ready: (p) => expect(p.locator('.tile').first()).toBeVisible() },
  {
    name: 'inventory',
    path: '/app/open/inventory',
    ready: (p) => expect(p.getByRole('heading', { name: 'Call graph' })).toBeVisible(),
  },
  {
    name: 'source',
    path: '/app/open/source/RATECALC.cbl?line=135',
    ready: (p) => expect(p.locator('#L135')).toBeVisible(),
  },
  {
    name: 'rules',
    path: '/app/open/rules',
    ready: (p) => expect(p.getByRole('heading', { name: 'Business rules' })).toBeVisible(),
  },
  { name: 'plan', path: '/app/open/plan', ready: (p) => expect(p.getByRole('heading', { name: 'Service map' })).toBeVisible() },
  { name: 'modules', path: '/app/open/modules', ready: (p) => expect(p.locator('tbody tr').first()).toBeVisible() },
  {
    name: 'module-ratecalc',
    path: '/app/open/module/RATECALC',
    ready: (p) => expect(p.getByRole('heading', { name: 'Verification report' })).toBeVisible(),
  },
  {
    name: 'module-mtrval',
    path: '/app/open/module/MTRVAL',
    ready: (p) => expect(p.locator('.summary')).toBeVisible(),
  },
  { name: 'report', path: '/app/open/report', ready: (p) => expect(p.getByRole('heading', { name: /As-Is/ })).toBeVisible() },
  { name: 'audit', path: '/app/admin/audit', ready: (p) => expect(p.locator('tbody tr').first()).toBeVisible() },
];

const WIDTHS = [375, 768, 1280, 1440];

for (const theme of ['dark', 'light'] as Theme[]) {
  test(`every app screen: ${theme} theme at ${WIDTHS.join(', ')} px`, async ({ page }) => {
    await useTheme(page, theme);
    await signIn(page, 'architect');
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      for (const screen of SCREENS) {
        await page.goto(screen.path);
        await screen.ready(page);
        await expectAccessible(page, `${screen.name}, ${theme}, ${width}px`);
        await expectNoSidewaysScroll(page, `${screen.name}, ${theme}, ${width}px`);
        if (width === 375 || width === 1440) {
          await page.screenshot({ path: `${SCREENSHOTS}/${screen.name}-${theme}-${width}.png`, fullPage: true });
        }
      }
    }
  });
}

test('the sign-in page in both themes, at every width', async ({ page }) => {
  await skipTour(page);
  for (const theme of ['light', 'dark'] as Theme[]) {
    await useTheme(page, theme);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/app/login');
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.locator('.account').first()).toBeVisible();
      await expectAccessible(page, `login, ${theme}, ${width}px`);
      await expectNoSidewaysScroll(page, `login, ${theme}, ${width}px`);
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: `${SCREENSHOTS}/login-${theme}-1440.png` });
  }
});

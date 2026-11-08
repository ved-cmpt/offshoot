import { expect, test } from '@playwright/test';

import { SCREENSHOTS, Theme, expectAccessible, expectNoSidewaysScroll, signIn, useTheme } from '../helpers';

const SCREENS = ['plan', 'modules', 'module'] as const;

for (const theme of ['light', 'dark'] as Theme[]) {
  for (const width of [1280, 375]) {
    test(`plan, modules and a module workspace: ${theme} theme at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await useTheme(page, theme);
      await signIn(page, 'architect');
      await page.getByRole('link', { name: 'BillRite' }).first().click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      for (const screen of SCREENS) {
        if (screen === 'plan') {
          await page.getByRole('link', { name: 'Plan', exact: true }).click();
          await expect(page.getByRole('heading', { name: 'Service map' })).toBeVisible();
        } else if (screen === 'modules') {
          await page.getByRole('link', { name: 'Modules', exact: true }).click();
          await expect(page.locator('tbody tr').first()).toBeVisible();
        } else {
          await page.getByRole('link', { name: 'RATECALC' }).click();
          await expect(page.getByRole('heading', { name: 'Verification report' })).toBeVisible();
          await expect(page.locator('.summary')).toBeVisible();
        }
        await expectAccessible(page, `${screen}, ${theme}, ${width}px`);
        await expectNoSidewaysScroll(page, `${screen}, ${theme}, ${width}px`);
        if (width === 375 || theme === 'dark') {
          await page.screenshot({ path: `${SCREENSHOTS}/${screen}-${theme}-${width}.png`, fullPage: true });
        }
      }
    });
  }
}

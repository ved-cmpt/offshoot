import { Page, expect, test } from '@playwright/test';

import { openBillRite, signIn, useTheme } from '../helpers';

const OUT = '../assets/screenshots/readme';

async function openModule(page: Page, program: string): Promise<void> {
  await page.goto('/projects');
  await openBillRite(page);
  await page.getByRole('link', { name: 'Modules', exact: true }).click();
  await page.getByRole('link', { name: program }).click();
  await expect(page.getByRole('heading', { name: program, level: 1 })).toBeVisible();
}

test('README screenshots', async ({ page }) => {
  await useTheme(page, 'light');
  await page.goto('/login');
  await expect(page.locator('.account')).toHaveCount(4);
  await page.screenshot({ path: `${OUT}/sign-in.png` });

  await signIn(page, 'viewer');
  await openBillRite(page);
  await expect(page.getByRole('heading', { name: 'BillRite', level: 1 })).toBeVisible();
  await page.screenshot({ path: `${OUT}/overview.png`, fullPage: true });

  await page.getByRole('link', { name: 'Inventory', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Call graph' })).toBeVisible();
  await page.screenshot({ path: `${OUT}/inventory.png`, fullPage: true });

  await page.getByRole('link', { name: 'Rules', exact: true }).click();
  await expect(page.locator('.rule-card, article').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/rules.png` });

  await openModule(page, 'RATECALC');
  await expect(page.getByRole('region', { name: 'Field-level differences' })).toContainText('RC-OUT-');
  await page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: 'Verification report' }) })
    .first()
    .screenshot({ path: `${OUT}/rounding-defect.png` });

  await openModule(page, 'MTRVAL');
  await expect(page.locator('.summary')).toContainText('500 of 500 cases identical');
  await page.screenshot({ path: `${OUT}/verified-module.png` });
});

import { expect, test } from '@playwright/test';

import { openBillRite, SCREENSHOTS, signIn } from '../helpers';

test.describe('Plan and modules (Blueprint Section 3.1, steps 4 and 5)', () => {
  test('a viewer reads the approved plan in call-graph order and cannot decide it', async ({ page }) => {
    await signIn(page, 'viewer');
    await openBillRite(page);
    await page.getByRole('link', { name: 'Plan', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Version 1: Approved' })).toBeVisible();
    const steps = page.locator('.timeline li');
    await expect(steps).toHaveCount(5);
    await expect(steps.nth(0)).toContainText('MTRVAL');
    await expect(steps.nth(1)).toContainText('RATECALC');
    await expect(steps.nth(2)).toContainText('LATEFEE');
    await expect(steps.nth(3)).toContainText('STMTGEN');
    await expect(steps.nth(4)).toContainText('BILLRUN');
    await expect(page.locator('.service h3')).toHaveText(['meter-service', 'billing-service', 'statement-service']);
    await expect(page.getByText('Half-up rounding')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve plan' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Propose plan' })).toHaveCount(0);
    await page.screenshot({ path: `${SCREENSHOTS}/plan-light.png`, fullPage: true });
  });

  test('the modules list shows each module with numbers from stored runs', async ({ page }) => {
    await signIn(page, 'viewer');
    await openBillRite(page);
    await page.getByRole('link', { name: 'Modules', exact: true }).click();
    const rows = page.locator('tbody tr');
    await expect(rows).toHaveCount(5);
    await expect(rows.filter({ hasText: 'RATECALC' })).toContainText('Blocked by verification');
    await expect(rows.filter({ hasText: 'MTRVAL' })).toContainText('500 of 500');
    await expect(rows.filter({ hasText: 'BILLRUN' })).toContainText('Not migrated yet');
  });
});

import { expect, test } from '@playwright/test';

import { SCREENSHOTS, signIn } from '../helpers';

// Blueprint Section 3.1, steps 6 and 7, in the browser: the banker's-rounding artifact is
// blocked by real mismatches; an engineer repairs it; re-verification passes every case.
test('the rounding defect is visible, repaired and re-verified', async ({ page }) => {
  await signIn(page, 'engineer');
  await page.getByRole('link', { name: 'BillRite' }).first().click();
  await page.getByRole('link', { name: 'Modules', exact: true }).click();
  await page.getByRole('link', { name: 'RATECALC' }).click();

  await expect(page.getByRole('heading', { name: 'RATECALC', level: 1 })).toBeVisible();
  await expect(page.getByText('Blocked by verification').first()).toBeVisible();
  const summary = page.locator('.summary');
  await expect(summary).toContainText(/\d+ of 500 cases identical/);
  const blockedText = await summary.innerText();
  const identical = Number(/(\d+) of 500/.exec(blockedText)?.[1]);
  expect(identical).toBeLessThan(500);

  const diffs = page.getByRole('region', { name: 'Field-level differences' });
  await expect(diffs).toContainText('RC-OUT-');
  const firstRow = diffs.locator('tbody tr').first();
  const legacy = Number(await firstRow.locator('td.num').nth(0).innerText());
  const modern = Number(await firstRow.locator('td.num').nth(1).innerText());
  expect(Math.round((legacy - modern) * 100)).toBe(1);
  await expect(page.locator('.gates li').filter({ hasText: 'Equivalence' })).toContainText('Fail');
  await page.screenshot({ path: `${SCREENSHOTS}/rounding-blocked.png`, fullPage: true });

  await page.getByRole('button', { name: 'Repair', exact: true }).click();
  await expect(page.getByText('Verified, awaiting approval').first()).toBeVisible({ timeout: 8 * 60 * 1000 });
  await expect(page.locator('.summary')).toContainText('500 of 500 cases identical');
  await expect(page.locator('.gates li')).toHaveCount(5);
  for (const gate of await page.locator('.gates li').all()) {
    await expect(gate).toContainText('Pass');
  }
  await page.screenshot({ path: `${SCREENSHOTS}/rounding-repaired.png`, fullPage: true });

  // The mismatch history stays: the first run still shows the defect.
  const history = page.getByRole('region', { name: 'Verification runs' });
  await expect(history.locator('tbody tr')).toHaveCount(2);
  await history.locator('tbody tr').nth(1).getByRole('button').click();
  await expect(page.locator('.summary')).toContainText(`${identical} of 500 cases identical`);
  await expect(page.getByRole('region', { name: 'Field-level differences' })).toContainText('RC-OUT-');
});

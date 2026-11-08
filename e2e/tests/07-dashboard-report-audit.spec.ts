import { readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

import { SCREENSHOTS, apiToken, billriteId, signIn } from '../helpers';

test('the overview shows the stored numbers', async ({ page, request }) => {
  const viewer = await apiToken(request, 'viewer');
  const project = await billriteId(request, viewer);
  const dashboard = await (
    await request.get(`/api/v1/projects/${project}/dashboard`, { headers: { Authorization: `Bearer ${viewer}` } })
  ).json();

  await signIn(page, 'viewer');
  await page.getByRole('link', { name: 'BillRite' }).first().click();
  await expect(page).toHaveURL(/\/overview$/);
  const tiles = page.locator('.tile');
  await expect(tiles.nth(2)).toContainText(`${dashboard.equivalence.identical} of ${dashboard.equivalence.cases}`);
  await expect(tiles.nth(3)).toContainText(`${dashboard.ai.calls} calls`);
  const modern = page.locator('tbody tr').filter({ hasText: 'MTRVAL' });
  await expect(modern).toContainText('Modern');
  await page.screenshot({ path: `${SCREENSHOTS}/overview-light.png`, fullPage: true });
});

test('the assessment report renders and downloads as Markdown', async ({ page }) => {
  await signIn(page, 'viewer');
  await page.getByRole('link', { name: 'BillRite' }).first().click();
  await page.getByRole('link', { name: 'Report', exact: true }).click();
  await expect(page.getByRole('heading', { name: /As-Is/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: /To-Be/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Transition/ })).toBeVisible();
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download Markdown' }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe('assessment-report.md');
  const text = readFileSync(await download.path(), 'utf-8');
  expect(text).toContain('# BillRite modernization assessment');
  expect(text).toContain('## As-Is');
  await page.emulateMedia({ media: 'print' });
  await expect(page.getByRole('button', { name: 'Download Markdown' })).toBeHidden();
  await page.screenshot({ path: `${SCREENSHOTS}/report-print.png`, fullPage: true });
});

test('the audit log is for architects and admins', async ({ page, request }) => {
  const engineer = await apiToken(request, 'engineer');
  expect((await request.get('/api/v1/admin/audit', { headers: { Authorization: `Bearer ${engineer}` } })).status()).toBe(403);

  await signIn(page, 'engineer');
  await expect(page.getByRole('link', { name: 'Audit log' })).toHaveCount(0);
  await page.goto('/admin/audit');
  await expect(page.getByText('Only architects and admins can read the audit log.')).toBeVisible();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);

  await signIn(page, 'architect');
  await page.getByRole('link', { name: 'Audit log' }).click();
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await page.getByLabel('Action').selectOption('facade.');
  await expect(page.locator('tbody tr').first()).toContainText('facade.');
  await page.screenshot({ path: `${SCREENSHOTS}/audit.png`, fullPage: true });
});

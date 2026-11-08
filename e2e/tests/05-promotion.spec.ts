import { expect, test } from '@playwright/test';

import { SCREENSHOTS, signIn } from '../helpers';

const FACADE = process.env.E2E_FACADE_URL ?? 'http://localhost:8200';

// Blueprint Section 3.1, step 8: after the rounding repair, the architect approves RATECALC,
// runs it in shadow mode, and promotes it to modern once the shadow sample is clean. The
// facade then answers from the repaired C#: half-up rounding, as the COBOL does.
test('the repaired module is approved, shadowed and promoted to modern', async ({ page, request }) => {
  await signIn(page, 'architect');
  await page.getByRole('link', { name: 'BillRite' }).first().click();
  await page.getByRole('link', { name: 'Modules', exact: true }).click();
  await page.getByRole('link', { name: 'RATECALC' }).click();
  await expect(page.getByText('Verified and awaiting').first()).toBeVisible();

  await page.getByRole('button', { name: 'Approve module' }).click();
  await expect(page.getByText(/Approved by Ari Architect/)).toBeVisible();
  await page.getByRole('button', { name: 'Start shadow mode' }).click();
  await expect(page.getByText(/0 compared, 0 mismatched/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Promote to modern' })).toBeDisabled();

  await page.getByRole('button', { name: 'Replay recorded traffic' }).click();
  await expect(page.getByText(/20 compared, 0 mismatched/)).toBeVisible({ timeout: 5 * 60 * 1000 });
  await expect(page.getByText(/with none mismatched: met/)).toBeVisible();
  await page.getByRole('button', { name: 'Promote to modern' }).click();
  await expect(page.getByText('to the modern module')).toBeVisible();
  await page.screenshot({ path: `${SCREENSHOTS}/module-modern.png`, fullPage: true });

  // The facade picks up the new route within a few seconds.
  await expect
    .poll(async () => {
      const response = await request.post(`${FACADE}/billing/rate`, {
        data: { customer_class: 'R', month: 10, kwh: 610 },
      });
      return response.headers()['x-parityforge-route'];
    }, { timeout: 30_000 })
    .toBe('modern');
  const answer = await request.post(`${FACADE}/billing/rate`, { data: { customer_class: 'R', month: 10, kwh: 610 } });
  expect(answer.status()).toBe(200);
  const body = await answer.json();
  // 54.72 + 1.185 = 55.905, which COBOL ROUNDED and the repaired module both round up.
  expect(body.energy).toBe('55.91');
  expect(body.total).toBe('61.66');
});

test('the facade refuses bad requests before any backend runs', async ({ request }) => {
  const response = await request.post(`${FACADE}/billing/late-fee`, {
    data: { balance: '-1.00', due_date: '990101', bill_date: '990201', senior: false, credit: '0.00' },
  });
  expect(response.status()).toBe(422);
  expect((await response.json()).error.code).toBe('VALIDATION_ERROR');
});

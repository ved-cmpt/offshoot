import { ConsoleMessage, Page, expect, test } from '@playwright/test';

import { apiToken, billriteId, email, expectAccessible, moduleId, openBillRite, Role, signIn } from '../helpers';

// Blueprint Section 15, smoke checklist: sign-in per role, inventory, a verified module, the
// rounding-defect story, approval in the demo project, the audit log, headers and cookies. It
// runs against the production image, where no code is compiled or run (ADR-047).

const ROLES: Role[] = ['viewer', 'engineer', 'architect', 'admin'];

function watchPolicy(page: Page): string[] {
  const violations: string[] = [];
  page.on('console', (message: ConsoleMessage) => {
    if (/Content.Security.Policy|Refused to/i.test(message.text())) {
      violations.push(message.text());
    }
  });
  page.on('pageerror', (error) => violations.push(String(error)));
  return violations;
}

async function openModule(page: Page, program: string): Promise<void> {
  await openBillRite(page);
  await page.getByRole('link', { name: 'Modules', exact: true }).click();
  await page.getByRole('link', { name: program }).click();
  await expect(page.getByRole('heading', { name: program, level: 1 })).toBeVisible();
}

test('the app and the API send the security headers', async ({ request }) => {
  const page = await request.get('/');
  expect(page.status()).toBe(200);
  const headers = page.headers();
  const policy = headers['content-security-policy'];
  expect(policy).toContain("default-src 'self'");
  expect(policy).toContain("script-src 'self'");
  expect(policy).toMatch(/style-src 'self' 'nonce-[^']+'/);
  expect(policy).toContain("frame-ancestors 'none'");
  expect(policy).not.toContain('unsafe-inline');
  expect(headers['x-content-type-options']).toBe('nosniff');
  expect(headers['x-frame-options']).toBe('DENY');
  expect(headers['referrer-policy']).toBe('no-referrer');
  expect(headers['strict-transport-security']).toMatch(/^max-age=\d+/);
  expect(await page.text()).toMatch(/ngCspNonce="[^"]+"/);

  const api = await request.get('/api/v1/config');
  expect(api.headers()['content-security-policy']).toContain("default-src 'none'");
  expect(api.headers()['cache-control']).toBe('no-store');
  const config = (await api.json()) as { demo_mode: boolean; execution_enabled: boolean; ai_mode: string };
  expect(config).toMatchObject({ demo_mode: true, execution_enabled: false, ai_mode: 'mock' });
});

test('the refresh cookie is HttpOnly, Secure and SameSite=Strict, and only for the auth path', async ({
  request,
}) => {
  const token = await apiToken(request, 'viewer');
  expect(token.length).toBeGreaterThan(20);
  const login = await request.post('/api/v1/auth/login', {
    data: { email: email('viewer'), password: process.env.DEMO_PASSWORD_VIEWER ?? 'demo-viewer-pass' },
  });
  const cookie = login.headersArray().find((header) => header.name.toLowerCase() === 'set-cookie')?.value ?? '';
  expect(cookie).toMatch(/HttpOnly/i);
  expect(cookie).toMatch(/Secure/i);
  expect(cookie).toMatch(/SameSite=strict/i);
  expect(cookie).toMatch(/Path=\/api\/v1\/auth/i);
});

for (const role of ROLES) {
  test(`the ${role} can sign in and out`, async ({ page }) => {
    const violations = watchPolicy(page);
    await signIn(page, role);
    await expect(page.locator('.role-badge')).toContainText(role.toUpperCase());
    await expect(page.locator('.demo-banner')).toContainText('No code is compiled or run here');
    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect(violations).toEqual([]);
  });
}

test('a viewer browses the inventory and its call graph', async ({ page }) => {
  const violations = watchPolicy(page);
  await signIn(page, 'viewer');
  await openBillRite(page);
  await page.getByRole('link', { name: 'Inventory', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Inventory', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Call graph' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Programs table' })).toContainText('RATECALC');
  await expectAccessible(page, 'inventory (production)');
  expect(violations).toEqual([]);
});

test('a verified module shows its stored equivalence report, and nothing can be run', async ({ page }) => {
  const violations = watchPolicy(page);
  await signIn(page, 'engineer');
  await openModule(page, 'MTRVAL');
  await expect(page.locator('.summary')).toContainText('500 of 500 cases identical');
  await expect(page.getByTestId('execution-off')).toContainText('does not compile or run code');
  for (const name of ['Migrate', 'Repair', 'Verify again', 'Run mutation testing', 'Replay recorded traffic']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  }
  await expectAccessible(page, 'module (production)');
  expect(violations).toEqual([]);
});

test('the rounding defect is shown from the stored run', async ({ page }) => {
  await signIn(page, 'viewer');
  await openModule(page, 'RATECALC');
  await expect(page.getByText('Blocked by verification').first()).toBeVisible();
  const summary = await page.locator('.summary').innerText();
  const identical = Number(/(\d+) of 500/.exec(summary)?.[1]);
  expect(identical).toBeLessThan(500);
  const diffs = page.getByRole('region', { name: 'Field-level differences' });
  await expect(diffs).toContainText('RC-OUT-');
  const firstRow = diffs.locator('tbody tr').first();
  const legacy = Number(await firstRow.locator('td.num').nth(0).innerText());
  const modern = Number(await firstRow.locator('td.num').nth(1).innerText());
  expect(Math.round((legacy - modern) * 100)).toBe(1);
});

test('the server refuses to run code, whatever the screen shows', async ({ request }) => {
  const token = await apiToken(request, 'engineer');
  const project = await billriteId(request, token);
  const ratecalc = await moduleId(request, token, project, 'RATECALC');
  const response = await request.post(`/api/v1/modules/${ratecalc}/repair`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.status()).toBe(403);
  expect(((await response.json()) as { error: { code: string } }).error.code).toBe('EXECUTION_DISABLED');
});

test('the architect approves the module awaiting approval, which the audit log records', async ({ page }) => {
  await signIn(page, 'architect');
  await openModule(page, 'STMTGEN');
  const approve = page.getByRole('button', { name: 'Approve module' });
  if (await approve.count()) {
    await approve.click();
  }
  // On the public demo another visitor may have approved it already today.
  await expect(page.getByText(/Approved by /).first()).toBeVisible();
  await page.getByRole('link', { name: 'Audit log' }).click();
  await expect(page.getByRole('heading', { name: 'Audit log', level: 1 })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Audit entries' })).toContainText('module.');
  await expectAccessible(page, 'audit log (production)');
});

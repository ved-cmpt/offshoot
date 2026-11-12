import { ConsoleMessage, Page, expect, test } from '@playwright/test';

import { apiToken, billriteId, expectAccessible, moduleId, openBillRite, password, Role, signIn, username } from '../helpers';

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

test('the page and every script it loads are UTF-8, with no replacement characters', async ({
  page,
  request,
}) => {
  const index = await request.get('/');
  expect(index.headers()['content-type']).toBe('text/html; charset=utf-8');
  const html = await index.text();
  expect(html).toContain('<meta charset="utf-8">');
  // Every script the app can load: the entry points, then the lazy chunks they name.
  const seen = new Set<string>();
  const queue = [...html.matchAll(/src="([^"]+\.js)"/g)].map((match) => match[1]);
  while (queue.length) {
    const name = queue.shift()!.replace(/^\.\//, '');
    if (seen.has(name)) continue;
    seen.add(name);
    const script = await request.get(`/${name}`);
    expect(script.status(), name).toBe(200);
    expect(script.headers()['content-type'], name).toContain('charset=utf-8');
    const bytes = await script.body();
    expect(bytes.includes(Buffer.from([0xef, 0xbf, 0xbd])), `${name} holds U+FFFD`).toBe(false);
    for (const match of bytes.toString('utf-8').matchAll(/\.\/(chunk-[A-Za-z0-9_-]+\.js)/g)) {
      queue.push(match[1]);
    }
  }
  expect(seen.size).toBeGreaterThan(3);

  await signIn(page, 'viewer');
  const banner = await page.locator('.demo-banner').innerText();
  expect(banner).toContain('Public demo \u2014 synthetic COBOL app');
  expect(await page.locator('body').innerText()).not.toContain('\ufffd');
});

test('the refresh cookie is HttpOnly, Secure and SameSite=Strict, and only for the auth path', async ({
  request,
}) => {
  const token = await apiToken(request, 'viewer');
  expect(token.length).toBeGreaterThan(20);
  const login = await request.post('/api/v1/auth/login', {
    data: { username: username('viewer'), password: password() },
  });
  const cookie = login.headersArray().find((header) => header.name.toLowerCase() === 'set-cookie')?.value ?? '';
  expect(cookie).toMatch(/HttpOnly/i);
  expect(cookie).toMatch(/Secure/i);
  expect(cookie).toMatch(/SameSite=strict/i);
  expect(cookie).toMatch(/Path=\/api\/v1\/auth/i);
});

test('the sign-in page lists the four usernames and the one published password', async ({ page }) => {
  await page.goto('/app/login');
  const cards = page.locator('.account');
  await expect(cards).toHaveCount(4);
  for (const role of ROLES) {
    await expect(page.locator('.account__credentials').filter({ hasText: username(role) }).first()).toBeVisible();
  }
  await expect(page.locator('.account__credentials').first()).toContainText(password());
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
  // A busy public log fills its first page with sign-ins, so filter to module decisions.
  await page.getByLabel('Action').selectOption('module.');
  await expect(page.getByRole('region', { name: 'Audit entries' })).toContainText('module.');
  await expectAccessible(page, 'audit log (production)');
});

test('the demo admin cannot add users, change passwords or disable a demo account', async ({ request }) => {
  const token = await apiToken(request, 'admin');
  const headers = { Authorization: `Bearer ${token}` };
  const users = (await (await request.get('/api/v1/admin/users', { headers })).json()) as {
    id: string;
    username: string | null;
  }[];
  const viewer = users.find((user) => user.username === 'viewer');
  expect(viewer, 'the viewer account').toBeDefined();
  const attempts = [
    request.post('/api/v1/admin/users', {
      headers,
      data: { email: 'x@example.test', display_name: 'X', role: 'ADMIN', password: 'long-enough-1' },
    }),
    request.post(`/api/v1/admin/users/${viewer!.id}/password`, { headers, data: { password: 'long-enough-1' } }),
    request.patch(`/api/v1/admin/users/${viewer!.id}`, { headers, data: { active: false } }),
  ];
  for (const response of await Promise.all(attempts)) {
    expect(response.status()).toBe(403);
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe('DEMO_ACCOUNTS_LOCKED');
  }
  // Still active. (Checked here rather than by signing in, which the per-account limit would count.)
  const after = (await (await request.get('/api/v1/admin/users', { headers })).json()) as {
    username: string | null;
    active: boolean;
  }[];
  expect(after.find((user) => user.username === 'viewer')?.active).toBe(true);
});

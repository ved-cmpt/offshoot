import AxeBuilder from '@axe-core/playwright';
import { APIRequestContext, Page, expect } from '@playwright/test';
import { resolve } from 'node:path';

export type Role = 'viewer' | 'engineer' | 'architect' | 'admin';
export type Theme = 'light' | 'dark';

// The published demo accounts (synthetic data only, ADR-050): the role's name as the username,
// and one password. DEMO_PASSWORD overrides it for a stack that uses another.
const PASSWORD = process.env.DEMO_PASSWORD ?? 'demo1234';

export function username(role: Role): string {
  return role;
}

export function password(): string {
  return PASSWORD;
}

export const SCREENSHOTS = resolve(__dirname, '..', 'assets', 'screenshots');

export async function useTheme(page: Page, theme: Theme): Promise<void> {
  await page.addInitScript((value) => {
    try {
      window.localStorage.setItem('offshoot-theme', value);
    } catch {
      // Storage blocked: the default theme applies.
    }
  }, theme);
}

export async function signIn(page: Page, role: Role): Promise<void> {
  await page.goto('/app/login');
  await page.getByLabel('Username').fill(username(role));
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
}

/** Open the bundled BillRite project from the projects list, and wait until it is open:
 * the list shows a Modules link for every project, so clicking on before it changes is ambiguous. */
export async function openBillRite(page: Page): Promise<void> {
  await page.getByRole('link', { name: 'BillRite', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'BillRite', level: 1, exact: true })).toBeVisible();
}

/** The BillRite project's id, through the UI's own API. */
export async function billriteId(request: APIRequestContext, token: string): Promise<string> {
  const response = await request.get('/api/v1/projects', { headers: { Authorization: `Bearer ${token}` } });
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as { items: { id: string; name: string; source_kind: string }[] };
  const project = body.items.find((item) => item.name === 'BillRite' && item.source_kind === 'BUNDLED');
  expect(project, 'the seeded BillRite project').toBeDefined();
  return project!.id;
}

export async function apiToken(request: APIRequestContext, role: Role): Promise<string> {
  const response = await request.post('/api/v1/auth/login', {
    data: { username: username(role), password: PASSWORD },
  });
  expect(response.status()).toBe(200);
  return ((await response.json()) as { access_token: string }).access_token;
}

export async function moduleId(request: APIRequestContext, token: string, projectId: string, program: string): Promise<string> {
  const response = await request.get(`/api/v1/projects/${projectId}/modules`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const modules = (await response.json()) as { id: string; program: string }[];
  const found = modules.find((item) => item.program === program);
  expect(found, `module ${program}`).toBeDefined();
  return found!.id;
}

/** Zero serious or critical axe violations (Blueprint Section 10). */
export async function expectAccessible(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  const serious = results.violations.filter((item) => item.impact === 'serious' || item.impact === 'critical');
  expect(
    serious.map((item) => `${item.id}: ${item.nodes.map((node) => node.target.join(' ')).join(', ')}`),
    `${label}: serious or critical axe violations`,
  ).toEqual([]);
}

/** No sideways page scroll (Blueprint Section 10: usable down to 375 px). */
export async function expectNoSidewaysScroll(page: Page, label: string): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `${label}: horizontal overflow in px`).toBeLessThanOrEqual(0);
}

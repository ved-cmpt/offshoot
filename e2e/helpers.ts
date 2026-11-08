import AxeBuilder from '@axe-core/playwright';
import { APIRequestContext, Page, expect } from '@playwright/test';
import { resolve } from 'node:path';

export type Role = 'viewer' | 'engineer' | 'architect' | 'admin';
export type Theme = 'light' | 'dark';

// The published demo accounts (synthetic data only). Override through the environment
// when a stack uses other passwords.
const PASSWORDS: Record<Role, string> = {
  viewer: process.env.DEMO_PASSWORD_VIEWER ?? 'demo-viewer-pass',
  engineer: process.env.DEMO_PASSWORD_ENGINEER ?? 'demo-engineer-pass',
  architect: process.env.DEMO_PASSWORD_ARCHITECT ?? 'demo-architect-pass',
  admin: process.env.DEMO_PASSWORD_ADMIN ?? 'demo-admin-pass',
};

export function email(role: Role): string {
  return `${role}@demo.parityforge.dev`;
}

export const SCREENSHOTS = resolve(__dirname, '..', 'assets', 'screenshots');

export async function useTheme(page: Page, theme: Theme): Promise<void> {
  await page.addInitScript((value) => {
    try {
      window.localStorage.setItem('parityforge-theme', value);
    } catch {
      // Storage blocked: the default theme applies.
    }
  }, theme);
}

export async function signIn(page: Page, role: Role): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email(role));
  await page.getByLabel('Password').fill(PASSWORDS[role]);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
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
    data: { email: email(role), password: PASSWORDS[role] },
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

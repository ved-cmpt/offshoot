import { expect, test } from '@playwright/test';

import { apiToken, billriteId, moduleId, openBillRite, signIn } from '../helpers';

// Blueprint Section 3.4: the server refuses, not only the hidden buttons.
test.describe('Role denials', () => {
  test('a viewer cannot start jobs and an engineer cannot decide', async ({ request }) => {
    const viewer = await apiToken(request, 'viewer');
    const engineer = await apiToken(request, 'engineer');
    const project = await billriteId(request, viewer);
    const module = await moduleId(request, viewer, project, 'STMTGEN');
    const as = (token: string) => ({ headers: { Authorization: `Bearer ${token}` } });

    for (const action of ['migrate', 'repair', 'verify', 'mutate']) {
      const response = await request.post(`/api/v1/modules/${module}/${action}`, as(viewer));
      expect(response.status(), `viewer ${action}`).toBe(403);
    }
    expect((await request.post(`/api/v1/projects/${project}/plan`, as(viewer))).status()).toBe(403);
    const decision = await request.post(`/api/v1/projects/${project}/plan/decision`, {
      ...as(engineer),
      data: { decision: 'APPROVED', expected_version: 1 },
    });
    expect(decision.status()).toBe(403);
    const exception = await request.post(`/api/v1/modules/${module}/gate-exceptions`, {
      ...as(engineer),
      data: { gate: 'COVERAGE', threshold: 1, reason: 'no', expected_version: 1 },
    });
    expect(exception.status()).toBe(403);
    expect((await request.post(`/api/v1/modules/${module}/migrate`)).status()).toBe(401);
  });

  test('a viewer sees no actions in the module workspace', async ({ page }) => {
    await signIn(page, 'viewer');
    await openBillRite(page);
    await page.getByRole('link', { name: 'Modules', exact: true }).click();
    await page.getByRole('link', { name: 'STMTGEN' }).click();
    await expect(page.getByRole('heading', { name: 'Gates' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Actions' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Record exception' })).toHaveCount(0);
  });
});

import { expect, test } from '@playwright/test';

import { apiToken, billriteId, moduleId } from '../helpers';

// Blueprint Sections 3.4 and 14: the gates and roles hold when called directly.
test('approval and promotion are refused without the evidence or the role', async ({ request }) => {
  const architect = await apiToken(request, 'architect');
  const engineer = await apiToken(request, 'engineer');
  const viewer = await apiToken(request, 'viewer');
  const project = await billriteId(request, viewer);
  const as = (token: string) => ({ Authorization: `Bearer ${token}` });
  const detail = async (program: string) => {
    const id = await moduleId(request, viewer, project, program);
    const response = await request.get(`/api/v1/modules/${id}`, { headers: as(viewer) });
    return response.json();
  };

  const billrun = await detail('BILLRUN');
  const pending = await request.post(`/api/v1/modules/${billrun.id}/decision`, {
    headers: as(architect),
    data: { decision: 'APPROVED', expected_version: billrun.version },
  });
  expect(pending.status()).toBe(409);
  expect((await pending.json()).error.code).toBe('VERIFICATION_REQUIRED');

  const stmtgen = await detail('STMTGEN');
  expect(stmtgen.state).toBe('VERIFIED');
  for (const token of [engineer, viewer]) {
    const response = await request.post(`/api/v1/modules/${stmtgen.id}/decision`, {
      headers: as(token),
      data: { decision: 'APPROVED', expected_version: stmtgen.version },
    });
    expect(response.status()).toBe(403);
  }
  const notApproved = await request.post(`/api/v1/modules/${stmtgen.id}/facade-mode`, {
    headers: as(architect),
    data: { mode: 'MODERN', expected_version: stmtgen.version },
  });
  expect((await notApproved.json()).error.code).toBe('NOT_APPROVED');

  const latefee = await detail('LATEFEE');
  expect(latefee.facade_mode).toBe('SHADOW');
  expect(latefee.shadow.compared).toBeLessThan(latefee.shadow.sample);
  const early = await request.post(`/api/v1/modules/${latefee.id}/facade-mode`, {
    headers: as(architect),
    data: { mode: 'MODERN', expected_version: latefee.version },
  });
  expect(early.status()).toBe(409);
  expect((await early.json()).error.code).toBe('SHADOW_GATE');
  const engineerMode = await request.post(`/api/v1/modules/${latefee.id}/facade-mode`, {
    headers: as(engineer),
    data: { mode: 'LEGACY', expected_version: latefee.version },
  });
  expect(engineerMode.status()).toBe(403);
});

test('uploads are refused in the public demo', async ({ request, page }) => {
  const engineer = await apiToken(request, 'engineer');
  const response = await request.post('/api/v1/projects', {
    headers: { Authorization: `Bearer ${engineer}` },
    multipart: { name: 'Mine', archive: { name: 'a.zip', mimeType: 'application/zip', buffer: Buffer.from('PK') } },
  });
  expect(response.status()).toBe(403);
  expect((await response.json()).error.code).toBe('UPLOADS_DISABLED');

  const { signIn } = await import('../helpers');
  await signIn(page, 'engineer');
  await expect(page.getByText('Uploads are turned off in the public demo')).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
});

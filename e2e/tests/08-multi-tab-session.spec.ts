import { expect, test } from '@playwright/test';

import { openBillRite, signIn } from '../helpers';

// ADR-018: the refresh cookie rotates and reuse revokes the session, so two tabs refreshing
// at the same moment must not sign each other out. The app serializes refreshes across tabs.
test('two tabs reloading together both stay signed in', async ({ context, page }) => {
  await signIn(page, 'engineer');
  const second = await context.newPage();
  await second.goto('/app/projects');
  await expect(second.getByRole('heading', { name: 'Projects' })).toBeVisible();

  for (let round = 0; round < 3; round++) {
    await Promise.all([page.reload(), second.reload()]);
    for (const tab of [page, second]) {
      await expect(tab).toHaveURL(/\/projects$/);
      await expect(tab.locator('.role-badge')).toContainText('ENGINEER');
      await expect(tab.getByRole('link', { name: 'BillRite', exact: true }).first()).toBeVisible();
    }
  }
  // Each tab still holds a working session for API calls.
  await openBillRite(second);
  await expect(second.locator('.tile').first()).toBeVisible();
});

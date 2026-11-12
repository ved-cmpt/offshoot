import { Page, expect, test } from '@playwright/test';

import { signIn, useTheme } from '../helpers';

const OUT = '../assets/screenshots/readme';

async function settle(page: Page): Promise<void> {
  await page.waitForTimeout(1200);
}

// Captures the README's screenshots from a running deployment (by default the public demo),
// dark first, as the product is designed. It changes nothing: every page is opened read-only.
test('README screenshots', async ({ page }) => {
  await useTheme(page, 'dark');
  await page.emulateMedia({ reducedMotion: 'reduce' });

  await page.goto('/');
  await expect(page.locator('app-hero-visual')).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/landing-hero.png` });
  await page.goto('/#demo');
  await expect(page.getByRole('tabpanel')).toBeVisible();
  await settle(page);
  await page.locator('#demo').screenshot({ path: `${OUT}/landing-demos.png` });

  await signIn(page, 'viewer');
  await page.goto('/app/open/overview');
  await expect(page.locator('.tile').first()).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/overview.png` });

  await page.goto('/app/open/module/RATECALC');
  await expect(page.getByRole('region', { name: 'Field-level differences' })).toContainText('RC-OUT-');
  await settle(page);
  await page.screenshot({ path: `${OUT}/rounding-defect.png` });
  await page.locator('#report').screenshot({ path: `${OUT}/rounding-report.png` });

  await page.goto('/app/open/module/MTRVAL');
  await expect(page.locator('.summary')).toContainText('500 of 500 cases identical');
  await settle(page);
  await page.screenshot({ path: `${OUT}/verified-module.png` });

  await page.goto('/app/open/inventory');
  await expect(page.getByRole('heading', { name: 'Call graph' })).toBeVisible();
  await settle(page);
  await page.locator('section', { has: page.getByRole('heading', { name: 'Call graph' }) }).screenshot({
    path: `${OUT}/call-graph.png`,
  });

  await page.goto('/app/open/rules');
  await expect(page.locator('app-rule-card').first()).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/rules.png` });

  await page.goto('/app/open/overview');
  await page.keyboard.press('Control+k');
  await page.getByRole('combobox').fill('rate');
  await settle(page);
  await page.screenshot({ path: `${OUT}/command-palette.png` });

  await useTheme(page, 'light');
  await page.goto('/app/open/module/RATECALC');
  await expect(page.getByRole('heading', { name: 'RATECALC', level: 1 })).toBeVisible();
  await settle(page);
  await page.screenshot({ path: `${OUT}/rounding-defect-light.png` });
});

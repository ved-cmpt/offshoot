import { expect, test } from '@playwright/test';

import { expectAccessible, openBillRite, password, SCREENSHOTS, signIn, username } from '../helpers';

// The app shell (Run 07): command palette, keyboard shortcuts, sidebar, breadcrumbs, the
// phone drawer and the first-visit tour.
test.describe('App shell', () => {
  test('the command palette jumps to a module, and runs actions', async ({ page }) => {
    await signIn(page, 'architect');
    await openBillRite(page);
    await page.keyboard.press('Control+k');
    const search = page.getByRole('combobox', { name: 'Search screens, modules, rules and actions' });
    await expect(search).toBeFocused();
    await expect(page.getByRole('option', { name: /RATECALC/ }).first()).toBeVisible();
    await expectAccessible(page, 'command palette');
    await page.screenshot({ path: `${SCREENSHOTS}/palette-dark.png` });
    await search.fill('ratecalc');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { name: 'RATECALC', level: 1 })).toBeVisible();

    await page.keyboard.press('Control+k');
    await search.fill('keyboard shortcuts');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { name: 'Keyboard shortcuts' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('heading', { name: 'Keyboard shortcuts' })).toBeHidden();
  });

  test('a rule found in the palette opens on the rules screen, outlined', async ({ page }) => {
    await signIn(page, 'viewer');
    await openBillRite(page);
    await page.keyboard.press('Control+k');
    await page.getByRole('combobox').fill('Century window');
    await expect(page.getByRole('option', { name: /Century window for two-digit years/ })).toBeVisible();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/rules\?program=LATEFEE&rule=/);
    await expect(page.locator('article.card--focus')).toContainText('Century window for two-digit years');
  });

  test('G then a letter goes to a screen, ? shows the shortcuts and T switches the theme', async ({ page }) => {
    await signIn(page, 'engineer');
    await openBillRite(page);
    await page.locator('main').click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('g');
    await page.keyboard.press('m');
    await expect(page).toHaveURL(/\/modules$/);
    await page.keyboard.press('Shift+?');
    await expect(page.getByRole('heading', { name: 'Keyboard shortcuts' })).toBeVisible();
    await page.keyboard.press('Escape');
    const before = await page.locator('html').getAttribute('data-theme');
    await page.keyboard.press('t');
    await expect(page.locator('html')).not.toHaveAttribute('data-theme', before ?? '');
  });

  test('breadcrumbs, the project switcher and the collapsible sidebar', async ({ page }) => {
    await signIn(page, 'viewer');
    await page.goto('/app/open/module/LATEFEE');
    const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' });
    await expect(crumbs).toContainText('Projects');
    await expect(crumbs).toContainText('BillRite');
    await expect(crumbs.locator('[aria-current="page"]')).toHaveText('LATEFEE');
    await crumbs.getByRole('link', { name: 'Modules' }).click();
    await expect(page).toHaveURL(/\/modules$/);

    await page.getByRole('button', { name: /Project\s*BillRite/ }).click();
    await expect(page.locator('#project-switcher')).toContainText('BillRite live sample');
    await page.keyboard.press('Escape');

    await page.getByRole('button', { name: 'Collapse the sidebar' }).click();
    await expect(page.locator('.layout')).toHaveClass(/layout--collapsed/);
    await expect(page.getByRole('link', { name: 'Inventory', exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('button', { name: 'Expand the sidebar' })).toBeVisible();
    await page.screenshot({ path: `${SCREENSHOTS}/sidebar-collapsed-dark.png` });
    await page.getByRole('button', { name: 'Expand the sidebar' }).click();
  });

  test('on a phone the sidebar is a drawer', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await signIn(page, 'architect');
    await expect(page.getByRole('link', { name: 'Audit log' })).toBeHidden();
    await page.getByRole('button', { name: 'Menu' }).click();
    await page.getByRole('link', { name: 'Audit log' }).click();
    await expect(page.getByRole('heading', { name: 'Audit log', level: 1 })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Menu' })).toHaveAttribute('aria-expanded', 'false');
  });

  test('the first visit to the demo offers the rounding tour, once', async ({ page }) => {
    // No skipTour here: this is the visitor who has never seen it.
    await page.goto('/app/login');
    await page.getByLabel('Username').fill(username('viewer'));
    await page.getByLabel('Password').fill(password());
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    const tour = page.getByRole('dialog', { name: 'Welcome to the live demo' });
    await expect(tour).toBeVisible();
    await expectAccessible(page, 'tour');
    await tour.getByRole('button', { name: 'Start the tour' }).click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.getByRole('dialog', { name: 'Everything is measured' })).toBeVisible();
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByRole('heading', { name: 'RATECALC', level: 1 })).toBeVisible();
    await expect(page.locator('#gates')).toHaveClass(/tour-target/);
    await page.screenshot({ path: `${SCREENSHOTS}/tour-dark.png` });
    await page.getByRole('button', { name: 'End tour' }).click();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'RATECALC', level: 1 })).toBeVisible();
    await expect(page.getByRole('dialog', { name: /tour|Welcome/ })).toHaveCount(0);
  });
});

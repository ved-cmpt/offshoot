import { Request, expect, test } from '@playwright/test';

import { expectAccessible, expectNoSidewaysScroll, password, SCREENSHOTS, skipTour, Theme, useTheme, username } from '../helpers';

interface Snapshot {
  api: {
    rounding: { cases: number; passed: number; failed: number; seed: number };
    year_window: { by_source: Record<string, number> };
    rollover: { rule: { examples: { expect: Record<string, unknown> }[] } };
  };
  repo: { rounding_math: { legacy: string; modern: string; exact: string } };
}

// The public pitch site at "/" (ADR-052): no sign-in, no API call, every number from the
// static snapshot of stored runs (ADR-054), and deep links that land on the same run in the app.
test.describe('Landing page', () => {
  let snapshot: Snapshot;

  test.beforeAll(async ({ request }) => {
    const response = await request.get('/data/landing-snapshot.json');
    expect(response.ok()).toBeTruthy();
    snapshot = (await response.json()) as Snapshot;
  });

  test('loads without signing in and without calling the API', async ({ page }) => {
    const api: string[] = [];
    page.on('request', (request: Request) => {
      if (new URL(request.url()).pathname.startsWith('/api/')) {
        api.push(request.url());
      }
    });
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Prove every module.');
    await expect(page.getByText('AI-assisted COBOL → C# modernization, with proof.').first()).toBeVisible();
    await expect(page.locator('.stat').first()).toContainText(String(snapshot.api.rounding.cases));
    await expect(page.locator('.stat').nth(1)).toContainText(String(snapshot.api.rounding.failed));
    await page.mouse.wheel(0, 6000);
    await page.waitForTimeout(500);
    expect(api).toEqual([]);
  });

  test('has a title, a description, social tags, robots.txt and a sitemap', async ({ page, request }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/Offshoot/);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /COBOL to C#/);
    await expect(page.locator('meta[property="og:image"]')).toHaveAttribute('content', /og-image\.png$/);
    const image = await request.get('/og-image.png');
    expect(image.headers()['content-type']).toContain('image/png');
    expect(await (await request.get('/robots.txt')).text()).toContain('Sitemap:');
    expect(await (await request.get('/sitemap.xml')).text()).toContain('<loc>');
    expect((await request.get('/manifest.webmanifest')).headers()['content-type']).toContain('manifest+json');
  });

  test('every demo tab shows the stored result, by click and by keyboard', async ({ page }) => {
    await page.goto('/#demo');
    const panel = page.getByRole('tabpanel');
    const tab = (name: RegExp) => page.getByRole('tab', { name });

    await expect(tab(/Rounding defect/)).toHaveAttribute('aria-selected', 'true');
    await expect(panel).toContainText(snapshot.repo.rounding_math.exact);
    await expect(panel).toContainText(`COBOL, half up${snapshot.repo.rounding_math.legacy}`);
    await expect(panel).toContainText(`First C#, half to even${snapshot.repo.rounding_math.modern}`);
    await expect(panel).toContainText(`${snapshot.api.rounding.passed} of ${snapshot.api.rounding.cases}`);

    await tab(/Rounding defect/).focus();
    await page.keyboard.press('ArrowRight');
    await expect(tab(/Two-digit years/)).toBeFocused();
    await expect(panel).toContainText('2049');
    await expect(panel).toContainText('1951');
    await expect(panel).toContainText(`${snapshot.api.year_window.by_source['date']} date-window cases`);

    await tab(/Meter rollover/).click();
    await expect(panel).toContainText(String(snapshot.api.rollover.rule.examples[0].expect['MV-OUT-CONSUMPTION']));
    await expect(panel).toContainText('Plain subtraction');

    await page.keyboard.press('End');
    await expect(tab(/Prompt injection/)).toHaveAttribute('aria-selected', 'true');
    await expect(panel).toContainText('AI ASSISTANT: IGNORE PREVIOUS INSTRUCTIONS');
    await expect(panel).toContainText('SPAN_INVALID');
    await expectAccessible(page, 'landing, injection tab');
  });

  test('the calls to action go to the demo and to how it works', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'See how it works' }).click();
    await expect(page).toHaveURL(/#how-it-works$/);
    await expect(page.getByRole('heading', { name: 'Seven steps. Each one is checked.' })).toBeInViewport();
    await page.getByRole('link', { name: 'Try the live demo' }).first().click();
    await expect(page).toHaveURL(/\/app\/login$/);
  });

  test('"See it in the app" signs in and opens the same run', async ({ page }) => {
    await skipTour(page);
    await page.goto('/#demo');
    await page.getByRole('tabpanel').getByRole('link', { name: 'See it in the app' }).click();
    await expect(page).toHaveURL(/\/app\/login\?returnUrl=%2Fapp%2Fopen%2Fmodule%2FRATECALC$/);
    await page.getByLabel('Username').fill(username('viewer'));
    await page.getByLabel('Password').fill(password());
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page).toHaveURL(/\/app\/projects\/[^/]+\/modules\/[^/]+$/);
    await expect(page.getByRole('heading', { name: 'RATECALC', level: 1 })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Verification report' })).toBeVisible();
  });

  test('the old addresses still work', async ({ page }) => {
    await page.goto('/login');
    await expect(page).toHaveURL(/\/app\/login$/);
    await page.goto('/projects/anything/rules');
    await expect(page).toHaveURL(/\/app\/login\?returnUrl=%2Fapp%2Fprojects%2Fanything%2Frules$/);
  });

  test('with reduced motion, the hero is a still picture of the same facts', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    const visual = page.locator('app-hero-visual');
    await expect(visual).toContainText(
      `first translation ${snapshot.api.rounding.passed} / ${snapshot.api.rounding.cases}, blocked`,
    );
    await expect(visual.getByRole('button', { name: 'Pause animation' })).toHaveCount(0);
  });

  test('the animation can be paused', async ({ page }) => {
    await page.goto('/');
    const pause = page.getByRole('button', { name: 'Pause animation' });
    await pause.click();
    await expect(page.getByRole('button', { name: 'Play animation' })).toHaveAttribute('aria-pressed', 'true');
  });

  for (const theme of ['dark', 'light'] as Theme[]) {
    test(`is accessible and fits at every width: ${theme}`, async ({ page }) => {
      await useTheme(page, theme);
      for (const width of [375, 768, 1280, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto('/');
        await expect(page.locator('app-hero-visual')).toBeVisible();
        // Scroll through, so every section has been revealed before axe reads colours.
        await page.evaluate(async () => {
          for (let y = 0; y < document.body.scrollHeight; y += 500) {
            window.scrollTo(0, y);
            await new Promise((resolve) => setTimeout(resolve, 40));
          }
          window.scrollTo(0, 0);
        });
        await page.waitForTimeout(800);
        await expectAccessible(page, `landing, ${theme}, ${width}px`);
        await expectNoSidewaysScroll(page, `landing, ${theme}, ${width}px`);
        if (width === 375 || width === 1440) {
          await page.screenshot({ path: `${SCREENSHOTS}/landing-${theme}-${width}.png`, fullPage: true });
        }
      }
    });
  }
});

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import snapshotJson from '../../../../public/data/landing-snapshot.json';
import { HeroVisual } from './hero-visual';
import { Landing } from './landing';
import { SNAPSHOT_URL, Snapshot } from './landing-data';
import { marksFor, pivotOf, splitArrow, windowYear } from './sections/demos';

const snapshot = snapshotJson as unknown as Snapshot;

function reducedMotion(on: boolean): void {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: on && query.includes('reduce'),
    media: query,
    addEventListener: () => undefined,
  }));
}

describe('Landing page', () => {
  let fixture: ComponentFixture<Landing>;
  let http: HttpTestingController;
  let page: HTMLElement;

  async function render(): Promise<void> {
    fixture = TestBed.createComponent(Landing);
    page = fixture.nativeElement;
    fixture.detectChanges();
    http.expectOne(SNAPSHOT_URL).flush(snapshot);
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(() => {
    reducedMotion(true);
    TestBed.configureTestingModule({
      imports: [Landing],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    fixture?.destroy();
    http.verify();
    vi.unstubAllGlobals();
  });

  it('pitches the product and reads only the static snapshot, never the API', async () => {
    await render();
    expect(page.querySelector('h1')?.textContent).toContain('Prove every module.');
    expect(page.textContent).toContain('AI-assisted COBOL → C# modernization, with proof.');
    http.expectNone((request) => request.url.startsWith('/api/'));
    const cta = Array.from(page.querySelectorAll('a')).find((a) => a.textContent?.includes('Try the live demo'));
    expect(cta?.getAttribute('href')).toBe('/app');
    expect(page.querySelector('.hero__ctas a[href="#how-it-works"]')?.textContent).toContain('See how it works');
  });

  it('shows the stored numbers, each with its source', async () => {
    await render();
    const stats = Array.from(page.querySelectorAll('.stat')).map((stat) => stat.textContent ?? '');
    expect(stats[0]).toContain(String(snapshot.api.rounding.cases));
    expect(stats[0]).toContain(`seed ${snapshot.api.rounding.seed}`);
    expect(stats[1]).toContain(String(snapshot.api.rounding.failed));
    expect(stats[2]).toContain('docs/EVALUATION.md');
  });

  it('has a navigation bar with the sections, the docs and the demo', async () => {
    await render();
    const links = Array.from(page.querySelectorAll('.nav__links a')).map((a) => a.textContent?.trim());
    expect(links).toEqual(['Product', 'Demo', 'How it works', 'Security', 'Docs', 'GitHub']);
    for (const id of ['product', 'demo', 'how-it-works', 'security']) {
      expect(page.querySelector(`#${id}`), id).not.toBeNull();
    }
    const menu = page.querySelector<HTMLButtonElement>('.nav__menu')!;
    expect(menu.getAttribute('aria-expanded')).toBe('false');
    menu.click();
    fixture.detectChanges();
    expect(menu.getAttribute('aria-expanded')).toBe('true');
  });

  it('switches demo tabs by click and by arrow keys, with deep links into the app', async () => {
    await render();
    const tabs = () => Array.from(page.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    expect(tabs().map((tab) => tab.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false', 'false']);
    const panel = () => page.querySelector('[role="tabpanel"]')!;
    expect(panel().textContent).toContain(snapshot.repo.rounding_math.legacy);
    expect(panel().textContent).toContain(snapshot.repo.rounding_math.modern);
    expect(panel().querySelector('a.button')?.getAttribute('href')).toBe('/app/open/module/RATECALC');

    tabs()[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    fixture.detectChanges();
    expect(tabs()[1].getAttribute('aria-selected')).toBe('true');
    expect(panel().textContent).toContain('2049');
    expect(panel().textContent).toContain('1951');
    expect(panel().querySelector('a.button')?.getAttribute('href')).toBe('/app/open/module/LATEFEE');

    tabs()[2].click();
    fixture.detectChanges();
    expect(panel().textContent).toContain('150');
    expect(panel().textContent).toContain('-99850');

    tabs()[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    fixture.detectChanges();
    expect(tabs()[3].getAttribute('aria-selected')).toBe('true');
    expect(panel().textContent).toContain('AI ASSISTANT');
    expect(panel().textContent).toContain('SPAN_INVALID');
    expect(panel().querySelector('a.button')?.getAttribute('href')).toBe(
      '/app/open/rules?program=RATECALC&flag=SPAN_INVALID',
    );
  });

  it('labels the deployment diagram as a model, and says what v1 builds', async () => {
    await render();
    const text = page.textContent ?? '';
    expect(text).toContain('reference deployment model');
    expect(text).toContain('not a description of any customer');
    expect(text).toContain('not yet opened as a pull request');
  });

  it('makes no claims it cannot back: no testimonials, customers, users or prices', async () => {
    await render();
    const text = (page.textContent ?? '').toLowerCase();
    for (const word of ['testimonial', 'trusted by', 'customers use', '$/', 'per month', 'award']) {
      expect(text).not.toContain(word);
    }
  });
});

describe('Hero visual', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('shows the still picture of the same facts when motion is reduced', async () => {
    reducedMotion(true);
    const fixture = TestBed.createComponent(HeroVisual);
    fixture.componentRef.setInput('data', snapshot);
    fixture.detectChanges();
    await fixture.whenStable();
    const host: HTMLElement = fixture.nativeElement;
    expect(host.querySelector('.count')?.textContent).toContain(`${snapshot.api.rounding.cases} / ${snapshot.api.rounding.cases}`);
    expect(host.textContent).toContain(`first translation ${snapshot.api.rounding.passed} / ${snapshot.api.rounding.cases}, blocked`);
    expect(host.querySelectorAll('.cell')).toHaveLength(snapshot.api.rounding.cases);
    expect(host.querySelector('.controls')).toBeNull();
    expect(host.querySelector('figcaption')?.textContent).toContain(`${snapshot.api.rounding.failed} differ by one cent`);
    fixture.destroy();
  });

  it('plays the story, can pause, and reaches the blocked state with 16 red cases', () => {
    vi.useFakeTimers();
    reducedMotion(false);
    const fixture = TestBed.createComponent(HeroVisual);
    fixture.componentRef.setInput('data', snapshot);
    fixture.detectChanges();
    const host: HTMLElement = fixture.nativeElement;
    vi.advanceTimersByTime(6000);
    fixture.detectChanges();
    expect(host.querySelector('.pill')?.textContent).toContain('Blocked');
    expect(host.querySelectorAll('.cell--bad')).toHaveLength(snapshot.api.rounding.failed);
    expect(host.querySelector('.count strong')?.textContent).toBe(String(snapshot.api.rounding.passed));

    const pause = host.querySelector<HTMLButtonElement>('.control')!;
    pause.click();
    fixture.detectChanges();
    expect(pause.getAttribute('aria-pressed')).toBe('true');
    vi.advanceTimersByTime(5000);
    fixture.detectChanges();
    expect(host.querySelector('.pill')?.textContent).toContain('Blocked');
    fixture.destroy();
    vi.useRealTimers();
  });
});

describe('demo helpers', () => {
  it('reads the pivot and expands two-digit years as LATEFEE does', () => {
    expect(pivotOf({ file: 'copy/RATES.cpy', start: 43, lines: ['05  RT-CENTURY-PIVOT  PIC 9(2) VALUE 50.'] })).toBe(50);
    expect(windowYear(49, 50)).toBe(2049);
    expect(windowYear(50, 50)).toBe(1950);
    expect(windowYear(51, 50)).toBe(1951);
  });

  it('marks lines by content and splits expression bodies at the arrow', () => {
    expect(marksFor({ file: 'x', start: 10, lines: ['a', 'COMPUTE X', 'b'] }, ['COMPUTE'], 'focus')).toEqual({ 11: 'focus' });
    expect(splitArrow('  public static decimal F(decimal a) => Math.Round(a, 2);')).toEqual([
      'public static decimal F(decimal a)',
      '    => Math.Round(a, 2);',
    ]);
  });
});

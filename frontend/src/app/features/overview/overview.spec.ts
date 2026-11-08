import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { Dashboard } from '../modernization/modernization.service';
import { Overview } from './overview';

const URL = '/api/v1/projects/p1/dashboard';

export function makeDashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    project: { id: 'p1', name: 'BillRite', source_kind: 'BUNDLED' },
    modules: [
      {
        id: 'm1',
        program: 'MTRVAL',
        service: 'meter-service',
        state: 'APPROVED',
        facade_mode: 'MODERN',
        cases: 500,
        passed: 500,
        failed: 0,
        coverage_pct: 100,
        mutation_score: 78.75,
        run_id: 'r1',
        shadow_compared: 20,
        shadow_mismatches: 0,
      },
      {
        id: 'm2',
        program: 'BILLRUN',
        service: 'billing-service',
        state: 'PENDING',
        facade_mode: 'LEGACY',
        cases: null,
        passed: null,
        failed: null,
        coverage_pct: null,
        mutation_score: null,
        run_id: null,
        shadow_compared: 0,
        shadow_mismatches: 0,
      },
    ],
    modules_by_state: { APPROVED: 1, PENDING: 1 },
    facade_modes: { MODERN: 1, LEGACY: 1 },
    rules: {
      total: 46,
      by_state: { VERIFIED: 43 },
      verified: 43,
      verified_pct: 93.48,
      decisions: 44,
      seeded_decisions: 44,
      human_decisions: 0,
    },
    equivalence: { modules_verified: 1, cases: 500, identical: 500 },
    ai: {
      calls: 11,
      failed: 0,
      by_mode: { mock: 11 },
      input_tokens: 74639,
      output_tokens: 0,
      estimated_cost_usd: 0,
      note: 'Mock calls cost nothing.',
    },
    activity: [
      {
        kind: 'decision',
        what: 'module MTRVAL',
        outcome: 'APPROVED',
        by: 'Ari Architect',
        seeded: true,
        at: '2026-11-08T07:00:00Z',
      },
      {
        kind: 'job',
        what: 'verify MTRVAL',
        outcome: 'SUCCEEDED',
        by: 'Ada Admin',
        at: '2026-11-08T06:59:00Z',
      },
    ],
    ...overrides,
  };
}

describe('Overview', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  async function open(): Promise<void> {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'projects/:id/overview', component: Overview }]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create('/projects/p1/overview');
    page = harness.routeNativeElement!;
  }

  async function settle(): Promise<void> {
    await harness.fixture.whenStable();
    harness.detectChanges();
  }

  afterEach(() => http.verify());

  it('shows the tiles, the module table and the activity in words', async () => {
    await open();
    http.expectOne(URL).flush(makeDashboard());
    await settle();
    const tiles = [...page.querySelectorAll('.tile')].map((tile) => tile.textContent ?? '');
    expect(tiles[0]).toContain('Approved: 1');
    expect(tiles[0]).toContain('Not migrated yet: 1');
    expect(tiles[1]).toContain('93.5%');
    expect(tiles[1]).toContain('0 decisions by people; 44 labelled demo seed decisions');
    expect(tiles[2]).toContain('500 of 500');
    expect(tiles[3]).toContain('11 calls');
    const row = page.querySelector('tbody tr')!.textContent!;
    expect(row).toContain('MTRVAL');
    expect(row).toContain('Modern');
    expect(row).toContain('78.75%');
    expect(row).toContain('20, 0 mismatched');
    expect(page.querySelector('.activity')?.textContent).toContain('(demo seed)');
  });

  it('shows empty states for a new project', async () => {
    await open();
    http.expectOne(URL).flush(
      makeDashboard({
        modules: [],
        modules_by_state: {},
        rules: { ...makeDashboard().rules, total: 0, verified: 0, verified_pct: null },
        equivalence: { modules_verified: 0, cases: 0, identical: 0 },
        activity: [],
      }),
    );
    await settle();
    expect(page.textContent).toContain('No modules yet.');
    expect(page.textContent).toContain('No rules extracted yet.');
    expect(page.textContent).toContain('No verification has run yet.');
    expect(page.textContent).toContain('No activity yet.');
  });

  it('shows an error with a retry', async () => {
    await open();
    http.expectOne(URL).flush({}, { status: 500, statusText: 'Error' });
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('could not be loaded');
    [...page.querySelectorAll('button')].find((b) => b.textContent?.includes('Try again'))!.click();
    http.expectOne(URL).flush(makeDashboard());
    await settle();
    expect(page.querySelector('h1')?.textContent).toBe('BillRite');
  });
});

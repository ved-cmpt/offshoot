import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { AuthService, Role } from '../../core/auth/auth.service';
import { ModuleDetail, RunDetail } from '../modernization/modernization.service';
import { makeArtifact, makeModule, makeRunDetail, makeRunSummary } from '../modernization/testing';
import { PARAGRAPH_GRAPH, authAs, makeJob, makeRule, makeSource } from '../workbench/testing';
import { JOB_POLL_INTERVAL_MS } from '../workbench/workbench.service';
import { ModuleWorkspace, coverageLines } from './module-workspace';

const MODULE_URL = '/api/v1/modules/m1';
const SOURCES = {
  items: [
    {
      id: 'f1',
      path: 'src/RATECALC.cbl',
      name: 'RATECALC.cbl',
      kind: 'PROGRAM',
      line_count: 3,
      sha256: 'x',
    },
  ],
  total: 1,
};

describe('coverageLines', () => {
  it('marks each line by the paragraph it belongs to', () => {
    const source = makeSource({
      id: 'f1',
      lines: Array.from({ length: 70 }, (_, index) => `line ${index + 1}`),
    });
    const lines = coverageLines(source, PARAGRAPH_GRAPH, ['0000-MAIN-CONTROL'], []);
    expect(lines[55].coverage).toBe('hit');
    expect(lines[55].paragraph).toBe('0000-MAIN-CONTROL');
    expect(lines[10].coverage).toBeNull();
    const missed = coverageLines(source, PARAGRAPH_GRAPH, [], ['0000-MAIN-CONTROL']);
    expect(missed[60].coverage).toBe('missed');
  });
});

describe('ModuleWorkspace', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  async function open(
    role: Role,
    module: ModuleDetail = makeModule(),
    run: RunDetail = makeRunDetail(),
  ): Promise<void> {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'projects/:id/modules/:mid', component: ModuleWorkspace }]),
        { provide: AuthService, useValue: authAs(role) },
        { provide: JOB_POLL_INTERVAL_MS, useValue: 100000 },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create('/projects/p1/modules/m1');
    page = harness.routeNativeElement!;
    await flushLoad(module, run);
  }

  async function flushLoad(module: ModuleDetail, run: RunDetail = makeRunDetail()): Promise<void> {
    http.expectOne(MODULE_URL).flush(module);
    await settle();
    http.expectOne(`${MODULE_URL}/runs`).flush(module.latest_run ? [makeRunSummary()] : []);
    http
      .expectOne(`${MODULE_URL}/artifacts`)
      .flush(module.current_artifact ? [module.current_artifact] : []);
    http.expectOne('/api/v1/projects/p1/sources').flush(SOURCES);
    http.expectOne(`/api/v1/projects/p1/graph?program=${module.program}`).flush(PARAGRAPH_GRAPH);
    http.expectOne(`/api/v1/projects/p1/rules?limit=50&program=${module.program}`).flush({
      items: [makeRule({ state: 'VERIFIED' })],
      total: 1,
      limit: 50,
      offset: 0,
      counts: {},
      programs: [],
    });
    await settle();
    // Only RATECALC.cbl is in the source list, so another program has no source to fetch.
    for (const request of http.match('/api/v1/projects/p1/sources/f1')) {
      request.flush(
        makeSource({
          id: 'f1',
          name: 'RATECALC.cbl',
          lines: Array.from({ length: 70 }, (_, i) => `       LINE ${i + 1}.`),
        }),
      );
    }
    await settle();
    if (module.latest_run) {
      http.expectOne(`${MODULE_URL}/runs/run1`).flush(run);
    }
    if (module.current_artifact) {
      http
        .expectOne(`${MODULE_URL}/artifacts/${module.current_artifact.version}`)
        .flush(makeArtifact());
    }
    await settle();
  }

  async function settle(): Promise<void> {
    await harness.fixture.whenStable();
    harness.detectChanges();
  }

  function button(label: string): HTMLButtonElement | undefined {
    return [...page.querySelectorAll('button')].find((item) => item.textContent?.trim() === label);
  }

  afterEach(() => http.verify());

  it('shows the blocked state, the failing gates and the field-level diffs in words', async () => {
    await open('VIEWER');
    expect(page.querySelector('h1')?.textContent).toContain('RATECALC');
    expect(page.textContent).toContain('Blocked by verification');
    expect(page.textContent).toContain(
      'Some cases gave a different result from the legacy program.',
    );
    const gates = [...page.querySelectorAll('.gates li')].map((item) => item.textContent ?? '');
    expect(gates.find((text) => text.includes('Equivalence'))).toContain('Fail');
    expect(gates.find((text) => text.includes('Build and analyzers'))).toContain('Pass');
    expect(page.textContent).toContain('484 of 500 cases identical');
    const rows = [...page.querySelectorAll('[aria-label="Field-level differences"] tbody tr')];
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('RC-OUT-ENERGY');
    expect(rows[0].textContent).toContain('55.91');
    expect(rows[0].textContent).toContain('55.90');
    expect(page.textContent).toContain('Paragraphs no case reached: 8500-APPLY-WINTER-DISCOUNT.');
    expect(page.textContent).toContain('Mutation testing runs only when every case matches');
  });

  it('shows COBOL beside the C# files and escapes their content', async () => {
    await open('VIEWER');
    expect(page.querySelector('[aria-label="COBOL source with coverage"]')?.textContent).toContain(
      'LINE 56',
    );
    expect(page.querySelector('.line--hit')).not.toBeNull();
    const tabs = [...page.querySelectorAll('[role="tab"]')];
    expect(tabs.map((tab) => tab.textContent?.trim())).toEqual([
      'src/ModuleEntry.cs',
      'tests/Tests.cs',
    ]);
    (tabs[1] as HTMLButtonElement).click();
    await settle();
    expect(page.querySelector('.csharp')?.textContent).toContain('<script>alert(1)</script>');
    expect(page.querySelector('.csharp script')).toBeNull();
  });

  it('links the rules and says which ones the run exercised', async () => {
    await open('VIEWER');
    const rule = page.querySelector('.rules li')!.textContent!;
    expect(rule).toContain('Minimum charge');
    expect(rule).toContain('implemented, per the agent');
    expect(rule).toContain('exercised by 4 cases');
  });

  it('gives a viewer no actions', async () => {
    await open('VIEWER');
    expect(button('Repair')).toBeUndefined();
    expect(button('Migrate')).toBeUndefined();
  });

  it('lets an engineer repair a blocked module and follows the verification it queues', async () => {
    await open('ENGINEER');
    expect(button('Repair')).toBeDefined();
    expect(button('Record exception')).toBeUndefined();
    button('Repair')!.click();
    http.expectOne({ method: 'POST', url: `${MODULE_URL}/repair` }).flush(
      makeJob({
        id: 'j2',
        kind: 'REPAIR',
        status: 'SUCCEEDED',
        metrics: { verify_job_id: 'j3' },
      }),
    );
    await settle();
    http.expectOne('/api/v1/jobs/j3').flush(
      makeJob({
        id: 'j3',
        kind: 'VERIFY',
        status: 'RUNNING',
        metrics: { stage: 'mutation testing with Stryker.NET' },
      }),
    );
    await flushLoad(
      makeModule({
        state: 'VERIFYING',
        active_job: makeJob({ id: 'j3', kind: 'VERIFY', status: 'RUNNING' }),
      }),
    );
    expect(page.textContent).toContain('Verification');
    expect(page.textContent).toContain('mutation testing with Stryker.NET');
    // The progress panel keeps polling the running verification.
    http
      .expectOne('/api/v1/jobs/j3')
      .flush(makeJob({ id: 'j3', kind: 'VERIFY', status: 'RUNNING' }));
  });

  it('reloads once when a verification finishes, without a reload loop', async () => {
    const running = makeJob({ id: 'j3', kind: 'VERIFY', status: 'RUNNING' });
    await open('ENGINEER', makeModule({ state: 'VERIFYING', active_job: running }));
    // The panel follows the running job from the server.
    http
      .expectOne('/api/v1/jobs/j3')
      .flush(makeJob({ id: 'j3', kind: 'VERIFY', status: 'SUCCEEDED' }));
    await settle();
    await flushLoad(makeModule({ state: 'VERIFIED', state_reason: null }));
    expect(page.textContent).toContain('Verified, awaiting approval');
    // http.verify() in afterEach fails if the finished job triggered any further reload.
  });

  it('reloads when the server refuses a stale action', async () => {
    await open('ENGINEER');
    button('Repair')!.click();
    http.expectOne(`${MODULE_URL}/repair`).flush(
      {
        error: {
          code: 'REPAIR_LIMIT',
          message: 'The repair budget of 3 attempts is spent. Migrate again.',
          request_id: 'r',
        },
      },
      { status: 409, statusText: 'Conflict' },
    );
    await settle();
    // The refusal reloads the module; the message stays on screen after the reload.
    await flushLoad(makeModule({ repairs_used: 3, repairs_remaining: 0 }));
    expect(page.querySelector('[role="alert"]')?.textContent).toContain(
      'repair budget of 3 attempts',
    );
    expect(button('Repair')).toBeUndefined();
  });

  it('lets only an architect record a gate exception, with a reason', async () => {
    await open('ARCHITECT');
    button('Record exception')!.click();
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('a reason');
    const threshold = page.querySelector<HTMLInputElement>('input[type="number"]')!;
    threshold.value = '90';
    threshold.dispatchEvent(new Event('input'));
    const reason = page.querySelector<HTMLTextAreaElement>('.exception textarea')!;
    reason.value = 'Only the dead winter discount is missed.';
    reason.dispatchEvent(new Event('input'));
    button('Record exception')!.click();
    const request = http.expectOne(`${MODULE_URL}/gate-exceptions`);
    expect(request.request.body).toEqual({
      gate: 'COVERAGE',
      threshold: 90,
      reason: 'Only the dead winter discount is missed.',
      expected_version: 5,
    });
    request.flush(makeModule());
    await settle();
    await flushLoad(makeModule());
  });

  it('explains a module the harness cannot run', async () => {
    await open(
      'ENGINEER',
      makeModule({
        program: 'BILLRUN',
        migratable: false,
        state: 'PENDING',
        current_artifact: null,
        latest_run: null,
        gates: [],
      }),
    );
    expect(page.textContent).toContain('The per-record harness has no entry for BILLRUN');
    expect(button('Migrate')).toBeUndefined();
    expect(page.textContent).toContain('No verification has run yet.');
  });

  it('shows an error with a retry', async () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'projects/:id/modules/:mid', component: ModuleWorkspace }]),
        { provide: AuthService, useValue: authAs('VIEWER') },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create('/projects/p1/modules/m1');
    page = harness.routeNativeElement!;
    http
      .expectOne(MODULE_URL)
      .flush(
        { error: { code: 'NOT_FOUND', message: 'Module not found.', request_id: 'r' } },
        { status: 404, statusText: 'Not Found' },
      );
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('Module not found.');
    button('Try again')!.click();
    await flushLoad(makeModule());
    expect(page.textContent).toContain('Gates');
  });
});

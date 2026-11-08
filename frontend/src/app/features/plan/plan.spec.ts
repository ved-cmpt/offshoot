import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { AuthService, Role } from '../../core/auth/auth.service';
import { PlanView } from '../modernization/modernization.service';
import { makePlan, makeSummary } from '../modernization/testing';
import { authAs, makeJob } from '../workbench/testing';
import { JOB_POLL_INTERVAL_MS } from '../workbench/workbench.service';
import { PlanPage } from './plan';

const PLAN_URL = '/api/v1/projects/p1/plan';
const MODULES_URL = '/api/v1/projects/p1/modules';

describe('PlanPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  async function open(
    role: Role,
    view: PlanView | null = { plan: makePlan(), history: [] },
    modules = [makeSummary()],
  ): Promise<void> {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'projects/:id/plan', component: PlanPage }]),
        { provide: AuthService, useValue: authAs(role) },
        { provide: JOB_POLL_INTERVAL_MS, useValue: 100000 },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create('/projects/p1/plan');
    page = harness.routeNativeElement!;
    if (view) {
      http.expectOne(PLAN_URL).flush(view);
      http.expectOne(MODULES_URL).flush(modules);
      await settle();
    }
  }

  async function settle(): Promise<void> {
    await harness.fixture.whenStable();
    harness.detectChanges();
  }

  function button(label: string): HTMLButtonElement | undefined {
    return [...page.querySelectorAll('button')].find((item) =>
      item.textContent?.trim().startsWith(label),
    );
  }

  afterEach(() => http.verify());

  it('shows the service map, the order, the risks and the estimate', async () => {
    await open('VIEWER');
    expect(page.textContent).toContain('Version 1: Proposed, awaiting an architect');
    expect(page.querySelectorAll('.service').length).toBe(2);
    const steps = [...page.querySelectorAll('.timeline li')].map((item) => item.textContent);
    expect(steps[2]).toContain('BILLRUN');
    expect(steps[2]).toContain('Calls MTRVAL, RATECALC');
    expect(page.textContent).toContain('High risk');
    expect(page.textContent).toContain('Half-up rounding');
    expect(page.querySelector('tfoot')?.textContent).toContain('29');
    // The module link shows its state in words.
    expect(page.querySelector('.service a')?.textContent).toContain('Blocked by verification');
  });

  it('lets a viewer read but not propose or decide', async () => {
    await open('VIEWER');
    expect(button('Propose plan')).toBeUndefined();
    expect(button('Approve plan')).toBeUndefined();
    expect(page.textContent).toContain('An architect decides on this plan.');
  });

  it('lets an engineer propose and follows the job', async () => {
    await open('ENGINEER');
    expect(button('Approve plan')).toBeUndefined();
    button('Propose plan')!.click();
    http
      .expectOne({ method: 'POST', url: PLAN_URL })
      .flush(makeJob({ kind: 'PLAN', status: 'SUCCEEDED' }));
    await settle();
    // A finished job reloads the plan and the modules.
    http.expectOne(PLAN_URL).flush({ plan: makePlan({ version: 2 }), history: [] });
    http.expectOne(MODULES_URL).flush([]);
    await settle();
    expect(page.textContent).toContain('Version 2');
  });

  it('lets an architect approve with the expected version', async () => {
    await open('ARCHITECT');
    button('Approve plan')!.click();
    const request = http.expectOne({ method: 'POST', url: `${PLAN_URL}/decision` });
    expect(request.request.body).toEqual({
      decision: 'APPROVED',
      expected_version: 1,
      reason: null,
    });
    request.flush(makePlan({ state: 'APPROVED' }));
    await settle();
    http.expectOne(PLAN_URL).flush({
      plan: makePlan({
        state: 'APPROVED',
        decided_by_name: 'Avery',
        decided_at: '2026-11-08T03:00:00Z',
      }),
      history: [],
    });
    http.expectOne(MODULES_URL).flush([]);
    await settle();
    expect(page.textContent).toContain('Approved by Avery');
    expect(button('Approve plan')).toBeUndefined();
  });

  it('needs a reason to reject, then sends it', async () => {
    await open('ARCHITECT');
    button('Reject')!.click();
    await settle();
    button('Reject plan')!.click();
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain(
      'A rejection needs a reason.',
    );
    const field = page.querySelector('textarea')!;
    field.value = 'Split billing further.';
    field.dispatchEvent(new Event('input'));
    button('Reject plan')!.click();
    const request = http.expectOne(`${PLAN_URL}/decision`);
    expect(request.request.body.reason).toBe('Split billing further.');
    request.flush(makePlan({ state: 'REJECTED' }));
    await settle();
    http.expectOne(PLAN_URL).flush({ plan: makePlan({ state: 'REJECTED' }), history: [] });
    http.expectOne(MODULES_URL).flush([]);
    await settle();
  });

  it('reloads after a stale decision and says why', async () => {
    await open('ARCHITECT');
    button('Approve plan')!.click();
    http.expectOne(`${PLAN_URL}/decision`).flush(
      {
        error: {
          code: 'STALE_VERSION',
          message: 'The plan has changed. Reload it: the latest is version 2.',
          request_id: 'r',
        },
      },
      { status: 409, statusText: 'Conflict' },
    );
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('the latest is version 2');
    http.expectOne(PLAN_URL).flush({ plan: makePlan({ version: 2 }), history: [] });
    http.expectOne(MODULES_URL).flush([]);
    await settle();
    expect(page.textContent).toContain('Version 2');
  });

  it('shows an empty state before any plan', async () => {
    await open('ENGINEER', { plan: null, history: [] }, []);
    expect(page.textContent).toContain('There is no plan yet.');
  });

  it('shows an error with a retry', async () => {
    await open('VIEWER', null);
    http.expectOne(MODULES_URL).flush([]);
    http.expectOne(PLAN_URL).flush({}, { status: 500, statusText: 'Server Error' });
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain(
      'The plan could not be loaded.',
    );
    button('Try again')!.click();
    http.expectOne(PLAN_URL).flush({ plan: makePlan(), history: [] });
    http.expectOne(MODULES_URL).flush([]);
    await settle();
    expect(page.textContent).toContain('Service map');
  });
});

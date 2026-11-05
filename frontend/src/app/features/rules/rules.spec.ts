import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { AuthService, Role } from '../../core/auth/auth.service';
import { authAs, makeFlaggedRule, makeInventory, makeJob, makeRule } from '../workbench/testing';
import { JOB_POLL_INTERVAL_MS, Rule, RulePage } from '../workbench/workbench.service';
import { parseSpans } from './rule-card';
import { Rules } from './rules';

const RULES_URL = '/api/v1/projects/p1/rules?limit=50&offset=0';
const INVENTORY_URL = '/api/v1/projects/p1/inventory';

function rulesUrl(filters: string): string {
  return `/api/v1/projects/p1/rules?limit=50&${filters}&offset=0`;
}

function pageOf(items: Rule[], overrides: Partial<RulePage> = {}): RulePage {
  return {
    items,
    total: items.length,
    limit: 50,
    offset: 0,
    counts: { PROPOSED: items.length },
    programs: ['RATECALC'],
    ...overrides,
  };
}

function errorBody(code: string, message: string): object {
  return { error: { code, message, request_id: 'r' } };
}

describe('Rules', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  async function open(
    role: Role,
    rules: Rule[] = [makeRule()],
    overrides: Partial<RulePage> = {},
  ): Promise<void> {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'projects/:id/rules', component: Rules }]),
        { provide: AuthService, useValue: authAs(role) },
        { provide: JOB_POLL_INTERVAL_MS, useValue: 100000 },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create('/projects/p1/rules');
    page = harness.routeNativeElement!;
    http.expectOne(RULES_URL).flush(pageOf(rules, overrides));
    http.expectOne(INVENTORY_URL).flush(makeInventory());
    await settle();
  }

  async function settle(): Promise<void> {
    await harness.fixture.whenStable();
    harness.detectChanges();
  }

  function button(label: string, root: Element = page): HTMLButtonElement | undefined {
    return [...root.querySelectorAll('button')].find((item) => item.textContent?.trim() === label);
  }

  function type(selector: string, value: string): void {
    const field = page.querySelector<HTMLInputElement | HTMLTextAreaElement>(selector)!;
    field.value = value;
    field.dispatchEvent(new Event('input'));
  }

  function fieldByLabel(label: string): HTMLInputElement | HTMLTextAreaElement {
    const found = [...page.querySelectorAll('label')].find((item) =>
      item.textContent?.includes(label),
    )!;
    return found.querySelector('input, textarea')!;
  }

  afterEach(() => http.verify());

  // What each role sees.

  it('a viewer reads rules and gets no actions at all', async () => {
    await open('VIEWER');
    expect(page.textContent).toContain('Minimum charge');
    expect(page.querySelectorAll('.actions button')).toHaveLength(0);
    expect(button('Extract rules')).toBeUndefined();
  });

  it('an admin gets no actions either', async () => {
    await open('ADMIN');
    expect(page.querySelectorAll('.actions button')).toHaveLength(0);
    expect(button('Extract rules')).toBeUndefined();
  });

  it('an engineer can edit and extract, but not decide', async () => {
    await open('ENGINEER');
    expect(button('Edit')).toBeDefined();
    expect(button('Verify')).toBeUndefined();
    expect(button('Reject')).toBeUndefined();
    expect(button('Extract rules')).toBeDefined();
  });

  it('an architect can verify, reject, edit and extract', async () => {
    await open('ARCHITECT');
    for (const label of ['Verify', 'Reject', 'Edit', 'Extract rules']) {
      expect(button(label)).toBeDefined();
    }
  });

  it('a decided rule offers no decision, and a rejected one no edit', async () => {
    await open('ARCHITECT', [
      makeRule({
        state: 'VERIFIED',
        verifiable: false,
        decided_by_name: 'Ari',
        decision_reason: 'Looks right.',
      }),
      makeRule({ id: 'r3', state: 'REJECTED', verifiable: false, decided_by_name: 'Ari' }),
    ]);
    const cards = page.querySelectorAll('.card');
    expect(button('Verify', cards[0])).toBeUndefined();
    expect(button('Edit', cards[0])).toBeDefined();
    expect(cards[0].textContent).toContain('By Ari');
    expect(cards[0].textContent).toContain('Looks right.');
    expect(cards[1].querySelectorAll('.actions button')).toHaveLength(0);
  });

  // Rule content.

  it('shows spans as links, with inputs, outputs, conditions and examples', async () => {
    await open('VIEWER');
    const card = page.querySelector('.card')!;
    const link = card.querySelector('a.span')!;
    expect(link.textContent).toBe('RATECALC.cbl:196-203');
    expect(link.getAttribute('href')).toBe('/projects/p1/sources/f1?line=196&end=203');
    expect(card.textContent).toContain('RC-OUT-ENERGY');
    expect(card.textContent).toContain('RC-OUT-SUBTOTAL < WS-MINIMUM');
    expect(card.textContent).toContain('{"RC-OUT-ENERGY":1} gives {"RC-OUT-SUBTOTAL":8.5}');
    expect(card.textContent).toContain('Confidence 95%');
    expect(card.textContent).toContain('Proposed by the agent');
  });

  it('a flagged rule explains itself, gives no link to its bad span, and cannot be verified', async () => {
    await open('ARCHITECT', [makeFlaggedRule()]);
    const card = page.querySelector('.card')!;
    expect(card.textContent).toContain('cannot be verified until an edit fixes this');
    expect(card.textContent).toContain('Source lines invalid:');
    expect(card.textContent).toContain('is outside the file');
    expect(card.textContent).toContain('Data names not found:');
    expect(card.querySelector('a.span')).toBeNull();
    expect(card.querySelector('.span--invalid')?.textContent).toContain('(invalid)');
    expect(button('Verify', card)?.disabled).toBe(true);
    expect(button('Reject', card)?.disabled).toBe(false);
  });

  // Decisions.

  it('verify sends the version the architect saw and shows the result', async () => {
    await open('ARCHITECT', [makeRule({ version: 3 })]);
    button('Verify')!.click();
    const request = http.expectOne('/api/v1/rules/r1/decision');
    expect(request.request.body).toEqual({
      decision: 'VERIFIED',
      expected_version: 3,
      reason: null,
    });
    request.flush(
      makeRule({ state: 'VERIFIED', version: 4, verifiable: false, decided_by_name: 'Ari' }),
    );
    await settle();
    expect(page.textContent).toContain('Verified.');
    expect(page.querySelector('.badge--ok')?.textContent).toContain('Verified');
    expect(button('Verify')).toBeUndefined();
    expect(page.querySelector('.counts')?.textContent).toContain('1 verified, 0 proposed');
  });

  it('reject needs a reason, and sends it', async () => {
    await open('ARCHITECT');
    button('Reject')!.click();
    await settle();
    button('Reject rule')!.click();
    await settle();
    http.expectNone('/api/v1/rules/r1/decision');
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('needs a reason');

    type('textarea', 'The cited lines do not say this.');
    await settle();
    button('Reject rule')!.click();
    const request = http.expectOne('/api/v1/rules/r1/decision');
    expect(request.request.body).toEqual({
      decision: 'REJECTED',
      expected_version: 1,
      reason: 'The cited lines do not say this.',
    });
    request.flush(makeRule({ state: 'REJECTED', version: 2, verifiable: false }));
    await settle();
    expect(page.querySelector('.badge--danger')?.textContent).toContain('Rejected');
    expect(page.querySelector('form')).toBeNull();
  });

  it('cancelling a rejection leaves the rule alone', async () => {
    await open('ARCHITECT');
    button('Reject')!.click();
    await settle();
    button('Cancel')!.click();
    await settle();
    expect(page.querySelector('form')).toBeNull();
    http.expectNone('/api/v1/rules/r1/decision');
  });

  it('a stale decision shows the server message and brings in the latest version', async () => {
    await open('ARCHITECT');
    button('Verify')!.click();
    http
      .expectOne('/api/v1/rules/r1/decision')
      .flush(errorBody('STALE_VERSION', 'This rule has changed. Reload it: it is now version 2.'), {
        status: 409,
        statusText: 'Conflict',
      });
    http
      .expectOne('/api/v1/rules/r1')
      .flush(makeRule({ version: 2, statement: 'Someone else reworded this rule.' }));
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('This rule has changed');
    expect(page.textContent).toContain('Someone else reworded this rule.');
    expect(page.textContent).toContain('Review it before deciding');
    expect(button('Verify')?.disabled).toBe(false);

    // The next try uses the new version.
    button('Verify')!.click();
    const retry = http.expectOne('/api/v1/rules/r1/decision');
    expect(retry.request.body.expected_version).toBe(2);
    retry.flush(makeRule({ state: 'VERIFIED', version: 3, verifiable: false }));
    await settle();
  });

  it('shows the server refusal for a flagged rule, should the screen be out of date', async () => {
    await open('ARCHITECT');
    button('Verify')!.click();
    http
      .expectOne('/api/v1/rules/r1/decision')
      .flush(errorBody('RULE_FLAGGED', 'This rule cannot be verified until it is fixed.'), {
        status: 409,
        statusText: 'Conflict',
      });
    http.expectOne('/api/v1/rules/r1').flush(makeFlaggedRule({ id: 'r1', version: 2 }));
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain(
      'cannot be verified until it is fixed',
    );
    expect(button('Verify')?.disabled).toBe(true);
  });

  it('the server is still the one enforcing roles: a 403 is shown as it comes', async () => {
    await open('ARCHITECT');
    button('Verify')!.click();
    http
      .expectOne('/api/v1/rules/r1/decision')
      .flush(errorBody('FORBIDDEN', 'You do not have permission to do this.'), {
        status: 403,
        statusText: 'Forbidden',
      });
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain(
      'You do not have permission',
    );
    expect(page.querySelector('.badge--ok')).toBeNull();
  });

  // Edits.

  it('an edit sends every field with the version, and the checks result comes back', async () => {
    await open('ENGINEER', [makeFlaggedRule()]);
    button('Edit')!.click();
    await settle();
    expect(document.activeElement).toBe(fieldByLabel('Title'));
    fieldByLabel('Statement').value = 'A corrected statement of the rule.';
    fieldByLabel('Statement').dispatchEvent(new Event('input'));
    fieldByLabel('Source spans').value = 'RATECALC.cbl:183-189\nRATES.cpy:16';
    fieldByLabel('Source spans').dispatchEvent(new Event('input'));
    await settle();
    button('Save edit')!.click();
    const request = http.expectOne('/api/v1/rules/r2');
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body.expected_version).toBe(1);
    expect(request.request.body.statement).toBe('A corrected statement of the rule.');
    expect(request.request.body.source_spans).toEqual([
      { file: 'RATECALC.cbl', start_line: 183, end_line: 189 },
      { file: 'RATES.cpy', start_line: 16, end_line: 16 },
    ]);
    expect(request.request.body.state).toBeUndefined();
    request.flush(
      makeRule({
        id: 'r2',
        state: 'EDITED',
        version: 2,
        flags: [],
        statement: 'A corrected statement of the rule.',
      }),
    );
    await settle();
    expect(page.textContent).toContain('The checks ran again');
    expect(page.textContent).toContain('Edited, awaiting a decision');
    expect(page.querySelector('.flags')).toBeNull();
  });

  it('an edit that leaves a problem keeps the rule flagged', async () => {
    await open('ENGINEER', [makeFlaggedRule()]);
    button('Edit')!.click();
    await settle();
    button('Save edit')!.click();
    http.expectOne('/api/v1/rules/r2').flush(makeFlaggedRule({ state: 'EDITED', version: 2 }));
    await settle();
    expect(page.querySelector('.flags')).not.toBeNull();
  });

  it('refuses malformed spans and examples before sending anything', async () => {
    await open('ENGINEER');
    button('Edit')!.click();
    await settle();
    fieldByLabel('Source spans').value = 'not a span';
    fieldByLabel('Source spans').dispatchEvent(new Event('input'));
    button('Save edit')!.click();
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('at least one source span');

    fieldByLabel('Source spans').value = 'RATECALC.cbl:1';
    fieldByLabel('Source spans').dispatchEvent(new Event('input'));
    fieldByLabel('Examples').value = '{nope';
    fieldByLabel('Examples').dispatchEvent(new Event('input'));
    button('Save edit')!.click();
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('not valid JSON');
    http.expectNone('/api/v1/rules/r1');
  });

  it('parses span text', () => {
    expect(parseSpans(' A.cbl:1-2 \n\nB.cpy:7')).toEqual([
      { file: 'A.cbl', start_line: 1, end_line: 2 },
      { file: 'B.cpy', start_line: 7, end_line: 7 },
    ]);
    expect(parseSpans('A.cbl')).toBeNull();
    expect(parseSpans('A.cbl:x')).toBeNull();
    expect(parseSpans('')).toEqual([]);
  });

  // Filters, states and jobs.

  it('filters ask the server, and go back to the first page', async () => {
    await open('VIEWER');
    const [program, state, flag] = page.querySelectorAll<HTMLSelectElement>('.filters select');

    program.value = 'BILLRUN';
    program.dispatchEvent(new Event('change'));
    http.expectOne(rulesUrl('program=BILLRUN')).flush(pageOf([makeRule()]));
    await settle();

    state.value = 'VERIFIED';
    state.dispatchEvent(new Event('change'));
    http.expectOne(rulesUrl('program=BILLRUN&state=VERIFIED')).flush(pageOf([]));
    await settle();
    expect(page.textContent).toContain('No rules match these filters');

    button('Clear filters')!.click();
    http.expectOne(RULES_URL).flush(pageOf([makeRule()]));
    await settle();

    flag.value = 'SPAN_INVALID';
    flag.dispatchEvent(new Event('change'));
    http.expectOne(rulesUrl('flag=SPAN_INVALID')).flush(pageOf([makeFlaggedRule()]));
    await settle();
    expect(page.querySelector('h3')?.textContent).toContain('Senior discount');
  });

  it('a slow reply cannot replace newer filters', async () => {
    await open('VIEWER');
    const [program] = page.querySelectorAll<HTMLSelectElement>('.filters select');
    program.value = 'BILLRUN';
    program.dispatchEvent(new Event('change'));
    const slow = http.expectOne(rulesUrl('program=BILLRUN'));
    program.value = 'RATECALC';
    program.dispatchEvent(new Event('change'));
    expect(slow.cancelled).toBe(true);
    http.expectOne(rulesUrl('program=RATECALC')).flush(pageOf([makeFlaggedRule()]));
    await settle();
    expect(page.querySelector('h3')?.textContent).toContain('Senior discount');
  });

  it('with no rules and no filters, it says so', async () => {
    await open('VIEWER', []);
    expect(page.textContent).toContain('No rules have been extracted yet');
  });

  it('pages through long lists', async () => {
    await open('VIEWER', [makeRule()], { total: 60 });
    expect(page.textContent).toContain('1 to 1 of 60');
    expect(button('Previous')?.disabled).toBe(true);
    button('Next')!.click();
    http
      .expectOne('/api/v1/projects/p1/rules?limit=50&offset=50')
      .flush(pageOf([makeRule()], { total: 60, offset: 50 }));
    await settle();
    expect(page.textContent).toContain('51 to 51 of 60');
    expect(button('Next')?.disabled).toBe(true);
  });

  it('shows a load failure with a working retry', async () => {
    await open('VIEWER');
    const select = page.querySelector<HTMLSelectElement>('.filters select')!;
    select.value = 'RATECALC';
    select.dispatchEvent(new Event('change'));
    http.expectOne(rulesUrl('program=RATECALC')).flush({}, { status: 500, statusText: 'Error' });
    await settle();
    const alert = page.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('could not be loaded');
    alert.querySelector('button')!.click();
    http.expectOne(rulesUrl('program=RATECALC')).flush(pageOf([makeRule()]));
    await settle();
    expect(page.querySelector('[role="alert"]')).toBeNull();
  });

  it('extraction runs as a job, and the list reloads when it finishes', async () => {
    await open('ENGINEER', []);
    const select = page.querySelector<HTMLSelectElement>('.extract select')!;
    select.value = 'RATECALC';
    select.dispatchEvent(new Event('change'));
    await settle();
    button('Extract rules')!.click();
    http
      .expectOne('/api/v1/projects/p1/programs/RATECALC/extract-rules')
      .flush(makeJob({ kind: 'EXTRACT' }));
    await settle();
    expect(page.textContent).toContain('Extraction:');

    await new Promise((resolve) => setTimeout(resolve, 5));
    http.expectOne('/api/v1/jobs/j1').flush(makeJob({ status: 'SUCCEEDED' }));
    await settle();
    http.expectOne(RULES_URL).flush(pageOf([makeFlaggedRule()]));
    await settle();
    expect(page.querySelector('h3')?.textContent).toContain('Senior discount');
  });

  it('a failed extraction explains itself and keeps the list', async () => {
    await open('ENGINEER');
    button('Extract rules')!.click();
    http
      .expectOne('/api/v1/projects/p1/programs/BILLRUN/extract-rules')
      .flush(makeJob({ kind: 'EXTRACT' }));
    await settle();
    await new Promise((resolve) => setTimeout(resolve, 5));
    http
      .expectOne('/api/v1/jobs/j1')
      .flush(makeJob({ status: 'FAILED', error_code: 'AI_INVALID_OUTPUT' }));
    await settle();
    expect(page.textContent).toContain('failed validation, so nothing was stored');
    expect(page.textContent).toContain('Minimum charge');
    http.expectNone(RULES_URL);
  });

  it('an unanalyzed project points to the inventory instead of offering extraction', async () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'projects/:id/rules', component: Rules }]),
        { provide: AuthService, useValue: authAs('ENGINEER') },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create('/projects/p1/rules');
    page = harness.routeNativeElement!;
    http.expectOne(RULES_URL).flush(pageOf([]));
    http.expectOne(INVENTORY_URL).flush(makeInventory({ analyzed: false, programs: [] }));
    await settle();
    expect(page.textContent).toContain('Analyze the project first');
    expect(button('Extract rules')).toBeUndefined();
  });
});

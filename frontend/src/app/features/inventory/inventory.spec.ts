import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { AuthService, Role } from '../../core/auth/auth.service';
import { OVERVIEW_GRAPH, authAs, makeInventory, makeJob } from '../workbench/testing';
import { JOB_POLL_INTERVAL_MS, LayoutPage } from '../workbench/workbench.service';
import { Inventory } from './inventory';

const INVENTORY_URL = '/api/v1/projects/p1/inventory';
const GRAPH_URL = '/api/v1/projects/p1/graph';
const LAYOUTS_URL = '/api/v1/projects/p1/inventory/layouts?limit=50&offset=0';

const LAYOUTS: LayoutPage = {
  items: [
    {
      id: 'l1',
      name: 'CUSTOMER-RECORD',
      file: 'CUSTREC.cpy',
      file_id: 'f3',
      start_line: 11,
      section: 'FILE',
      length: 100,
      redefines: null,
      used_by: ['BILLRUN'],
      obsolete: false,
      fields: [
        {
          name: 'CUST-OVERDUE-BAL',
          line: 21,
          order: 0,
          level: 5,
          picture: '9(7)V99',
          category: 'NUMERIC',
          offset: 70,
          length: 9,
          total_length: 9,
          occurs: null,
          digits: 9,
          scale: 2,
          signed: false,
          redefines: null,
          value: null,
        },
      ],
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

describe('Inventory', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  async function open(role: Role): Promise<HTMLElement> {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'projects/:id/inventory', component: Inventory }]),
        { provide: AuthService, useValue: authAs(role) },
        { provide: JOB_POLL_INTERVAL_MS, useValue: 100000 },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create('/projects/p1/inventory');
    return harness.routeNativeElement!;
  }

  async function settle(): Promise<void> {
    await harness.fixture.whenStable();
    harness.detectChanges();
  }

  async function loadReady(): Promise<void> {
    http.expectOne(INVENTORY_URL).flush(makeInventory());
    await settle();
    http.expectOne(LAYOUTS_URL).flush(LAYOUTS);
    http.expectOne(GRAPH_URL).flush(OVERVIEW_GRAPH);
    await settle();
  }

  afterEach(() => http.verify());

  it('shows the counts, programs, dead code, files and layouts', async () => {
    const page = await open('VIEWER');
    expect(page.querySelector('[role="status"]')?.textContent).toContain('Loading');
    await loadReady();
    expect(page.textContent).toContain('Working paragraphs');
    expect(page.querySelector('.summary')?.textContent).toContain('69');
    expect(page.textContent).toContain('8500-APPLY-WINTER-DISCOUNT');
    expect(page.textContent).toContain('RT-WINTER-1987-TABLE');
    expect(page.textContent).toContain('CUSTFILE');
    expect(page.textContent).toContain('read in 8100-READ-CUSTOMER');
    expect(page.textContent).toContain('CUSTOMER-RECORD');
    expect(page.textContent).toContain('100 bytes');
    const hrefs = [...page.querySelectorAll('a')].map((link) => link.getAttribute('href'));
    expect(hrefs).toContain('/projects/p1/sources/f1?line=216&end=232');
    expect(hrefs).toContain('/projects/p1/sources/f3');
  });

  it('every scrolling table can be reached by keyboard', async () => {
    const page = await open('VIEWER');
    await loadReady();
    for (const region of page.querySelectorAll('.table-scroll')) {
      expect(region.getAttribute('tabindex')).toBe('0');
      expect(region.getAttribute('role')).toBe('region');
    }
  });

  it('hides the run button from a viewer and an admin', async () => {
    for (const role of ['VIEWER', 'ADMIN'] as Role[]) {
      TestBed.resetTestingModule();
      const page = await open(role);
      await loadReady();
      expect(page.textContent).not.toContain('Run analysis');
    }
  });

  it('an empty project says who can start it', async () => {
    const page = await open('VIEWER');
    http.expectOne(INVENTORY_URL).flush(makeInventory({ analyzed: false, programs: [], summary: {} }));
    await settle();
    expect(page.textContent).toContain('has not been analyzed yet');
    expect(page.textContent).toContain('An engineer or architect can run');
  });

  it('an engineer runs the analysis and the page reloads when it finishes', async () => {
    const page = await open('ENGINEER');
    http.expectOne(INVENTORY_URL).flush(makeInventory({ analyzed: false, programs: [], summary: {} }));
    await settle();
    const run = [...page.querySelectorAll('button')].find((button) => button.textContent?.includes('Run analysis'))!;
    run.click();
    http.expectOne('/api/v1/projects/p1/analyze').flush(makeJob());
    await settle();
    expect(page.textContent).toContain('Analysis:');

    await new Promise((resolve) => setTimeout(resolve, 5));
    http.expectOne('/api/v1/jobs/j1').flush(makeJob({ status: 'SUCCEEDED' }));
    await settle();
    await loadReady();
    expect(page.querySelector('.summary')).not.toBeNull();
  });

  it('shows the server message when starting is refused', async () => {
    const page = await open('ENGINEER');
    await loadReady();
    const run = [...page.querySelectorAll('button')].find((button) => button.textContent?.includes('Run analysis'))!;
    run.click();
    http
      .expectOne('/api/v1/projects/p1/analyze')
      .flush(
        { error: { code: 'FORBIDDEN', message: 'You do not have permission to do this.', request_id: 'r' } },
        { status: 403, statusText: 'Forbidden' },
      );
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('You do not have permission');
  });

  it('shows an error with a working retry', async () => {
    const page = await open('VIEWER');
    http.expectOne(INVENTORY_URL).flush({}, { status: 500, statusText: 'Error' });
    await settle();
    const alert = page.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('could not be loaded');
    alert.querySelector('button')!.click();
    await settle();
    await loadReady();
    expect(page.querySelector('[role="alert"]')).toBeNull();
  });

  it('filters the layouts by program', async () => {
    const page = await open('VIEWER');
    await loadReady();
    const select = page.querySelector<HTMLSelectElement>('.field-inline select')!;
    select.value = 'RATECALC';
    select.dispatchEvent(new Event('change'));
    await settle();
    http
      .expectOne('/api/v1/projects/p1/inventory/layouts?limit=50&offset=0&program=RATECALC')
      .flush({ items: [], total: 0, limit: 50, offset: 0 });
    await settle();
    expect(page.textContent).toContain('No records for this program');
  });

  it('shows more layouts on request', async () => {
    const page = await open('VIEWER');
    http.expectOne(INVENTORY_URL).flush(makeInventory());
    await settle();
    http.expectOne(LAYOUTS_URL).flush({ ...LAYOUTS, total: 2 });
    http.expectOne(GRAPH_URL).flush(OVERVIEW_GRAPH);
    await settle();
    const more = [...page.querySelectorAll('button')].find((button) => button.textContent?.includes('Show more'))!;
    more.click();
    http
      .expectOne('/api/v1/projects/p1/inventory/layouts?limit=50&offset=1')
      .flush({ ...LAYOUTS, items: [{ ...LAYOUTS.items[0], id: 'l2', name: 'READ-RECORD' }], total: 2 });
    await settle();
    expect(page.textContent).toContain('READ-RECORD');
    expect(page.textContent).toContain('CUSTOMER-RECORD');
  });

  it('shows parser diagnostics when there are any', async () => {
    const page = await open('VIEWER');
    http.expectOne(INVENTORY_URL).flush(makeInventory({ diagnostics: ['X.cbl:1: something odd'] }));
    await settle();
    http.expectOne(LAYOUTS_URL).flush(LAYOUTS);
    http.expectOne(GRAPH_URL).flush(OVERVIEW_GRAPH);
    await settle();
    expect(page.textContent).toContain('X.cbl:1: something odd');
  });
});

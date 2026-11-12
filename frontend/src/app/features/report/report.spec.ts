import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AssessmentReport } from '../modernization/modernization.service';
import { ReportPage } from './report';

const REPORT: AssessmentReport = {
  title: 'BillRite modernization assessment',
  sections: [
    { heading: 'As-Is: the legacy application', paragraphs: ['5 programs.'], tables: [] },
    {
      heading: 'To-Be: target services and verified modules',
      paragraphs: ['Equivalence is decided by the harness.'],
      tables: [{ columns: ['Module', 'State'], rows: [['MTRVAL', 'APPROVED']] }],
    },
    {
      heading: 'Transition: order, routing and open items',
      paragraphs: ['Open items: none.'],
      tables: [],
    },
  ],
  limits: 'Limits: tested inputs only.',
  markdown: '# BillRite modernization assessment',
};

describe('ReportPage', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: HTMLElement;

  async function open(): Promise<void> {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'app/projects/:id/report', component: ReportPage }]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create('/app/projects/p1/report');
    page = harness.routeNativeElement!;
    http.expectOne('/api/v1/projects/p1/report').flush(REPORT);
    await harness.fixture.whenStable();
    harness.detectChanges();
  }

  function button(label: string): HTMLButtonElement {
    return [...page.querySelectorAll('button')].find((b) => b.textContent?.includes(label))!;
  }

  afterEach(() => http.verify());

  it('renders the three sections with their tables', async () => {
    await open();
    expect([...page.querySelectorAll('h2')].map((h) => h.textContent)).toEqual([
      'As-Is: the legacy application',
      'To-Be: target services and verified modules',
      'Transition: order, routing and open items',
    ]);
    expect(page.querySelector('tbody')?.textContent).toContain('MTRVAL');
    expect(page.textContent).toContain('Limits: tested inputs only.');
  });

  it('downloads the Markdown with the session and prints for a PDF', async () => {
    await open();
    const created = vi.fn(() => 'blob:report');
    const revoked = vi.fn();
    Object.assign(window.URL, { createObjectURL: created, revokeObjectURL: revoked });
    const clicked = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    button('Download Markdown').click();
    const request = http.expectOne('/api/v1/projects/p1/report.md');
    expect(request.request.responseType).toBe('blob');
    request.flush(new Blob(['# report']));
    expect(created).toHaveBeenCalled();
    expect(clicked).toHaveBeenCalled();
    const printed = vi.spyOn(window, 'print').mockImplementation(() => undefined);
    button('Print or save as PDF').click();
    expect(printed).toHaveBeenCalled();
  });
});

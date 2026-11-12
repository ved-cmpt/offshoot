import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { makeSource } from '../workbench/testing';
import { SourceViewer } from './source-viewer';

const SOURCE_URL = '/api/v1/projects/p1/sources/f2';
const LIST_URL = '/api/v1/projects/p1/sources';
const FILES = {
  items: [
    {
      id: 'f2',
      path: 'src/DEMO.cbl',
      name: 'DEMO.cbl',
      kind: 'PROGRAM',
      line_count: 5,
      sha256: 'a',
    },
    {
      id: 'f4',
      path: 'copy/RATES.cpy',
      name: 'RATES.cpy',
      kind: 'COPYBOOK',
      line_count: 9,
      sha256: 'b',
    },
  ],
  total: 2,
};

describe('SourceViewer', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;

  async function open(url = '/app/projects/p1/sources/f2'): Promise<HTMLElement> {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'app/projects/:id/sources/:file', component: SourceViewer }]),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create(url);
    return harness.routeNativeElement!;
  }

  async function settle(): Promise<void> {
    await harness.fixture.whenStable();
    harness.detectChanges();
  }

  async function loadReady(): Promise<void> {
    http.expectOne(SOURCE_URL).flush(makeSource());
    http.expectOne(LIST_URL).flush(FILES);
    await settle();
  }

  afterEach(() => http.verify());

  it('shows each line with its number, starting from a loading state', async () => {
    const page = await open();
    expect(page.querySelector('[role="status"]')?.textContent).toContain('Loading');
    await loadReady();
    expect(page.querySelector('h1')?.textContent).toBe('DEMO.cbl');
    const rows = page.querySelectorAll('.code tr');
    expect(rows).toHaveLength(5);
    expect(rows[0].querySelector('th')?.textContent).toBe('1');
    expect(rows[0].querySelector('pre')?.textContent).toContain('IDENTIFICATION');
    expect(rows[4].id).toBe('L5');
  });

  it('never treats source text as markup or a template', async () => {
    const page = await open();
    await loadReady();
    const line = page.querySelectorAll('.code pre')[1];
    expect(line.textContent).toContain('<script>alert(1)</script>');
    expect(line.textContent).toContain('{{ not a binding }}');
    expect(line.querySelector('script')).toBeNull();
    expect(page.querySelector('script')).toBeNull();
  });

  it('links a COPY line to its copybook, and a missing copybook gets no link', async () => {
    const page = await open();
    await loadReady();
    const rows = page.querySelectorAll('.code tr');
    expect(rows[2].querySelector('a')?.getAttribute('href')).toBe('/app/projects/p1/sources/f4');
    expect(rows[2].textContent).toContain('Open RATES');
    expect(rows[3].querySelector('a')).toBeNull();
  });

  it('marks lines that rules cite, in words for assistive technology', async () => {
    const page = await open();
    await loadReady();
    const rows = page.querySelectorAll('.code tr');
    expect(rows[2].classList).toContain('cited');
    expect(rows[2].textContent).toContain('Cited by 1 rules.');
    expect(rows[1].classList).not.toContain('cited');
    expect(page.textContent).toContain('Rules citing this file (1)');
    expect(page.querySelector('.spans a')?.getAttribute('href')).toContain('line=3&end=4');
  });

  it('highlights the range from the address', async () => {
    const page = await open('/app/projects/p1/sources/f2?line=2&end=3');
    await loadReady();
    const selected = page.querySelectorAll('.code tr.selected');
    expect([...selected].map((row) => row.id)).toEqual(['L2', 'L3']);
    expect(selected[0].textContent).toContain('Selected line.');
  });

  it('a backwards or nonsense range selects at most the first line', async () => {
    const page = await open('/app/projects/p1/sources/f2?line=3&end=1');
    await loadReady();
    expect([...page.querySelectorAll('.code tr.selected')].map((row) => row.id)).toEqual(['L3']);
  });

  it('moving between ranges in the same file does not refetch it', async () => {
    const page = await open('/app/projects/p1/sources/f2?line=1');
    await loadReady();
    await harness.navigateByUrl('/app/projects/p1/sources/f2?line=4');
    await settle();
    http.expectNone(SOURCE_URL);
    expect([...page.querySelectorAll('.code tr.selected')].map((row) => row.id)).toEqual(['L4']);
  });

  it('opening another file loads it', async () => {
    const page = await open();
    await loadReady();
    await harness.navigateByUrl('/app/projects/p1/sources/f4');
    http
      .expectOne('/api/v1/projects/p1/sources/f4')
      .flush(makeSource({ id: 'f4', name: 'RATES.cpy', rule_spans: [] }));
    http.expectOne(LIST_URL).flush(FILES);
    await settle();
    expect(page.querySelector('h1')?.textContent).toBe('RATES.cpy');
    expect(page.textContent).toContain('No rule cites this file yet');
    expect(page.querySelector('[aria-current="page"]')?.textContent).toContain('RATES.cpy');
  });

  it('a reply after leaving the page is dropped, not rendered', async () => {
    await open();
    const source = http.expectOne(SOURCE_URL);
    const files = http.expectOne(LIST_URL);
    harness.fixture.destroy();
    expect(source.cancelled).toBe(true);
    expect(files.cancelled).toBe(true);
  });

  it('only the latest file counts when files are switched quickly', async () => {
    const page = await open();
    const first = http.expectOne(SOURCE_URL);
    http.expectOne(LIST_URL).flush(FILES);
    await harness.navigateByUrl('/app/projects/p1/sources/f4');
    expect(first.cancelled).toBe(true);
    http
      .expectOne('/api/v1/projects/p1/sources/f4')
      .flush(makeSource({ id: 'f4', name: 'RATES.cpy' }));
    http.expectOne(LIST_URL).flush(FILES);
    await settle();
    expect(page.querySelector('h1')?.textContent).toBe('RATES.cpy');
  });

  it('the code can be scrolled by keyboard', async () => {
    const page = await open();
    await loadReady();
    const region = page.querySelector('.code-scroll')!;
    expect(region.getAttribute('tabindex')).toBe('0');
    expect(region.getAttribute('aria-label')).toContain('DEMO.cbl');
  });

  it('shows the server message for a missing file, with a working retry', async () => {
    const page = await open();
    http
      .expectOne(SOURCE_URL)
      .flush(
        { error: { code: 'NOT_FOUND', message: 'Source file not found.', request_id: 'r' } },
        { status: 404, statusText: 'Not Found' },
      );
    http.expectOne(LIST_URL).flush(FILES);
    await settle();
    const alert = page.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('Source file not found.');
    alert.querySelector('button')!.click();
    await settle();
    http.expectOne(SOURCE_URL).flush(makeSource());
    await settle();
    expect(page.querySelector('[role="alert"]')).toBeNull();
  });

  it('still shows the source when the file list fails', async () => {
    const page = await open();
    http.expectOne(SOURCE_URL).flush(makeSource());
    http.expectOne(LIST_URL).flush({}, { status: 500, statusText: 'Error' });
    await settle();
    expect(page.querySelectorAll('.code tr')).toHaveLength(5);
    expect(page.querySelector('.files')).toBeNull();
  });
});

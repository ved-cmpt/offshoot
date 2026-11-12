import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AuthService, Role } from '../../core/auth/auth.service';
import { ConfigService, PublicConfig } from '../../core/config/config.service';
import { authAs } from '../workbench/testing';
import { Projects } from './projects';
import { ProjectPage } from './projects.service';

const PAGE: ProjectPage = {
  items: [
    {
      id: 'p1',
      name: 'BillRite',
      description: 'Synthetic billing system.',
      source_kind: 'BUNDLED',
      status: 'IMPORTED',
      created_at: '2026-11-05T01:00:00Z',
      source_file_count: 12,
      source_line_count: 1548,
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

describe('Projects', () => {
  let fixture: ComponentFixture<Projects>;
  let http: HttpTestingController;
  let page: HTMLElement;

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function create(role: Role = 'VIEWER', demoMode = true): void {
    const config: PublicConfig = { demo_mode: demoMode, ai_mode: 'mock', demo_accounts: [] };
    TestBed.configureTestingModule({
      imports: [Projects],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: authAs(role) },
        { provide: ConfigService, useValue: { load: () => of(config) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Projects);
    page = fixture.nativeElement;
    fixture.detectChanges();
  }

  beforeEach((context) => {
    if (!context.task.name.startsWith('upload:')) {
      create();
    }
  });

  afterEach(() => http.verify());

  /** The upload form opens from the "New project" button. */
  function openUpload(): void {
    Array.from(page.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('New project'))!
      .click();
    fixture.detectChanges();
  }

  it('announces a loading state first', () => {
    expect(page.querySelector('[role="status"]')?.textContent).toContain('Loading');
    http.expectOne('/api/v1/projects').flush(PAGE);
  });

  it('lists the projects with their facts in words', async () => {
    http.expectOne('/api/v1/projects').flush(PAGE);
    await settle();
    const project = page.querySelector('.project')!;
    expect(project.querySelector('h2')?.textContent?.trim()).toBe('BillRite');
    expect(project.querySelector('h2 a')?.getAttribute('href')).toBe('/app/projects/p1/overview');
    expect(project.textContent).toContain('Synthetic billing system.');
    expect(project.textContent).toContain('Imported, not analyzed yet');
    expect(project.textContent).toContain('Bundled sample');
    expect(project.textContent).toContain('12');
    expect(project.textContent).toContain('1,548');
    expect(project.textContent).toContain('Nov 5, 2026');
    expect(page.querySelector('[role="status"]')).toBeNull();
  });

  it('shows an empty state that says what to do', async () => {
    http.expectOne('/api/v1/projects').flush({ ...PAGE, items: [], total: 0 });
    await settle();
    expect(page.textContent).toContain('no projects yet');
    expect(page.querySelector('.project')).toBeNull();
  });

  it('shows the server message, and retry recovers', async () => {
    http
      .expectOne('/api/v1/projects')
      .flush(
        { error: { code: 'INTERNAL_ERROR', message: 'Something broke.', request_id: 'r' } },
        { status: 500, statusText: 'Error' },
      );
    await settle();
    const alert = page.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('Something broke.');

    alert.querySelector('button')!.click();
    await settle();
    expect(page.querySelector('[role="status"]')).not.toBeNull();
    http.expectOne('/api/v1/projects').flush(PAGE);
    await settle();
    expect(page.querySelector('.project h2')?.textContent?.trim()).toBe('BillRite');
    expect(page.querySelector('[role="alert"]')).toBeNull();
  });

  it('upload: is hidden from viewers', async () => {
    create('VIEWER', false);
    http.expectOne('/api/v1/projects').flush(PAGE);
    await settle();
    expect(page.textContent).not.toContain('New project from COBOL sources');
  });

  it('upload: says it is off in the public demo', async () => {
    create('ENGINEER', true);
    http.expectOne('/api/v1/projects').flush(PAGE);
    await settle();
    expect(page.textContent).toContain('Uploads are turned off in the public demo');
    expect(page.querySelector('input[type="file"]')).toBeNull();
  });

  it('upload: sends the archive and the name, then lists the new project', async () => {
    create('ENGINEER', false);
    http.expectOne('/api/v1/projects').flush(PAGE);
    await settle();
    openUpload();
    const name = page.querySelector<HTMLInputElement>('input[type="text"]')!;
    name.value = 'Payroll';
    name.dispatchEvent(new Event('input'));
    const file = new File(['x'], 'payroll.zip', { type: 'application/zip' });
    const input = page.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { value: [file] });
    input.dispatchEvent(new Event('change'));
    [...page.querySelectorAll('button')]
      .find((b) => b.textContent?.includes('Create project'))!
      .click();
    const request = http.expectOne({ method: 'POST', url: '/api/v1/projects' });
    const body = request.request.body as FormData;
    expect(body.get('name')).toBe('Payroll');
    expect((body.get('archive') as File).name).toBe('payroll.zip');
    request.flush({
      ...PAGE.items[0],
      id: 'p2',
      name: 'Payroll',
      source_kind: 'UPLOAD',
      source_file_count: 3,
    });
    http.expectOne('/api/v1/projects').flush(PAGE);
    await settle();
    expect(page.querySelector('[role="status"]')?.textContent).toContain(
      'Created Payroll with 3 files.',
    );
  });

  it('upload: shows the server refusal', async () => {
    create('ARCHITECT', false);
    http.expectOne('/api/v1/projects').flush(PAGE);
    await settle();
    openUpload();
    const name = page.querySelector<HTMLInputElement>('input[type="text"]')!;
    name.value = 'Bad';
    name.dispatchEvent(new Event('input'));
    const input = page.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { value: [new File(['x'], 'bad.zip')] });
    input.dispatchEvent(new Event('change'));
    [...page.querySelectorAll('button')]
      .find((b) => b.textContent?.includes('Create project'))!
      .click();
    http.expectOne({ method: 'POST', url: '/api/v1/projects' }).flush(
      {
        error: {
          code: 'UPLOAD_PATH_REJECTED',
          message: 'Archive paths may not leave the archive.',
          request_id: 'r',
        },
      },
      { status: 422, statusText: 'Unprocessable' },
    );
    await settle();
    expect(page.querySelector('[role="alert"]')?.textContent).toContain(
      'Archive paths may not leave',
    );
  });
});

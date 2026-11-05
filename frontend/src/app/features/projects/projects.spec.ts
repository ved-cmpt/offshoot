import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

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

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [Projects],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(Projects);
    page = fixture.nativeElement;
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('announces a loading state first', () => {
    expect(page.querySelector('[role="status"]')?.textContent).toContain('Loading');
    http.expectOne('/api/v1/projects').flush(PAGE);
  });

  it('lists the projects with their facts in words', async () => {
    http.expectOne('/api/v1/projects').flush(PAGE);
    await settle();
    const project = page.querySelector('.project')!;
    expect(project.querySelector('h2')?.textContent?.trim()).toBe('BillRite');
    expect(project.querySelector('h2 a')?.getAttribute('href')).toBe('/projects/p1/inventory');
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
});

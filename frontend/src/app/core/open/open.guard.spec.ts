import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { nextRequest } from '../../../testing/http';
import { Project } from '../../features/projects/projects.service';
import { demoProject, openGuard } from './open.guard';

@Component({ template: 'page' })
class Page {}

const project = (id: string, name: string, kind: 'BUNDLED' | 'UPLOAD' = 'BUNDLED'): Project => ({
  id,
  name,
  description: null,
  source_kind: kind,
  status: 'ANALYZED',
  created_at: '2026-11-08T00:00:00Z',
  source_file_count: 12,
  source_line_count: 1464,
});

describe('demo links by name', () => {
  let router: Router;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'app/open/:kind/:name', canActivate: [openGuard], children: [] },
          { path: 'app/open/:kind', canActivate: [openGuard], children: [] },
          { path: 'app/projects', component: Page },
          { path: 'app/projects/:id/:screen', component: Page },
          { path: 'app/projects/:id/:screen/:item', component: Page },
        ]),
      ],
    });
    router = TestBed.inject(Router);
    http = TestBed.inject(HttpTestingController);
  });

  async function answerProjects(): Promise<void> {
    (await nextRequest(http, '/api/v1/projects')).flush({
      items: [project('live', 'BillRite live sample'), project('demo', 'BillRite')],
      total: 2,
      limit: 50,
      offset: 0,
    });
  }

  it('picks the bundled BillRite project, not the live sample', () => {
    expect(
      demoProject([project('live', 'BillRite live sample'), project('demo', 'BillRite')])?.id,
    ).toBe('demo');
    expect(demoProject([project('u', 'Mine', 'UPLOAD')])?.id).toBe('u');
    expect(demoProject([])).toBeNull();
  });

  it('opens a module by its program name', async () => {
    const harness = await RouterTestingHarness.create();
    const navigation = harness.navigateByUrl('/app/open/module/RATECALC');
    await answerProjects();
    (await nextRequest(http, '/api/v1/projects/demo/modules')).flush([
      { id: 'm1', program: 'MTRVAL' },
      { id: 'm2', program: 'RATECALC' },
    ]);
    await navigation;
    expect(router.url).toBe('/app/projects/demo/modules/m2');
  });

  it('opens a source file by name at the given lines', async () => {
    const harness = await RouterTestingHarness.create();
    const navigation = harness.navigateByUrl('/app/open/source/RATECALC.cbl?line=135');
    await answerProjects();
    (await nextRequest(http, '/api/v1/projects/demo/sources')).flush({
      items: [{ id: 'f9', name: 'RATECALC.cbl' }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    await navigation;
    expect(router.url).toBe('/app/projects/demo/sources/f9?line=135');
  });

  it('keeps filters on the rules link', async () => {
    const harness = await RouterTestingHarness.create();
    const navigation = harness.navigateByUrl('/app/open/rules?program=RATECALC&flag=SPAN_INVALID');
    await answerProjects();
    await navigation;
    expect(router.url).toBe('/app/projects/demo/rules?program=RATECALC&flag=SPAN_INVALID');
  });

  it('falls back to the module list for an unknown program', async () => {
    const harness = await RouterTestingHarness.create();
    const navigation = harness.navigateByUrl('/app/open/module/NOPE');
    await answerProjects();
    (await nextRequest(http, '/api/v1/projects/demo/modules')).flush([]);
    await navigation;
    expect(router.url).toBe('/app/projects/demo/modules');
  });
});

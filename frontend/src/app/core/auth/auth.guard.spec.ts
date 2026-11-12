import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, inject } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { firstValueFrom } from 'rxjs';
import { beforeEach, describe, expect, it } from 'vitest';

import { nextRequest } from '../../../testing/http';
import { legacyMatcher } from '../../app.routes';
import { authGuard, guestGuard } from './auth.guard';
import { AuthService } from './auth.service';

@Component({ template: 'page' })
class Page {}

describe('route guards', () => {
  let router: Router;
  let http: HttpTestingController;

  async function signIn(): Promise<void> {
    const auth = TestBed.inject(AuthService);
    const login = firstValueFrom(auth.login('a@b.co', 'x'));
    http.expectOne('/api/v1/auth/login').flush({
      access_token: 't',
      token_type: 'bearer',
      expires_in: 900,
      user: { id: '1', email: 'a@b.co', display_name: 'A', role: 'VIEWER' },
    });
    await login;
  }

  /** The guard's first visit asks the server once for a session; answer "none". */
  async function noSession(): Promise<void> {
    const request = await nextRequest(http, '/api/v1/auth/refresh');
    request.flush(null, { status: 401, statusText: 'Unauthorized' });
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: '', component: Page },
          {
            matcher: legacyMatcher,
            redirectTo: ({ url, queryParams }) =>
              inject(Router).createUrlTree(['/app', ...url.map((segment) => segment.path)], {
                queryParams,
              }),
          },
          { path: 'app/login', component: Page, canActivate: [guestGuard] },
          { path: 'app/projects', component: Page, canActivate: [authGuard] },
          { path: 'app/projects/:id/rules', component: Page, canActivate: [authGuard] },
        ]),
      ],
    });
    router = TestBed.inject(Router);
    http = TestBed.inject(HttpTestingController);
  });

  it('sends a signed-out visitor to login and remembers where they were going', async () => {
    const harness = await RouterTestingHarness.create();
    const navigation = harness.navigateByUrl('/app/projects/p1/rules');
    await noSession();
    await navigation;
    expect(router.url).toBe('/app/login?returnUrl=%2Fapp%2Fprojects%2Fp1%2Frules');
  });

  it('needs no return address for the front door of the app', async () => {
    const harness = await RouterTestingHarness.create();
    const navigation = harness.navigateByUrl('/app/projects');
    await noSession();
    await navigation;
    expect(router.url).toBe('/app/login');
  });

  it('restores a session from the refresh cookie on the first visit only', async () => {
    const harness = await RouterTestingHarness.create();
    const navigation = harness.navigateByUrl('/app/projects');
    (await nextRequest(http, '/api/v1/auth/refresh')).flush({
      access_token: 't',
      token_type: 'bearer',
      expires_in: 900,
      user: { id: '1', email: 'a@b.co', display_name: 'A', role: 'VIEWER' },
    });
    await navigation;
    expect(router.url).toBe('/app/projects');
    await harness.navigateByUrl('/app/projects/p1/rules');
    http.expectNone('/api/v1/auth/refresh');
    expect(router.url).toBe('/app/projects/p1/rules');
  });

  it('never asks for a session on the public landing page', async () => {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/');
    http.expectNone('/api/v1/auth/refresh');
    expect(router.url).toBe('/');
  });

  it('lets a signed-in user through', async () => {
    await signIn();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/app/projects');
    expect(router.url).toBe('/app/projects');
  });

  it('keeps a signed-in user away from the login page', async () => {
    await signIn();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/app/login');
    expect(router.url).toBe('/app/projects');
  });

  it('shows the login page to a signed-out visitor', async () => {
    const harness = await RouterTestingHarness.create();
    const navigation = harness.navigateByUrl('/app/login');
    await noSession();
    await navigation;
    expect(router.url).toBe('/app/login');
  });

  it('redirects the old paths into /app, keeping the query', async () => {
    await signIn();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/projects/p1/rules?program=RATECALC');
    expect(router.url).toBe('/app/projects/p1/rules?program=RATECALC');
    await harness.navigateByUrl('/login');
    expect(router.url).toBe('/app/projects');
  });
});

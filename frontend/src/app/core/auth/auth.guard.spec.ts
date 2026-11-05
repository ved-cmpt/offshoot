import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { firstValueFrom } from 'rxjs';
import { beforeEach, describe, expect, it } from 'vitest';

import { authGuard, guestGuard } from './auth.guard';
import { AuthService } from './auth.service';

@Component({ template: 'page' })
class Page {}

describe('route guards', () => {
  let router: Router;

  async function signIn(): Promise<void> {
    const auth = TestBed.inject(AuthService);
    const login = firstValueFrom(auth.login('a@b.co', 'x'));
    TestBed.inject(HttpTestingController)
      .expectOne('/api/v1/auth/login')
      .flush({
        access_token: 't',
        token_type: 'bearer',
        expires_in: 900,
        user: { id: '1', email: 'a@b.co', display_name: 'A', role: 'VIEWER' },
      });
    await login;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'login', component: Page, canActivate: [guestGuard] },
          { path: 'projects', component: Page, canActivate: [authGuard] },
        ]),
      ],
    });
    router = TestBed.inject(Router);
  });

  it('sends a signed-out visitor to login and remembers where they were going', async () => {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/projects');
    expect(router.url).toBe('/login?returnUrl=%2Fprojects');
  });

  it('lets a signed-in user through', async () => {
    await signIn();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/projects');
    expect(router.url).toBe('/projects');
  });

  it('keeps a signed-in user away from the login page', async () => {
    await signIn();
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/login');
    expect(router.url).toBe('/projects');
  });

  it('shows the login page to a signed-out visitor', async () => {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/login');
    expect(router.url).toBe('/login');
  });
});

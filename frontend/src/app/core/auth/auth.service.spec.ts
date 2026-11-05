import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AuthService, Session } from './auth.service';

const SESSION: Session = {
  access_token: 'access-1',
  token_type: 'bearer',
  expires_in: 900,
  user: { id: '1', email: 'a@b.co', display_name: 'A', role: 'VIEWER' },
};

/** Let the promise chain behind refresh() reach the HTTP layer. */
async function flushMicrotasks(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve));
}

describe('AuthService', () => {
  let auth: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('starts signed out', () => {
    expect(auth.isSignedIn()).toBe(false);
    expect(auth.token).toBeNull();
  });

  it('holds the access token in memory and nowhere else after login', async () => {
    const login = firstValueFrom(auth.login('a@b.co', 'secret'));
    const request = http.expectOne('/api/v1/auth/login');
    expect(request.request.body).toEqual({ email: 'a@b.co', password: 'secret' });
    request.flush(SESSION);
    await login;

    expect(auth.token).toBe('access-1');
    expect(auth.user()?.email).toBe('a@b.co');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain('access-1');
  });

  it('stays signed out when login fails', async () => {
    const login = firstValueFrom(auth.login('a@b.co', 'nope'));
    http.expectOne('/api/v1/auth/login').flush(
      { error: { code: 'INVALID_CREDENTIALS', message: 'No.', request_id: 'x' } },
      { status: 401, statusText: 'Unauthorized' },
    );
    await expect(login).rejects.toBeTruthy();
    expect(auth.isSignedIn()).toBe(false);
  });

  it('sends the CSRF header when refreshing', async () => {
    const refreshed = firstValueFrom(auth.refresh());
    await flushMicrotasks();
    const request = http.expectOne('/api/v1/auth/refresh');
    expect(request.request.headers.get('X-LegacyLens-CSRF')).toBe('1');
    request.flush({ ...SESSION, access_token: 'access-2' });
    await expect(refreshed).resolves.toBe('access-2');
    expect(auth.token).toBe('access-2');
  });

  it('shares one exchange between simultaneous refresh callers', async () => {
    const results = Promise.all([firstValueFrom(auth.refresh()), firstValueFrom(auth.refresh())]);
    await flushMicrotasks();
    http.expectOne('/api/v1/auth/refresh').flush(SESSION);
    await expect(results).resolves.toEqual(['access-1', 'access-1']);
  });

  it('runs a new exchange once the last one has finished', async () => {
    const first = firstValueFrom(auth.refresh());
    await flushMicrotasks();
    http.expectOne('/api/v1/auth/refresh').flush(SESSION);
    await first;

    const second = firstValueFrom(auth.refresh());
    await flushMicrotasks();
    http.expectOne('/api/v1/auth/refresh').flush({ ...SESSION, access_token: 'access-2' });
    await expect(second).resolves.toBe('access-2');
  });

  it('restores a session from the refresh cookie', async () => {
    const restored = auth.restoreSession();
    await flushMicrotasks();
    http.expectOne('/api/v1/auth/refresh').flush(SESSION);
    await restored;
    expect(auth.isSignedIn()).toBe(true);
  });

  it('treats having no session at startup as a normal outcome', async () => {
    const restored = auth.restoreSession();
    await flushMicrotasks();
    http
      .expectOne('/api/v1/auth/refresh')
      .flush({ error: { code: 'INVALID_REFRESH_TOKEN' } }, { status: 401, statusText: 'Unauthorized' });
    await expect(restored).resolves.toBeUndefined();
    expect(auth.isSignedIn()).toBe(false);
  });

  it('clears the session on logout, sending the CSRF header', async () => {
    const login = firstValueFrom(auth.login('a@b.co', 'secret'));
    http.expectOne('/api/v1/auth/login').flush(SESSION);
    await login;

    const logout = firstValueFrom(auth.logout());
    const request = http.expectOne('/api/v1/auth/logout');
    expect(request.request.headers.get('X-LegacyLens-CSRF')).toBe('1');
    request.flush(null, { status: 204, statusText: 'No Content' });
    await logout;
    expect(auth.token).toBeNull();
    expect(auth.isSignedIn()).toBe(false);
  });

  it('clears the local session even when the logout request fails', async () => {
    const login = firstValueFrom(auth.login('a@b.co', 'secret'));
    http.expectOne('/api/v1/auth/login').flush(SESSION);
    await login;

    const logout = firstValueFrom(auth.logout());
    http.expectOne('/api/v1/auth/logout').flush(null, { status: 500, statusText: 'Error' });
    await expect(logout).rejects.toBeTruthy();
    expect(auth.isSignedIn()).toBe(false);
  });
});

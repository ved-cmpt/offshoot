import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { authInterceptor } from './auth.interceptor';
import { AuthService, Session } from './auth.service';

const SESSION: Session = {
  access_token: 'fresh-token',
  token_type: 'bearer',
  expires_in: 900,
  user: { id: '1', email: 'a@b.co', display_name: 'A', role: 'VIEWER' },
};
const UNAUTHORIZED = { status: 401, statusText: 'Unauthorized' };

async function flushMicrotasks(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve));
}

describe('authInterceptor', () => {
  let client: HttpClient;
  let http: HttpTestingController;
  let auth: AuthService;

  async function signIn(): Promise<void> {
    const login = firstValueFrom(auth.login('a@b.co', 'x'));
    http.expectOne('/api/v1/auth/login').flush({ ...SESSION, access_token: 'old-token' });
    await login;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    client = TestBed.inject(HttpClient);
    http = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
  });

  afterEach(() => http.verify());

  it('adds the bearer token to API requests', async () => {
    await signIn();
    client.get('/api/v1/projects').subscribe();
    const request = http.expectOne('/api/v1/projects');
    expect(request.request.headers.get('Authorization')).toBe('Bearer old-token');
    request.flush({});
  });

  it('does not send the token to other origins', async () => {
    await signIn();
    client.get('https://elsewhere.example/api/v1/projects').subscribe();
    const request = http.expectOne('https://elsewhere.example/api/v1/projects');
    expect(request.request.headers.has('Authorization')).toBe(false);
    request.flush({});
  });

  it('does not attach a token to the login request', async () => {
    await signIn();
    auth.login('a@b.co', 'x').subscribe();
    const request = http.expectOne('/api/v1/auth/login');
    expect(request.request.headers.has('Authorization')).toBe(false);
    request.flush(SESSION);
  });

  it('refreshes once on a 401 and retries with the new token', async () => {
    await signIn();
    const result = firstValueFrom(client.get('/api/v1/projects'));
    http.expectOne('/api/v1/projects').flush({}, UNAUTHORIZED);
    await flushMicrotasks();
    http.expectOne('/api/v1/auth/refresh').flush(SESSION);
    await flushMicrotasks();
    const retry = http.expectOne('/api/v1/projects');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer fresh-token');
    retry.flush({ ok: true });
    await expect(result).resolves.toEqual({ ok: true });
  });

  it('shares one refresh between several requests that fail together', async () => {
    await signIn();
    const results = Promise.all([
      firstValueFrom(client.get('/api/v1/a')),
      firstValueFrom(client.get('/api/v1/b')),
    ]);
    http.expectOne('/api/v1/a').flush({}, UNAUTHORIZED);
    http.expectOne('/api/v1/b').flush({}, UNAUTHORIZED);
    await flushMicrotasks();
    http.expectOne('/api/v1/auth/refresh').flush(SESSION);
    await flushMicrotasks();
    http.expectOne('/api/v1/a').flush({ a: 1 });
    http.expectOne('/api/v1/b').flush({ b: 2 });
    await expect(results).resolves.toEqual([{ a: 1 }, { b: 2 }]);
  });

  it('gives up without looping when the retry also gets a 401', async () => {
    await signIn();
    const result = firstValueFrom(client.get('/api/v1/projects'));
    http.expectOne('/api/v1/projects').flush({}, UNAUTHORIZED);
    await flushMicrotasks();
    http.expectOne('/api/v1/auth/refresh').flush(SESSION);
    await flushMicrotasks();
    http.expectOne('/api/v1/projects').flush({}, UNAUTHORIZED);
    await expect(result).rejects.toMatchObject({ status: 401 });
  });

  it('ends the session and goes to login when the refresh fails', async () => {
    await signIn();
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const result = firstValueFrom(client.get('/api/v1/projects'));
    http.expectOne('/api/v1/projects').flush({}, UNAUTHORIZED);
    await flushMicrotasks();
    http.expectOne('/api/v1/auth/refresh').flush({}, UNAUTHORIZED);
    await expect(result).rejects.toMatchObject({ status: 401 });
    expect(auth.isSignedIn()).toBe(false);
    expect(navigate).toHaveBeenCalledWith(['/login'], expect.anything());
  });

  it('passes other errors straight through without refreshing', async () => {
    await signIn();
    for (const status of [403, 404, 500]) {
      const result = firstValueFrom(client.get('/api/v1/projects'));
      http.expectOne('/api/v1/projects').flush({}, { status, statusText: 'Error' });
      await expect(result).rejects.toMatchObject({ status });
    }
    http.expectNone('/api/v1/auth/refresh');
    expect(auth.isSignedIn()).toBe(true);
  });
});

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ConfigService, PublicConfig } from '../../core/config/config.service';
import { Login } from './login';

const CONFIG: PublicConfig = {
  demo_mode: true,
  ai_mode: 'mock',
  demo_accounts: [
    {
      username: 'viewer',
      email: 'viewer@demo.dev',
      password: 'v-pass',
      display_name: 'Vera Viewer',
      role: 'VIEWER',
    },
    {
      username: 'engineer',
      email: 'engineer@demo.dev',
      password: 'e-pass',
      display_name: 'Eli Engineer',
      role: 'ENGINEER',
    },
    {
      username: 'architect',
      email: 'architect@demo.dev',
      password: 'a-pass',
      display_name: 'Ari Architect',
      role: 'ARCHITECT',
    },
    {
      username: 'admin',
      email: 'admin@demo.dev',
      password: 'd-pass',
      display_name: 'Ada Admin',
      role: 'ADMIN',
    },
  ],
};
const SESSION = {
  access_token: 't',
  token_type: 'bearer',
  expires_in: 900,
  user: {
    id: '1',
    username: 'viewer',
    email: 'viewer@demo.dev',
    display_name: 'Vera Viewer',
    role: 'VIEWER',
  },
};

describe('Login', () => {
  let fixture: ComponentFixture<Login>;
  let http: HttpTestingController;
  let page: HTMLElement;
  let navigateByUrl: ReturnType<typeof vi.spyOn>;
  let returnUrl: string | null;

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function render(config: PublicConfig | null = CONFIG): Promise<void> {
    fixture = TestBed.createComponent(Login);
    page = fixture.nativeElement;
    fixture.detectChanges();
    const request = http.expectOne('/api/v1/config');
    if (config) {
      request.flush(config);
    } else {
      request.flush({}, { status: 500, statusText: 'Error' });
    }
    await settle();
  }

  function setInput(id: string, value: string): void {
    const input = page.querySelector<HTMLInputElement>(`#${id}`)!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  function buttons(): HTMLButtonElement[] {
    return Array.from(page.querySelectorAll('button'));
  }

  function buttonNamed(name: string): HTMLButtonElement {
    return buttons().find((button) => button.textContent?.includes(name))!;
  }

  beforeEach(() => {
    returnUrl = null;
    TestBed.configureTestingModule({
      imports: [Login],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useFactory: () => ({
            snapshot: { queryParamMap: convertToParamMap(returnUrl ? { returnUrl } : {}) },
          }),
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    navigateByUrl = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
  });

  afterEach(() => http.verify());

  it('shows a loading state until the demo accounts arrive', () => {
    fixture = TestBed.createComponent(Login);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="status"]').textContent).toContain('Loading');
    http.expectOne('/api/v1/config').flush(CONFIG);
  });

  it('shows one demo card per role, with published credentials and a banner', async () => {
    await render();
    const cards = page.querySelectorAll('.account');
    expect(cards.length).toBe(4);
    for (const [index, role] of ['VIEWER', 'ENGINEER', 'ARCHITECT', 'ADMIN'].entries()) {
      expect(cards[index].querySelector('h3')?.textContent).toBe(role);
    }
    expect(cards[0].querySelector('dl')?.textContent).toContain('Username');
    expect(cards[0].querySelector('dl')?.textContent).toContain('viewer');
    expect(cards[0].querySelector('dl')?.textContent).not.toContain('@');
    expect(cards[0].textContent).toContain('v-pass');
    expect(page.querySelector('.demo-banner')?.textContent).toContain('synthetic');
  });

  it('has no banner or cards outside demo mode', async () => {
    await render({ demo_mode: false, ai_mode: 'mock', demo_accounts: [] });
    expect(page.querySelector('.demo-banner')).toBeNull();
    expect(page.querySelectorAll('.account').length).toBe(0);
    expect(page.textContent).toContain('No demo accounts are available');
  });

  it('offers a retry when the demo accounts fail to load, and the form still works', async () => {
    await render(null);
    expect(page.querySelector('[role="alert"]')?.textContent).toContain('could not be loaded');
    expect(page.querySelector('#username')).not.toBeNull();

    buttonNamed('Try again').click();
    await settle();
    http.expectOne('/api/v1/config').flush(CONFIG);
    await settle();
    expect(page.querySelectorAll('.account').length).toBe(4);
  });

  it('labels every form input', async () => {
    await render();
    for (const id of ['username', 'password']) {
      expect(page.querySelector(`label[for="${id}"]`)).not.toBeNull();
      expect(page.querySelector(`#${id}`)).not.toBeNull();
    }
  });

  it('every control is a native, keyboard-reachable element', async () => {
    await render();
    const controls = page.querySelectorAll<HTMLElement>('button, input');
    expect(controls.length).toBeGreaterThan(0);
    for (const control of Array.from(controls)) {
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
    }
    for (const button of buttons()) {
      expect(button.type === 'button' || button.type === 'submit').toBe(true);
    }
  });

  it('submits the form, then goes to the projects page', async () => {
    await render();
    setInput('username', 'viewer');
    setInput('password', 'v-pass');
    page.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle();

    const request = http.expectOne('/api/v1/auth/login');
    expect(request.request.body).toEqual({ username: 'viewer', password: 'v-pass' });
    expect(buttonNamed('Signing in').disabled).toBe(true);
    request.flush(SESSION);
    await settle();
    expect(navigateByUrl).toHaveBeenCalledWith('/projects');
  });

  it('returns to the page the visitor originally asked for', async () => {
    returnUrl = '/projects/123';
    await render();
    buttonNamed('Sign in as Vera Viewer').click();
    await settle();
    http.expectOne('/api/v1/auth/login').flush(SESSION);
    await settle();
    expect(navigateByUrl).toHaveBeenCalledWith('/projects/123');
  });

  it('signs in with one click on a demo card', async () => {
    await render();
    buttonNamed('Sign in as Ari Architect').click();
    await settle();
    const request = http.expectOne('/api/v1/auth/login');
    expect(request.request.body).toEqual({ username: 'architect', password: 'a-pass' });
    request.flush({ ...SESSION, user: { ...SESSION.user, role: 'ARCHITECT' } });
    await settle();
    expect(navigateByUrl).toHaveBeenCalledWith('/projects');
  });

  it('does not send an empty form, and explains what is missing', async () => {
    await render();
    page.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle();
    http.expectNone('/api/v1/auth/login');
    expect(page.querySelector('#username-error')?.textContent).toContain('username');
    expect(page.querySelector('#password-error')?.textContent).toContain('password');
    expect(page.querySelector('#username')?.getAttribute('aria-describedby')).toBe(
      'username-error',
    );
    expect(page.querySelector('#username')?.getAttribute('aria-invalid')).toBe('true');
  });

  it.each([
    [401, 'Username or password is incorrect.'],
    [429, 'Too many sign-in attempts.'],
  ])('shows the server message on a %i and allows another try', async (status, message) => {
    await render();
    buttonNamed('Sign in as Vera Viewer').click();
    await settle();
    http
      .expectOne('/api/v1/auth/login')
      .flush({ error: { code: 'X', message, request_id: 'r' } }, { status, statusText: 'Error' });
    await settle();
    expect(page.querySelector('.form-error')?.textContent).toContain(message);
    expect(page.querySelector('.form-error')?.getAttribute('role')).toBe('alert');
    expect(buttonNamed('Sign in as Vera Viewer').disabled).toBe(false);
    expect(navigateByUrl).not.toHaveBeenCalled();
  });

  it('caches nothing about a failed config load', async () => {
    await render(null);
    const config = TestBed.inject(ConfigService);
    config.load().subscribe();
    http.expectOne('/api/v1/config').flush(CONFIG);
  });
});

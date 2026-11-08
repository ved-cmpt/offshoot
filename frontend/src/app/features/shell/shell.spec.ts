import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthService, Role } from '../../core/auth/auth.service';
import { Shell } from './shell';

describe('Shell', () => {
  let fixture: ComponentFixture<Shell>;
  let http: HttpTestingController;
  let page: HTMLElement;
  let navigate: ReturnType<typeof vi.spyOn>;

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function render(
    role: Role = 'ARCHITECT',
    demoMode = true,
    extra: Record<string, unknown> = {},
  ): Promise<void> {
    const auth = TestBed.inject(AuthService);
    const login = firstValueFrom(auth.login('a@b.co', 'x'));
    http.expectOne('/api/v1/auth/login').flush({
      access_token: 't',
      token_type: 'bearer',
      expires_in: 900,
      user: { id: '1', email: 'a@b.co', display_name: 'Ari Architect', role },
    });
    await login;
    fixture = TestBed.createComponent(Shell);
    page = fixture.nativeElement;
    fixture.detectChanges();
    http
      .expectOne('/api/v1/config')
      .flush({ demo_mode: demoMode, ai_mode: 'mock', demo_accounts: [], ...extra });
    await settle();
  }

  function buttonNamed(name: string): HTMLButtonElement {
    return Array.from(page.querySelectorAll('button')).find((b) => b.textContent?.includes(name))!;
  }

  beforeEach(() => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query }));
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [Shell],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  afterEach(() => {
    http.verify();
    vi.unstubAllGlobals();
  });

  it.each<Role>(['VIEWER', 'ENGINEER', 'ARCHITECT', 'ADMIN'])(
    'shows the user and the %s role',
    async (role) => {
      await render(role);
      expect(page.querySelector('.identity__name')?.textContent).toBe('Ari Architect');
      expect(page.querySelector('.role-badge')?.textContent).toContain(role);
    },
  );

  it('shows the demo banner in demo mode only', async () => {
    await render('VIEWER', true);
    expect(page.querySelector('.demo-banner')).not.toBeNull();
  });

  it('says on the public demo that no code runs and that it resets daily', async () => {
    await render('VIEWER', true, { execution_enabled: false, demo_reset_hours: 24 });
    const banner = page.querySelector('.demo-banner')?.textContent ?? '';
    expect(banner).toContain('simulated AI responses');
    // A real em dash, never the replacement character a mis-decoded edit once left (Run 06).
    expect(banner).toContain('Public demo \u2014 synthetic COBOL app');
    expect(banner).not.toContain('\ufffd');
    expect(banner).toContain('No code is compiled or run here');
    expect(banner).toContain('resets every day');
  });

  it('keeps the banner short where code runs and nothing resets', async () => {
    await render('VIEWER', true);
    const banner = page.querySelector('.demo-banner')?.textContent ?? '';
    expect(banner).not.toContain('No code is compiled');
    expect(banner).not.toContain('resets');
  });

  it('hides the demo banner outside demo mode', async () => {
    await render('VIEWER', false);
    expect(page.querySelector('.demo-banner')).toBeNull();
  });

  it('has landmarks and a skip link for keyboard users', async () => {
    await render();
    expect(page.querySelector('a.skip-link')?.getAttribute('href')).toBe('#main');
    expect(page.querySelector('main#main')).not.toBeNull();
    expect(page.querySelector('nav')?.getAttribute('aria-label')).toBe('Main');
    expect(page.querySelector('header')).not.toBeNull();
  });

  it('signs out through the API and returns to login', async () => {
    await render();
    buttonNamed('Sign out').click();
    await settle();
    expect(buttonNamed('Signing out').disabled).toBe(true);
    http.expectOne('/api/v1/auth/logout').flush(null, { status: 204, statusText: 'No Content' });
    await settle();
    expect(navigate).toHaveBeenCalledWith(['/login']);
    expect(TestBed.inject(AuthService).isSignedIn()).toBe(false);
  });

  it('still returns to login when the sign-out request fails', async () => {
    await render();
    buttonNamed('Sign out').click();
    await settle();
    http.expectOne('/api/v1/auth/logout').flush(null, { status: 500, statusText: 'Error' });
    await settle();
    expect(navigate).toHaveBeenCalledWith(['/login']);
    expect(TestBed.inject(AuthService).isSignedIn()).toBe(false);
  });

  it('switches between the two themes, labelled in words', async () => {
    await render();
    buttonNamed('Use dark theme').click();
    await settle();
    expect(document.documentElement.dataset['theme']).toBe('dark');
    buttonNamed('Use light theme').click();
    await settle();
    expect(document.documentElement.dataset['theme']).toBe('light');
  });
});

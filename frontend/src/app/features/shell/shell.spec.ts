import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthService, Role } from '../../core/auth/auth.service';
import { parseLocation } from '../../core/project/project-context';
import { TOUR_KEY } from './tour';
import { Shell, initials } from './shell';
import { score } from './command-palette';

const PROJECTS = {
  items: [
    {
      id: 'p1',
      name: 'BillRite',
      description: null,
      source_kind: 'BUNDLED',
      status: 'ANALYZED',
      created_at: '2026-11-08T00:00:00Z',
      source_file_count: 12,
      source_line_count: 1464,
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

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
    http.match('/api/v1/projects').forEach((request) => request.flush(PROJECTS));
    await settle();
  }

  function buttonNamed(name: string): HTMLButtonElement {
    return Array.from(page.querySelectorAll('button')).find(
      (b) => b.textContent?.includes(name) || b.getAttribute('aria-label') === name,
    )!;
  }

  function openUserMenu(): void {
    page.querySelector<HTMLButtonElement>('.user__button')!.click();
    fixture.detectChanges();
  }

  beforeEach(() => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query }));
    localStorage.clear();
    // The tour offers itself on a first visit to the demo; these tests are not about it.
    localStorage.setItem(TOUR_KEY, '1');
    TestBed.configureTestingModule({
      imports: [Shell],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  afterEach(() => {
    http.match('/api/v1/projects').forEach((request) => request.flush(PROJECTS));
    http.verify();
    vi.unstubAllGlobals();
  });

  it.each<Role>(['VIEWER', 'ENGINEER', 'ARCHITECT', 'ADMIN'])(
    'shows the user and the %s role',
    async (role) => {
      await render(role);
      expect(page.querySelector('.identity__name')?.textContent).toBe('Ari Architect');
      expect(page.querySelector('.role-badge')?.textContent).toContain(role);
      expect(page.querySelector('.avatar')?.textContent).toBe('AA');
    },
  );

  it.each<[Role, string[]]>([
    ['VIEWER', ['Projects']],
    ['ADMIN', ['Projects', 'Audit log']],
  ])('shows the audit log only to architects and admins (%s)', async (role, expected) => {
    await render(role);
    const links = Array.from(page.querySelectorAll('.nav a')).map((a) => a.textContent?.trim());
    expect(links).toEqual(expected);
  });

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

  it('has landmarks, breadcrumbs and a skip link for keyboard users', async () => {
    await render();
    expect(page.querySelector('a.skip-link')?.getAttribute('href')).toBe('#main');
    expect(page.querySelector('main#main')).not.toBeNull();
    expect(page.querySelector('nav[aria-label="Main"]')).not.toBeNull();
    expect(page.querySelector('nav[aria-label="Breadcrumb"] [aria-current="page"]')?.textContent).toBe('Projects');
    expect(page.querySelector('header')).not.toBeNull();
  });

  it('signs out from the user menu and returns to login', async () => {
    await render();
    openUserMenu();
    expect(page.querySelector('.user__button')?.getAttribute('aria-expanded')).toBe('true');
    buttonNamed('Sign out').click();
    await settle();
    http.expectOne('/api/v1/auth/logout').flush(null, { status: 204, statusText: 'No Content' });
    await settle();
    expect(navigate).toHaveBeenCalledWith(['/app/login']);
    expect(TestBed.inject(AuthService).isSignedIn()).toBe(false);
  });

  it('still returns to login when the sign-out request fails', async () => {
    await render();
    openUserMenu();
    buttonNamed('Sign out').click();
    await settle();
    http.expectOne('/api/v1/auth/logout').flush(null, { status: 500, statusText: 'Error' });
    await settle();
    expect(navigate).toHaveBeenCalledWith(['/app/login']);
    expect(TestBed.inject(AuthService).isSignedIn()).toBe(false);
  });

  it('switches between the two themes, labelled in words', async () => {
    await render();
    buttonNamed('Use light theme').click();
    await settle();
    expect(document.documentElement.dataset['theme']).toBe('light');
    buttonNamed('Use dark theme').click();
    await settle();
    expect(document.documentElement.dataset['theme']).toBe('dark');
  });

  it('collapses the sidebar to a rail and remembers it', async () => {
    await render();
    buttonNamed('Collapse the sidebar').click();
    await settle();
    expect(page.querySelector('.layout')?.classList).toContain('layout--collapsed');
    expect(localStorage.getItem('offshoot-sidebar')).toBe('1');
    expect(buttonNamed('Expand the sidebar').getAttribute('aria-pressed')).toBe('true');
  });

  it('opens the command palette with Ctrl+K and the shortcuts with ?', async () => {
    await render();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }));
    await settle();
    await new Promise((resolve) => setTimeout(resolve));
    http.match(() => true).forEach((request) => {
      const url = request.request.url;
      const empty = { items: [], total: 0, limit: 50, offset: 0, counts: {}, programs: [] };
      request.flush(url.endsWith('/projects') ? PROJECTS : url.endsWith('/modules') ? [] : empty);
    });
    await settle();
    expect(page.querySelector('app-command-palette input[role="combobox"]')).not.toBeNull();
    const palette = page.querySelector('app-command-palette') as HTMLElement;
    expect(palette.textContent).toContain('Projects');
    expect(palette.textContent).toContain('Sign out');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }));
    await settle();
    expect(page.querySelector('app-shortcuts-dialog')?.textContent).toContain('Open the command palette');
  });

  it('goes to a screen with G then a letter, but not while typing', async () => {
    await render();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'g' }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'p' }));
    expect(navigate).toHaveBeenCalledWith(['/app/projects']);
    navigate.mockClear();
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'g', bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', bubbles: true }));
    expect(navigate).not.toHaveBeenCalled();
    input.remove();
  });
});

describe('shell helpers', () => {
  it('reads the location from the address', () => {
    expect(parseLocation('/app/projects')).toEqual({ projectId: null, screen: 'projects', itemId: null });
    expect(parseLocation('/app/projects/p1/modules/m2?x=1')).toEqual({
      projectId: 'p1',
      screen: 'modules',
      itemId: 'm2',
    });
    expect(parseLocation('/app/projects/p1')).toEqual({ projectId: 'p1', screen: 'overview', itemId: null });
    expect(parseLocation('/app/admin/audit').screen).toBe('audit');
    expect(parseLocation('/').screen).toBeNull();
  });

  it('makes initials from a display name', () => {
    expect(initials('Ari Architect')).toBe('AA');
    expect(initials('vera')).toBe('V');
  });

  it('scores palette matches: contiguous first, then in order, else none', () => {
    expect(score('rate', 'RATECALC')).toBeGreaterThan(score('rclc', 'RATECALC'));
    expect(score('rclc', 'RATECALC')).toBeGreaterThan(0);
    expect(score('xyz', 'RATECALC')).toBe(0);
    expect(score('', 'anything')).toBe(1);
  });
});

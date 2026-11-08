import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeService } from './theme.service';

function mockSystemPreference(dark: boolean): void {
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: dark, media: query }));
}

describe('ThemeService', () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset['theme'];
    TestBed.configureTestingModule({});
  });

  afterEach(() => vi.unstubAllGlobals());

  it('follows the system preference by default', () => {
    mockSystemPreference(true);
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    expect(theme.theme()).toBe('dark');
    expect(document.documentElement.dataset['theme']).toBe('dark');
  });

  it('prefers a stored choice over the system preference', () => {
    mockSystemPreference(true);
    localStorage.setItem('offshoot-theme', 'light');
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    expect(theme.theme()).toBe('light');
  });

  it('ignores a stored value it does not recognize', () => {
    mockSystemPreference(false);
    localStorage.setItem('offshoot-theme', 'neon');
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    expect(theme.theme()).toBe('light');
  });

  it('toggles, applies and remembers the theme', () => {
    mockSystemPreference(false);
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    theme.toggle();
    expect(theme.theme()).toBe('dark');
    expect(document.documentElement.dataset['theme']).toBe('dark');
    expect(localStorage.getItem('offshoot-theme')).toBe('dark');
    theme.toggle();
    expect(document.documentElement.dataset['theme']).toBe('light');
  });

  it('still works when storage is blocked', () => {
    mockSystemPreference(false);
    const blocked = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    expect(() => theme.toggle()).not.toThrow();
    expect(theme.theme()).toBe('dark');
    blocked.mockRestore();
  });
});

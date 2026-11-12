import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeService } from './theme.service';

/** The system's colour scheme; `null` means it states no preference. */
function mockSystemPreference(scheme: 'light' | 'dark' | null): void {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: scheme !== null && query.includes(scheme),
    media: query,
  }));
}

describe('ThemeService', () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset['theme'];
    TestBed.configureTestingModule({});
  });

  afterEach(() => vi.unstubAllGlobals());

  it('is dark first: dark when the system states no preference', () => {
    mockSystemPreference(null);
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    expect(theme.theme()).toBe('dark');
    expect(document.documentElement.dataset['theme']).toBe('dark');
  });

  it('follows a system that asks for light', () => {
    mockSystemPreference('light');
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    expect(theme.theme()).toBe('light');
  });

  it('prefers a stored choice over the system preference', () => {
    mockSystemPreference('dark');
    localStorage.setItem('offshoot-theme', 'light');
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    expect(theme.theme()).toBe('light');
  });

  it('ignores a stored value it does not recognize', () => {
    mockSystemPreference('light');
    localStorage.setItem('offshoot-theme', 'neon');
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    expect(theme.theme()).toBe('light');
  });

  it('toggles, applies and remembers the theme, and updates the theme colour', () => {
    mockSystemPreference('light');
    const meta = document.createElement('meta');
    meta.name = 'theme-color';
    document.head.appendChild(meta);
    const theme = TestBed.inject(ThemeService);
    theme.initialize();
    theme.toggle();
    expect(theme.theme()).toBe('dark');
    expect(document.documentElement.dataset['theme']).toBe('dark');
    expect(localStorage.getItem('offshoot-theme')).toBe('dark');
    expect(meta.content).toBe('#08090c');
    theme.toggle();
    expect(document.documentElement.dataset['theme']).toBe('light');
    expect(meta.content).toBe('#fafafb');
    meta.remove();
  });

  it('still works when storage is blocked', () => {
    mockSystemPreference('light');
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

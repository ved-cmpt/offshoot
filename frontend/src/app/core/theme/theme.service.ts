import { DOCUMENT, Injectable, inject, signal } from '@angular/core';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'offshoot-theme';
const THEME_COLOR: Record<Theme, string> = { dark: '#08090c', light: '#fafafb' };

/**
 * Dark-first (ADR-051): dark unless the visitor chose light, or their system asks for light and
 * they have not chosen. The choice is kept in local storage when storage is allowed.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly document = inject(DOCUMENT);
  private readonly current = signal<Theme>('dark');

  readonly theme = this.current.asReadonly();

  initialize(): void {
    this.apply(this.readStored() ?? (this.prefersLight() ? 'light' : 'dark'));
  }

  toggle(): void {
    this.set(this.current() === 'dark' ? 'light' : 'dark');
  }

  set(theme: Theme): void {
    this.apply(theme);
    try {
      this.document.defaultView?.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Storage can be blocked. The choice still holds for this page.
    }
  }

  private apply(theme: Theme): void {
    this.current.set(theme);
    this.document.documentElement.dataset['theme'] = theme;
    this.document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', THEME_COLOR[theme]);
  }

  private readStored(): Theme | null {
    try {
      const stored = this.document.defaultView?.localStorage.getItem(STORAGE_KEY);
      return stored === 'light' || stored === 'dark' ? stored : null;
    } catch {
      return null;
    }
  }

  private prefersLight(): boolean {
    return (
      this.document.defaultView?.matchMedia?.('(prefers-color-scheme: light)').matches ?? false
    );
  }
}

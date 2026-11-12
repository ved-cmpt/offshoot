import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { catchError, of } from 'rxjs';

import { AuthService } from '../../core/auth/auth.service';
import { ConfigService } from '../../core/config/config.service';
import { ThemeService } from '../../core/theme/theme.service';

@Component({
  selector: 'app-shell',
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './shell.html',
  styleUrl: './shell.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Shell {
  private readonly auth = inject(AuthService);
  private readonly configService = inject(ConfigService);
  private readonly router = inject(Router);
  private readonly themeService = inject(ThemeService);

  private readonly config = toSignal(this.configService.load().pipe(catchError(() => of(null))));

  protected readonly user = this.auth.user;
  protected readonly theme = this.themeService.theme;
  protected readonly isSigningOut = signal(false);
  protected readonly demoMode = computed(() => this.config()?.demo_mode ?? false);
  protected readonly executionOff = computed(() => this.config()?.execution_enabled === false);
  protected readonly resetHours = computed(() => this.config()?.demo_reset_hours ?? 0);
  protected readonly canReadAudit = computed(() => {
    const role = this.user()?.role;
    return role === 'ARCHITECT' || role === 'ADMIN';
  });
  protected readonly themeToggleLabel = computed(() =>
    this.theme() === 'dark' ? 'Use light theme' : 'Use dark theme',
  );

  protected toggleTheme(): void {
    this.themeService.toggle();
  }

  protected signOut(): void {
    this.isSigningOut.set(true);
    // The local session ends either way, so the outcome of the request doesn't change where we go.
    const toLogin = () => void this.router.navigate(['/app/login']);
    this.auth.logout().subscribe({ next: toLogin, error: toLogin });
  }
}

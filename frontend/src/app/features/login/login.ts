import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { describeError } from '../../core/api/api-error';
import { AuthService, Role } from '../../core/auth/auth.service';
import { ConfigService, DemoAccount, PublicConfig } from '../../core/config/config.service';
import { Icon } from '../../shared/icon/icon';

export const ROLE_SUMMARIES: Record<Role, string> = {
  VIEWER: 'Browse projects, rules, plans and reports. Read-only.',
  ENGINEER: 'Run analysis, extraction, migration and verification.',
  ARCHITECT: 'Everything an engineer can do, plus approvals and promotion.',
  ADMIN: 'Manage users and demo resets.',
};

type ConfigState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; config: PublicConfig };

@Component({
  selector: 'app-login',
  imports: [Icon, ReactiveFormsModule, RouterLink],
  templateUrl: './login.html',
  styleUrl: './login.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Login implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly configService = inject(ConfigService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly roleSummaries = ROLE_SUMMARIES;
  protected readonly configState = signal<ConfigState>({ kind: 'loading' });
  protected readonly isSubmitting = signal(false);
  protected readonly errorMessage = signal<string | null>(null);
  protected readonly demoMode = computed(() => {
    const state = this.configState();
    return state.kind === 'ready' && state.config.demo_mode;
  });

  protected readonly form = new FormGroup({
    username: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    password: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
  });

  ngOnInit(): void {
    this.loadConfig();
  }

  protected loadConfig(): void {
    this.configState.set({ kind: 'loading' });
    this.configService.load().subscribe({
      next: (config) => this.configState.set({ kind: 'ready', config }),
      error: (error: unknown) => {
        this.configService.reset();
        this.configState.set({ kind: 'error', message: describeError(error) });
      },
    });
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const { username, password } = this.form.getRawValue();
    this.signIn(username, password);
  }

  protected useAccount(account: DemoAccount): void {
    this.form.setValue({ username: account.username, password: account.password });
    this.signIn(account.username, account.password);
  }

  private signIn(username: string, password: string): void {
    this.isSubmitting.set(true);
    this.errorMessage.set(null);
    this.auth.login(username, password).subscribe({
      next: () => {
        // Only a path inside the app, never another site.
        const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl');
        const safe = returnUrl && returnUrl.startsWith('/app/') ? returnUrl : '/app/projects';
        void this.router.navigateByUrl(safe);
      },
      error: (error: unknown) => {
        this.isSubmitting.set(false);
        this.errorMessage.set(describeError(error));
      },
    });
  }
}

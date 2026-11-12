import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription, forkJoin } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { Skeleton } from '../../shared/ui/ui';
import { AuthService } from '../../core/auth/auth.service';
import {
  MODULE_STATE_TEXT,
  ModernizationService,
  ModuleSummary,
  Plan,
  PlanView,
} from '../modernization/modernization.service';
import { JobProgress } from '../workbench/job-progress';
import { Job } from '../workbench/workbench.service';

type ViewState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; view: PlanView; modules: ModuleSummary[] };

const SEVERITY_TEXT = { HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' } as const;
const PLAN_STATE_TEXT = {
  PROPOSED: 'Proposed, awaiting an architect',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
} as const;

/** The modernization plan: service map, ordered timeline, risks, estimate and the decision. */
@Component({
  selector: 'app-plan',
  imports: [DatePipe, JobProgress, RouterLink, Skeleton],
  templateUrl: './plan.html',
  styleUrl: './plan.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PlanPage implements OnInit {
  private readonly api = inject(ModernizationService);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private loading: Subscription | null = null;

  protected readonly projectId = signal('');
  protected readonly state = signal<ViewState>({ kind: 'loading' });
  protected readonly job = signal<Job | null>(null);
  protected readonly busy = signal(false);
  protected readonly actionError = signal<string | null>(null);
  protected readonly rejecting = signal(false);
  protected readonly reason = signal('');

  protected readonly severityText = SEVERITY_TEXT;
  protected readonly planStateText = PLAN_STATE_TEXT;
  protected readonly moduleStateText = MODULE_STATE_TEXT;
  protected readonly canPropose = computed(() => {
    const role = this.auth.user()?.role;
    return role === 'ENGINEER' || role === 'ARCHITECT';
  });
  protected readonly isArchitect = computed(() => this.auth.user()?.role === 'ARCHITECT');
  protected readonly plan = computed(() => {
    const state = this.state();
    return state.kind === 'ready' ? state.view.plan : null;
  });
  protected readonly modulesByProgram = computed(() => {
    const state = this.state();
    const found = new Map<string, ModuleSummary>();
    if (state.kind === 'ready') {
      for (const module of state.modules) {
        found.set(module.program, module);
      }
    }
    return found;
  });

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.projectId.set(params.get('id') ?? '');
      this.load();
    });
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    this.loading?.unsubscribe();
    this.loading = forkJoin({
      view: this.api.plan(this.projectId()),
      modules: this.api.modules(this.projectId()),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ view, modules }) => this.state.set({ kind: 'ready', view, modules }),
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }

  protected propose(): void {
    this.busy.set(true);
    this.actionError.set(null);
    this.api
      .proposePlan(this.projectId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          this.busy.set(false);
          this.job.set(job);
        },
        error: (error: unknown) => {
          this.busy.set(false);
          this.actionError.set(describeError(error));
        },
      });
  }

  protected jobFinished(job: Job): void {
    if (job.status === 'SUCCEEDED') {
      this.load();
    }
  }

  protected decide(plan: Plan, decision: 'APPROVED' | 'REJECTED'): void {
    const reason = this.reason().trim();
    if (decision === 'REJECTED' && !reason) {
      this.actionError.set('A rejection needs a reason.');
      return;
    }
    this.busy.set(true);
    this.actionError.set(null);
    this.api
      .decidePlan(this.projectId(), plan, decision, reason || null)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.rejecting.set(false);
          this.reason.set('');
          this.load();
        },
        error: (error: unknown) => {
          this.busy.set(false);
          this.actionError.set(describeError(error));
          // A stale or decided plan: show what is there now.
          if (error instanceof HttpErrorResponse && error.status === 409) {
            this.load();
          }
        },
      });
  }

  protected servicePrograms(plan: Plan, service: string): string[] {
    return plan.order.filter((step) => step.service === service).map((step) => step.program);
  }
}

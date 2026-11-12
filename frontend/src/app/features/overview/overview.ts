import { DatePipe, DecimalPipe } from '@angular/common';
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

import { describeError } from '../../core/api/api-error';
import { Icon } from '../../shared/icon/icon';
import { IconName } from '../../shared/icon/icons';
import { EmptyState, Skeleton } from '../../shared/ui/ui';
import {
  Dashboard,
  MODULE_STATE_TEXT,
  ModuleState,
  PromotionService,
} from '../modernization/modernization.service';

type ViewState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; data: Dashboard };

const STATE_ORDER: ModuleState[] = [
  'APPROVED',
  'VERIFIED',
  'VERIFYING',
  'MIGRATING',
  'BLOCKED',
  'BUILD_FAILED',
  'REJECTED',
  'PENDING',
];
const MODE_TEXT = { LEGACY: 'Legacy', SHADOW: 'Shadow', MODERN: 'Modern' } as const;

export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

/** Status colours carry meaning only, and always come with a word and an icon. */
export const STATE_TONE: Record<ModuleState, Tone> = {
  APPROVED: 'good',
  VERIFIED: 'good',
  VERIFYING: 'warn',
  MIGRATING: 'warn',
  BLOCKED: 'bad',
  BUILD_FAILED: 'bad',
  REJECTED: 'bad',
  PENDING: 'neutral',
};
const TONE_ICON: Record<Tone, IconName> = {
  good: 'circle-check',
  warn: 'loader-circle',
  bad: 'octagon-x',
  neutral: 'circle-dot',
};
const BADGE_TONE: Record<Tone, string> = { good: 'ok', warn: 'warn', bad: 'danger', neutral: 'neutral' };

export function outcomeTone(outcome: string): Tone {
  const value = outcome.toUpperCase();
  if (['SUCCEEDED', 'APPROVED', 'VERIFIED', 'PASSED'].includes(value)) {
    return 'good';
  }
  if (['FAILED', 'REJECTED', 'BLOCKED'].includes(value)) {
    return 'bad';
  }
  return value === 'RUNNING' || value === 'QUEUED' ? 'warn' : 'neutral';
}

/** The project at a glance. Every number is read from stored runs and decisions. */
@Component({
  selector: 'app-overview',
  imports: [DatePipe, DecimalPipe, EmptyState, Icon, RouterLink, Skeleton],
  templateUrl: './overview.html',
  styleUrl: './overview.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Overview implements OnInit {
  private readonly api = inject(PromotionService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly projectId = signal('');
  protected readonly state = signal<ViewState>({ kind: 'loading' });
  protected readonly stateText = MODULE_STATE_TEXT;
  protected readonly modeText = MODE_TEXT;
  protected readonly modeOrder = ['LEGACY', 'SHADOW', 'MODERN'] as const;
  protected readonly tone = STATE_TONE;
  protected readonly toneIcon = TONE_ICON;
  protected readonly badgeTone = BADGE_TONE;
  protected readonly outcomeTone = outcomeTone;
  protected readonly measured = computed(() => {
    const state = this.state();
    return state.kind === 'ready' ? state.data.modules.filter((row) => row.coverage_pct !== null) : [];
  });
  protected readonly stateSummary = computed(() =>
    'Modules by state: ' + this.states().map((entry) => `${MODULE_STATE_TEXT[entry.name]} ${entry.count}`).join(', '),
  );
  protected readonly qualitySummary = computed(
    () =>
      'Coverage and mutation score by module: ' +
      this.measured()
        .map(
          (row) =>
            `${row.program} coverage ${row.coverage_pct}%, mutation ${row.mutation_score === null ? 'not run' : row.mutation_score + '%'}`,
        )
        .join('; '),
  );
  protected readonly states = computed(() => {
    const state = this.state();
    if (state.kind !== 'ready') {
      return [];
    }
    return STATE_ORDER.filter((name) => state.data.modules_by_state[name]).map((name) => ({
      name,
      count: state.data.modules_by_state[name] ?? 0,
    }));
  });

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.projectId.set(params.get('id') ?? '');
      this.load();
    });
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    this.api
      .dashboard(this.projectId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => this.state.set({ kind: 'ready', data }),
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }
}

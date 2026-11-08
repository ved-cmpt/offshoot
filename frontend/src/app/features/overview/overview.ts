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

/** The project at a glance. Every number is read from stored runs and decisions. */
@Component({
  selector: 'app-overview',
  imports: [DatePipe, DecimalPipe, RouterLink],
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

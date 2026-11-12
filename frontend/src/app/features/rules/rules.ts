import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Injector,
  OnInit,
  afterNextRender,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { AuthService } from '../../core/auth/auth.service';
import { JobProgress } from '../workbench/job-progress';
import { Job, Rule, RulePage, WorkbenchService } from '../workbench/workbench.service';
import { Icon } from '../../shared/icon/icon';
import { Skeleton } from '../../shared/ui/ui';
import { RuleCard } from './rule-card';

type ListState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; page: RulePage };

const PAGE_SIZE = 50;

@Component({
  selector: 'app-rules',
  imports: [Icon, JobProgress, RouterLink, RuleCard, Skeleton],
  templateUrl: './rules.html',
  styleUrl: './rules.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Rules implements OnInit {
  private readonly workbench = inject(WorkbenchService);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private loading: Subscription | null = null;
  private readonly injector = inject(Injector);
  /** A rule to bring into view once the list has loaded (from the palette or a link). */
  private focusRule: string | null = null;

  protected readonly projectId = signal('');
  protected readonly state = signal<ListState>({ kind: 'loading' });
  protected readonly program = signal('');
  protected readonly ruleState = signal('');
  protected readonly flag = signal('');
  protected readonly offset = signal(0);
  protected readonly view = signal<'cards' | 'table'>('cards');
  protected readonly stateOrder = ['VERIFIED', 'PROPOSED', 'EDITED', 'REJECTED'] as const;

  protected readonly analyzedPrograms = signal<string[] | null>(null);
  protected readonly extractProgram = signal('');
  protected readonly job = signal<Job | null>(null);
  protected readonly starting = signal(false);
  protected readonly startError = signal<string | null>(null);

  protected readonly pageSize = PAGE_SIZE;
  protected readonly canExtract = computed(() => {
    const role = this.auth.user()?.role;
    return role === 'ENGINEER' || role === 'ARCHITECT';
  });
  protected readonly isArchitect = computed(() => this.auth.user()?.role === 'ARCHITECT');
  protected readonly hasFilters = computed(
    () => !!(this.program() || this.ruleState() || this.flag()),
  );
  protected readonly countsText = computed(() => {
    const state = this.state();
    if (state.kind !== 'ready') {
      return '';
    }
    const counts = state.page.counts;
    return (
      `${counts.VERIFIED ?? 0} verified, ${counts.PROPOSED ?? 0} proposed, ` +
      `${counts.EDITED ?? 0} edited, ${counts.REJECTED ?? 0} rejected`
    );
  });

  ngOnInit(): void {
    // Filters can come from the address, as links from the landing page and the palette do.
    const query = this.route.snapshot?.queryParamMap;
    if (query) {
      this.program.set(query.get('program') ?? '');
      this.ruleState.set(query.get('state') ?? '');
      this.flag.set(query.get('flag') ?? '');
      this.focusRule = query.get('rule');
    }
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.projectId.set(params.get('id') ?? '');
      this.load();
      this.loadPrograms();
    });
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    // Only the latest request counts: a slow reply must not replace newer filters.
    this.loading?.unsubscribe();
    this.loading = this.workbench
      .rules(this.projectId(), {
        program: this.program(),
        state: this.ruleState(),
        flag: this.flag(),
        offset: this.offset(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) => {
          this.state.set({ kind: 'ready', page });
          this.revealFocus();
        },
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }

  /** Scroll to the rule named in the address, and outline it. */
  private revealFocus(): void {
    const id = this.focusRule;
    if (!id) {
      return;
    }
    this.focusRule = null;
    this.view.set('cards');
    afterNextRender(
      () => {
        const card = document.getElementById(`rule-${id}`)?.closest('article');
        card?.scrollIntoView?.({ block: 'center' });
        card?.classList.add('card--focus');
      },
      { injector: this.injector },
    );
  }

  /** From the table view to the rule's full card. */
  protected openCard(id: string): void {
    this.focusRule = id;
    this.revealFocus();
  }

  protected setFilter(filter: 'program' | 'ruleState' | 'flag', value: string): void {
    this[filter].set(value);
    this.offset.set(0);
    this.load();
  }

  protected clearFilters(): void {
    this.program.set('');
    this.ruleState.set('');
    this.flag.set('');
    this.offset.set(0);
    this.load();
  }

  protected goTo(offset: number): void {
    this.offset.set(Math.max(0, offset));
    this.load();
  }

  protected extract(): void {
    const program = this.extractProgram();
    if (!program) {
      return;
    }
    this.starting.set(true);
    this.startError.set(null);
    this.workbench
      .startExtraction(this.projectId(), program)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          this.starting.set(false);
          this.job.set(job);
        },
        error: (error: unknown) => {
          this.starting.set(false);
          this.startError.set(describeError(error));
        },
      });
  }

  protected jobFinished(job: Job): void {
    if (job.status === 'SUCCEEDED') {
      this.load();
    }
  }

  protected updateRule(updated: Rule): void {
    this.state.update((state) => {
      if (state.kind !== 'ready') {
        return state;
      }
      const before = state.page.items.find((rule) => rule.id === updated.id);
      const items = state.page.items.map((rule) => (rule.id === updated.id ? updated : rule));
      const counts = { ...state.page.counts };
      if (before && before.state !== updated.state) {
        counts[before.state] = Math.max(0, (counts[before.state] ?? 0) - 1);
        counts[updated.state] = (counts[updated.state] ?? 0) + 1;
      }
      return { kind: 'ready', page: { ...state.page, items, counts } };
    });
  }

  private loadPrograms(): void {
    this.workbench
      .inventory(this.projectId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (inventory) => {
          const names = inventory.programs.map((program) => program.name);
          this.analyzedPrograms.set(names);
          this.extractProgram.set(names[0] ?? '');
        },
        // The list still works without this. Extraction just stays unavailable.
        error: () => this.analyzedPrograms.set([]),
      });
  }
}

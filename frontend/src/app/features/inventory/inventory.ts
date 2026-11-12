import { DecimalPipe } from '@angular/common';
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
import { Subscription } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { AuthService } from '../../core/auth/auth.service';
import { JobProgress } from '../workbench/job-progress';
import {
  Inventory as InventoryData,
  Job,
  LayoutRecord,
  WorkbenchService,
} from '../workbench/workbench.service';
import { Skeleton } from '../../shared/ui/ui';
import { CallGraph } from './call-graph';

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; inventory: InventoryData };

type LayoutState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; records: LayoutRecord[]; total: number };

const SUMMARY_LABELS: [string, string][] = [
  ['programs', 'Programs'],
  ['copybooks', 'Copybooks'],
  ['lines', 'Program lines'],
  ['working_paragraphs', 'Working paragraphs'],
  ['exit_labels', '-EXIT labels'],
  ['performs', 'PERFORMs'],
  ['go_tos', 'GO TOs'],
  ['calls', 'CALLs'],
  ['files', 'Files'],
  ['records', 'Records'],
  ['dead_paragraphs', 'Dead paragraphs'],
  ['obsolete_records', 'Obsolete tables'],
];

@Component({
  selector: 'app-inventory',
  imports: [CallGraph, DecimalPipe, JobProgress, RouterLink, Skeleton],
  templateUrl: './inventory.html',
  styleUrl: './inventory.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Inventory implements OnInit {
  private readonly workbench = inject(WorkbenchService);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private loading: Subscription | null = null;
  private loadingLayouts: Subscription | null = null;

  protected readonly projectId = signal('');
  protected readonly state = signal<LoadState>({ kind: 'loading' });
  protected readonly job = signal<Job | null>(null);
  protected readonly starting = signal(false);
  protected readonly startError = signal<string | null>(null);
  protected readonly layoutProgram = signal<string | null>(null);
  protected readonly layouts = signal<LayoutState>({ kind: 'idle' });

  protected readonly canRun = computed(() => {
    const role = this.auth.user()?.role;
    return role === 'ENGINEER' || role === 'ARCHITECT';
  });
  protected readonly summary = computed(() => {
    const state = this.state();
    if (state.kind !== 'ready') {
      return [];
    }
    return SUMMARY_LABELS.filter(([key]) => key in state.inventory.summary).map(([key, label]) => ({
      label,
      value: state.inventory.summary[key],
    }));
  });
  protected readonly programNames = computed(() => {
    const state = this.state();
    return state.kind === 'ready' ? state.inventory.programs.map((program) => program.name) : [];
  });

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.projectId.set(params.get('id') ?? '');
      this.job.set(null);
      this.load();
    });
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    this.loading?.unsubscribe();
    this.loading = this.workbench
      .inventory(this.projectId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (inventory) => {
          this.state.set({ kind: 'ready', inventory });
          if (inventory.analyzed) {
            this.loadLayouts();
          }
        },
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }

  protected analyze(): void {
    this.starting.set(true);
    this.startError.set(null);
    this.workbench
      .startAnalysis(this.projectId())
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
    if (job.status === 'SUCCEEDED' && !job.deduplicated) {
      this.load();
    }
  }

  protected chooseLayoutProgram(value: string): void {
    this.layoutProgram.set(value || null);
    this.loadLayouts();
  }

  protected loadLayouts(): void {
    this.layouts.set({ kind: 'loading' });
    this.loadingLayouts?.unsubscribe();
    this.loadingLayouts = this.workbench
      .layouts(this.projectId(), this.layoutProgram())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) => this.layouts.set({ kind: 'ready', records: page.items, total: page.total }),
        error: (error: unknown) =>
          this.layouts.set({ kind: 'error', message: describeError(error) }),
      });
  }

  protected showMoreLayouts(): void {
    const current = this.layouts();
    if (current.kind !== 'ready') {
      return;
    }
    this.loadingLayouts?.unsubscribe();
    this.loadingLayouts = this.workbench
      .layouts(this.projectId(), this.layoutProgram(), current.records.length)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) =>
          this.layouts.set({
            kind: 'ready',
            records: [...current.records, ...page.items],
            total: page.total,
          }),
        error: (error: unknown) =>
          this.layouts.set({ kind: 'error', message: describeError(error) }),
      });
  }

  protected query(start: number | null, end: number | null): Record<string, number> {
    return start ? { line: start, end: end ?? start } : {};
  }

  protected indent(level: number): string {
    return `${Math.max(0, Math.floor(level / 5)) * 0.75}rem`;
  }

  protected operations(file: {
    read_in: { paragraph: string }[];
    written_in: { paragraph: string }[];
  }): string {
    const reads = file.read_in.map((item) => `read in ${item.paragraph}`);
    const writes = file.written_in.map((item) => `written in ${item.paragraph}`);
    return [...reads, ...writes].join('; ') || 'not read or written';
  }
}

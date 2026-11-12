import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
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
import { Observable, Subscription, catchError, forkJoin, map, of, switchMap } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { AuthService } from '../../core/auth/auth.service';
import {
  ArtifactDetail,
  ArtifactSummary,
  MODULE_STATE_TEXT,
  ModernizationService,
  ModuleAction,
  ModuleDetail,
  PromotionService,
  RunDetail,
  ShadowView,
  RunSummary,
  describeReason,
} from '../modernization/modernization.service';
import { Token, highlightLines } from '../../shared/code/highlight';
import { Icon } from '../../shared/icon/icon';
import { ToastService } from '../../shared/toast/toast';
import { Skeleton } from '../../shared/ui/ui';
import { ProjectContext } from '../../core/project/project-context';
import { JobProgress } from '../workbench/job-progress';
import { changedLines, removedCount } from './line-diff';
import { Graph, Job, Rule, SourceDetail, WorkbenchService } from '../workbench/workbench.service';

interface Loaded {
  module: ModuleDetail;
  runs: RunSummary[];
  artifacts: ArtifactSummary[];
  source: SourceDetail | null;
  graph: Graph | null;
  rules: Rule[];
}

type ViewState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; data: Loaded };

export type Coverage = 'hit' | 'missed' | null;

export interface CobolLine {
  number: number;
  text: string;
  paragraph: string | null;
  coverage: Coverage;
  tokens?: Token[];
}

export interface CodeLine {
  number: number;
  tokens: Token[];
  changed: boolean;
}

const SOURCE_TONE: Record<string, string> = {
  boundary: 'var(--chart-1)',
  date: 'var(--info)',
  constant: 'var(--chart-2)',
  rule: 'var(--warn)',
  recorded: 'var(--ok)',
  random: 'var(--text-3)',
};

const ACTION_TEXT: Record<ModuleAction, string> = {
  migrate: 'Migrate',
  repair: 'Repair',
  verify: 'Verify again',
  mutate: 'Re-run mutation testing',
};

const SOURCE_TEXT: Record<string, string> = {
  boundary: 'PIC boundaries',
  date: 'Date windows',
  constant: 'Copybook constants',
  rule: 'Rule examples and conditions',
  recorded: 'Recorded BillRite data',
  random: 'Seeded random (Hypothesis)',
};

/** Which paragraph each COBOL line belongs to, and whether the latest run executed it. */
export function coverageLines(
  source: SourceDetail,
  graph: Graph | null,
  hit: string[],
  missed: string[],
): CobolLine[] {
  const paragraphs = (graph?.nodes ?? [])
    .filter((node) => node.kind === 'PARAGRAPH' && node.file_id === source.id && node.start_line)
    .map((node) => ({
      name: node.name,
      start: node.start_line ?? 0,
      end: node.end_line ?? 0,
      exit: node.is_exit_label,
    }));
  const hits = new Set(hit);
  const misses = new Set(missed);
  return source.lines.map((text, index) => {
    const number = index + 1;
    const paragraph =
      paragraphs.find((p) => !p.exit && number >= p.start && number <= p.end) ?? null;
    let coverage: Coverage = null;
    if (paragraph && hits.has(paragraph.name)) {
      coverage = 'hit';
    } else if (paragraph && misses.has(paragraph.name)) {
      coverage = 'missed';
    }
    return { number, text, paragraph: paragraph?.name ?? null, coverage };
  });
}

/** One module: COBOL beside C#, build and tests, verification reports, history and actions. */
@Component({
  selector: 'app-module-workspace',
  imports: [DatePipe, DecimalPipe, Icon, JobProgress, RouterLink, Skeleton],
  templateUrl: './module-workspace.html',
  styleUrl: './module-workspace.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModuleWorkspace implements OnInit {
  private readonly api = inject(ModernizationService);
  private readonly promotion = inject(PromotionService);
  private readonly workbench = inject(WorkbenchService);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toasts = inject(ToastService);
  private readonly context = inject(ProjectContext);
  private loading: Subscription | null = null;
  private previousLoading: Subscription | null = null;
  private runLoading: Subscription | null = null;
  private artifactLoading: Subscription | null = null;
  private readonly handledJobs = new Set<string>();

  protected readonly projectId = signal('');
  protected readonly moduleId = signal('');
  protected readonly state = signal<ViewState>({ kind: 'loading' });
  protected readonly run = signal<RunDetail | null>(null);
  protected readonly runError = signal<string | null>(null);
  protected readonly artifact = signal<ArtifactDetail | null>(null);
  protected readonly artifactError = signal<string | null>(null);
  protected readonly selectedFile = signal(0);
  protected readonly job = signal<Job | null>(null);
  protected readonly busy = signal(false);
  protected readonly actionError = signal<string | null>(null);
  protected readonly exceptionGate = signal<'COVERAGE' | 'MUTATION'>('COVERAGE');
  protected readonly exceptionThreshold = signal('');
  protected readonly exceptionReason = signal('');
  protected readonly rejecting = signal(false);
  protected readonly decisionReason = signal('');
  protected readonly shadowView = signal<ShadowView | null>(null);
  /** The version before the selected one, to show what changed. */
  protected readonly previous = signal<ArtifactDetail | null>(null);
  protected readonly showChanges = signal(true);
  protected readonly sourceTone = SOURCE_TONE;

  protected readonly stateText = MODULE_STATE_TEXT;
  protected readonly actionText = ACTION_TEXT;
  protected readonly sourceText = SOURCE_TEXT;
  protected readonly describeReason = describeReason;

  protected readonly canRun = computed(() => {
    const role = this.auth.user()?.role;
    return role === 'ENGINEER' || role === 'ARCHITECT';
  });
  protected readonly isArchitect = computed(() => this.auth.user()?.role === 'ARCHITECT');
  protected readonly data = computed(() => {
    const state = this.state();
    return state.kind === 'ready' ? state.data : null;
  });
  protected readonly actions = computed<ModuleAction[]>(() => {
    const module = this.data()?.module;
    if (!module || !module.migratable || module.active_job) {
      return [];
    }
    const found: ModuleAction[] = [];
    if (['PENDING', 'BUILD_FAILED', 'BLOCKED', 'REJECTED'].includes(module.state)) {
      found.push('migrate');
    }
    if (
      ['BLOCKED', 'BUILD_FAILED'].includes(module.state) &&
      module.current_artifact &&
      module.repairs_remaining > 0
    ) {
      found.push('repair');
    }
    if (
      module.current_artifact?.build_status === 'BUILT' &&
      ['VERIFIED', 'BLOCKED', 'APPROVED'].includes(module.state)
    ) {
      found.push('verify');
    }
    const run = module.latest_run;
    if (
      run &&
      run.failed === 0 &&
      run.artifact_id === module.current_artifact?.id &&
      module.state !== 'VERIFYING'
    ) {
      found.push('mutate');
    }
    return found;
  });
  protected readonly cobol = computed<CobolLine[]>(() => {
    const data = this.data();
    if (!data?.source) {
      return [];
    }
    const coverage = this.run()?.report?.coverage;
    return coverageLines(data.source, data.graph, coverage?.hit ?? [], coverage?.missed ?? []);
  });
  protected readonly currentFile = computed(
    () => this.artifact()?.file_contents[this.selectedFile()] ?? null,
  );
  protected readonly cobolTokens = computed(() => highlightLines(this.cobol().map((line) => line.text), 'cobol'));
  /** The selected C# file, coloured, with the lines that differ from the previous version. */
  protected readonly csharpLines = computed<CodeLine[]>(() => {
    const file = this.currentFile();
    if (!file) {
      return [];
    }
    const lines = file.content.split('\n');
    const before = this.previous()?.file_contents.find((item) => item.path === file.path);
    const changed =
      before && this.showChanges() ? changedLines(before.content.split('\n'), lines) : lines.map(() => false);
    return highlightLines(lines, 'csharp').map((tokens, index) => ({
      number: index + 1,
      tokens,
      changed: changed[index],
    }));
  });
  protected readonly diffStats = computed(() => {
    const file = this.currentFile();
    const before = this.previous()?.file_contents.find((item) => item.path === file?.path);
    if (!file || !before) {
      return null;
    }
    const after = file.content.split('\n');
    const old = before.content.split('\n');
    return {
      added: changedLines(old, after).filter(Boolean).length,
      removed: removedCount(old, after),
      version: this.previous()!.version,
    };
  });
  /** The share of each case source, for the stacked bar. */
  protected readonly sourceShares = computed(() => {
    const entries = this.sources();
    const total = entries.reduce((sum, [, count]) => sum + count, 0) || 1;
    return entries.map(([name, count]) => ({ name, count, share: (count / total) * 100 }));
  });
  /** Paragraphs the latest full run reached and missed, for the coverage map. */
  protected readonly coverageMap = computed(() => {
    const coverage = this.run()?.report?.coverage;
    if (!coverage) {
      return [];
    }
    return [
      ...coverage.hit.map((name) => ({ name, hit: true })),
      ...coverage.missed.map((name) => ({ name, hit: false })),
    ].sort((a, b) => a.name.localeCompare(b.name));
  });
  protected readonly cells = computed(() => {
    const run = this.run();
    if (!run || run.kind !== 'FULL' || !run.cases) {
      return [];
    }
    const failing = new Set((run.report?.mismatches ?? []).map((item) => item.case - 1));
    const extra = Math.max(0, run.failed - failing.size);
    return Array.from({ length: run.cases }, (_, index) => failing.has(index) || index >= run.cases - extra);
  });
  protected readonly coveredRuleIds = computed(() => new Set(this.artifact()?.rule_ids ?? []));
  protected readonly exercisedRuleIds = computed(
    () =>
      new Map((this.run()?.report?.rules?.exercised ?? []).map((rule) => [rule.id, rule.cases])),
  );
  protected readonly sources = computed(() => Object.entries(this.run()?.report?.by_source ?? {}));
  protected readonly mismatchedFields = computed(() =>
    Object.entries(this.run()?.report?.mismatched_fields ?? {}),
  );

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.projectId.set(params.get('id') ?? '');
      this.moduleId.set(params.get('mid') ?? '');
      this.load();
    });
  }

  /**
   * Load everything. A refresh after an action keeps the current page on screen until the new
   * data arrives, so the job panel is not destroyed and re-created while it reports progress.
   */
  protected load(refresh = false): void {
    if (!refresh || this.state().kind !== 'ready') {
      this.state.set({ kind: 'loading' });
    }
    this.loading?.unsubscribe();
    const moduleId = this.moduleId();
    this.loading = this.api
      .moduleDetail(moduleId)
      .pipe(
        switchMap((module) =>
          forkJoin({
            module: of(module),
            runs: this.api.runs(moduleId),
            artifacts: this.api.artifacts(moduleId),
            source: this.cobolSource(module.program),
            graph: this.workbench
              .graph(this.projectId(), module.program)
              .pipe(catchError(() => of(null))),
            rules: this.workbench
              .rules(this.projectId(), { program: module.program })
              .pipe(map((page) => page.items)),
          }),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (data) => {
          this.state.set({ kind: 'ready', data });
          if (data.module.active_job && !this.job()) {
            this.job.set(data.module.active_job);
          }
          this.loadShadow(data.module);
          const latest = data.runs[0];
          if (latest) {
            this.selectRun(latest.id);
          } else {
            this.run.set(null);
          }
          const version = data.module.current_artifact?.version ?? data.artifacts[0]?.version;
          if (version) {
            this.selectArtifact(version);
          } else {
            this.artifact.set(null);
          }
        },
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }

  private cobolSource(program: string): Observable<SourceDetail | null> {
    return this.workbench.sources(this.projectId()).pipe(
      switchMap((list) => {
        const file = list.items.find(
          (item) => item.kind === 'PROGRAM' && item.name === `${program}.cbl`,
        );
        return file ? this.workbench.source(this.projectId(), file.id) : of(null);
      }),
      catchError(() => of(null)),
    );
  }

  private loadShadow(module: ModuleDetail): void {
    if (module.facade_mode === 'LEGACY' && !module.shadow.since) {
      this.shadowView.set(null);
      return;
    }
    this.promotion
      .shadow(module.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (view) => this.shadowView.set(view),
        error: () => this.shadowView.set(null),
      });
  }

  protected decide(module: ModuleDetail, decision: 'APPROVED' | 'REJECTED'): void {
    const reason = this.decisionReason().trim();
    if (decision === 'REJECTED' && !reason) {
      this.actionError.set('A rejection needs a reason.');
      return;
    }
    this.runPromotion(this.promotion.decide(module, decision, reason || null));
  }

  protected setMode(module: ModuleDetail, mode: 'LEGACY' | 'SHADOW' | 'MODERN'): void {
    this.runPromotion(this.promotion.setMode(module, mode, null));
  }

  protected replay(module: ModuleDetail): void {
    this.busy.set(true);
    this.actionError.set(null);
    this.promotion
      .replay(module.id)
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

  private runPromotion(request: Observable<ModuleDetail>): void {
    this.busy.set(true);
    this.actionError.set(null);
    request.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (module) => {
        this.busy.set(false);
        this.rejecting.set(false);
        this.decisionReason.set('');
        this.context.invalidate();
        this.toasts.ok(`${module.program}: ${MODULE_STATE_TEXT[module.state].toLowerCase()}`, `Routing ${module.facade_mode.toLowerCase()}.`);
        this.load(true);
      },
      error: (error: unknown) => {
        this.busy.set(false);
        this.actionError.set(describeError(error));
        if (error instanceof HttpErrorResponse && error.status === 409) {
          this.load(true);
        }
      },
    });
  }

  protected selectRun(runId: string): void {
    this.runError.set(null);
    this.runLoading?.unsubscribe();
    this.runLoading = this.api
      .run(this.moduleId(), runId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (run) => this.run.set(run),
        error: (error: unknown) => this.runError.set(describeError(error)),
      });
  }

  protected selectArtifact(version: number): void {
    this.artifactError.set(null);
    this.artifactLoading?.unsubscribe();
    this.artifactLoading = this.api
      .artifact(this.moduleId(), version)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (artifact) => {
          this.artifact.set(artifact);
          this.selectedFile.set(0);
          this.loadPrevious(artifact);
        },
        error: (error: unknown) => this.artifactError.set(describeError(error)),
      });
  }

  /** The version before this one, so the code view can mark what changed. */
  private loadPrevious(artifact: ArtifactDetail): void {
    this.previousLoading?.unsubscribe();
    this.previous.set(null);
    if (artifact.version <= 1) {
      return;
    }
    this.previousLoading = this.api
      .artifact(this.moduleId(), artifact.version - 1)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (before) => {
          this.previous.set(before);
          // Open the first file the new version changed: that is what a reviewer wants to see.
          const changed = artifact.file_contents.findIndex(
            (file) => before.file_contents.find((old) => old.path === file.path)?.content !== file.content,
          );
          if (changed >= 0 && this.artifact()?.id === artifact.id) {
            this.selectedFile.set(changed);
          }
        },
        error: () => this.previous.set(null),
      });
  }

  protected start(action: ModuleAction): void {
    this.busy.set(true);
    this.actionError.set(null);
    this.api
      .start(this.moduleId(), action)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          this.busy.set(false);
          this.job.set(job);
        },
        error: (error: unknown) => {
          this.busy.set(false);
          this.actionError.set(describeError(error));
          if (error instanceof HttpErrorResponse && error.status === 409) {
            this.load(true);
          }
        },
      });
  }

  protected jobFinished(job: Job): void {
    // A progress panel created again for an already finished job reports it again. Act once.
    if (this.handledJobs.has(job.id)) {
      return;
    }
    this.handledJobs.add(job.id);
    const verifyJob = job.metrics['verify_job_id'];
    if (job.status === 'SUCCEEDED' && typeof verifyJob === 'string') {
      // A migration or repair queues its verification. Follow that job next.
      this.workbench
        .job(verifyJob)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({ next: (next) => this.job.set(next), error: () => this.load(true) });
      this.load(true);
      return;
    }
    this.load(true);
  }

  protected addException(module: ModuleDetail): void {
    const threshold = Number(this.exceptionThreshold());
    const reason = this.exceptionReason().trim();
    if (!Number.isFinite(threshold) || threshold < 0 || threshold > 100 || !reason) {
      this.actionError.set('Give a threshold from 0 to 100 and a reason.');
      return;
    }
    this.busy.set(true);
    this.actionError.set(null);
    this.api
      .addGateException(module, this.exceptionGate(), threshold, reason)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.exceptionReason.set('');
          this.exceptionThreshold.set('');
          this.load(true);
        },
        error: (error: unknown) => {
          this.busy.set(false);
          this.actionError.set(describeError(error));
        },
      });
  }

  protected jobLabel(kind: string): string {
    const labels: Record<string, string> = {
      VERIFY: 'Verification',
      REPAIR: 'Repair',
      MUTATE: 'Mutation testing',
      SHADOW: 'Shadow replay',
    };
    return labels[kind] ?? 'Migration';
  }

  protected formatValue(value: number | null, unit: string): string {
    if (value === null || value === undefined) {
      return 'not measured';
    }
    return unit.startsWith('%') ? `${value}${unit === '%' ? '%' : ' ' + unit}` : `${value} ${unit}`;
  }
}

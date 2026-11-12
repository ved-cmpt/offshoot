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
import { Subscription, combineLatest } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { Token, highlightLines, languageOf } from '../../shared/code/highlight';
import { Icon } from '../../shared/icon/icon';
import { Skeleton } from '../../shared/ui/ui';
import {
  RuleSpanHit,
  SourceDetail,
  SourceSummary,
  WorkbenchService,
} from '../workbench/workbench.service';

type ViewState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; source: SourceDetail };

interface Row {
  number: number;
  text: string;
  tokens: Token[];
  cited: number;
  selected: boolean;
  copyName: string | null;
  copyFile: string | null;
}

/** Source with line numbers, rule spans and links to copybooks. Plain text only, never parsed as HTML. */
@Component({
  selector: 'app-source-viewer',
  imports: [Icon, RouterLink, Skeleton],
  templateUrl: './source-viewer.html',
  styleUrl: './source-viewer.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SourceViewer implements OnInit {
  private readonly workbench = inject(WorkbenchService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);
  private loading: Subscription | null = null;

  protected readonly projectId = signal('');
  protected readonly fileId = signal('');
  protected readonly state = signal<ViewState>({ kind: 'loading' });
  protected readonly files = signal<SourceSummary[]>([]);
  protected readonly range = signal<{ start: number; end: number } | null>(null);

  protected readonly rows = computed<Row[]>(() => {
    const state = this.state();
    if (state.kind !== 'ready') {
      return [];
    }
    const range = this.range();
    const links = new Map(state.source.copy_links.map((link) => [link.line, link]));
    const tokens = highlightLines(state.source.lines, languageOf(state.source.name));
    return state.source.lines.map((text, index) => {
      const number = index + 1;
      const link = links.get(number);
      return {
        number,
        text,
        tokens: tokens[index],
        cited: state.source.rule_spans.filter(
          (span) => span.start_line <= number && number <= span.end_line,
        ).length,
        selected: range !== null && range.start <= number && number <= range.end,
        copyName: link?.name ?? null,
        copyFile: link?.file_id ?? null,
      };
    });
  });

  ngOnInit(): void {
    combineLatest([this.route.paramMap, this.route.queryParamMap])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(([params, query]) => {
        const projectId = params.get('id') ?? '';
        const fileId = params.get('file') ?? '';
        const start = Number(query.get('line'));
        const end = Number(query.get('end'));
        this.range.set(start > 0 ? { start, end: end >= start ? end : start } : null);
        const changed = fileId !== this.fileId() || projectId !== this.projectId();
        this.projectId.set(projectId);
        this.fileId.set(fileId);
        if (changed) {
          this.load();
          this.loadFiles();
        } else {
          this.scrollToRange();
        }
      });
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    // Only the latest request counts, and a reply after leaving the page must not touch it.
    this.loading?.unsubscribe();
    this.loading = this.workbench
      .source(this.projectId(), this.fileId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (source) => {
          this.state.set({ kind: 'ready', source });
          this.scrollToRange();
        },
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }

  protected spanQuery(span: RuleSpanHit): Record<string, number> {
    return { line: span.start_line, end: span.end_line };
  }

  private loadFiles(): void {
    this.workbench
      .sources(this.projectId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) => this.files.set(page.items),
        // The file list is a convenience. The source itself still shows without it.
        error: () => this.files.set([]),
      });
  }

  private scrollToRange(): void {
    const range = this.range();
    if (!range) {
      return;
    }
    afterNextRender(
      () => {
        const row = document.getElementById(`L${range.start}`);
        row?.scrollIntoView?.({ block: 'center' });
      },
      { injector: this.injector },
    );
  }
}

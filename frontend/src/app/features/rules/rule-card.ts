import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { describeError } from '../../core/api/api-error';
import { AuthService } from '../../core/auth/auth.service';
import {
  Rule,
  RuleEdit,
  RuleExample,
  RuleSpan,
  WorkbenchService,
} from '../workbench/workbench.service';

type Mode = 'view' | 'edit' | 'reject';

const STATE_LABELS: Record<Rule['state'], string> = {
  PROPOSED: 'Proposed by the agent',
  EDITED: 'Edited, awaiting a decision',
  VERIFIED: 'Verified',
  REJECTED: 'Rejected',
};

const FLAG_LABELS: Record<string, string> = {
  SPAN_INVALID: 'Source lines invalid',
  NAMES_NOT_FOUND: 'Data names not found',
  LOW_CONFIDENCE: 'Low confidence',
};

const SPAN_PATTERN = /^\s*([^\s:]+):(\d+)(?:-(\d+))?\s*$/;

function toLines(values: string[]): string {
  return values.join('\n');
}

function fromLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

export function formatSpan(span: Pick<RuleSpan, 'file' | 'start_line' | 'end_line'>): string {
  return span.start_line === span.end_line
    ? `${span.file}:${span.start_line}`
    : `${span.file}:${span.start_line}-${span.end_line}`;
}

/** Parse "FILE.cbl:10-20" lines. Returns null when any line does not fit. */
export function parseSpans(text: string): RuleEdit['source_spans'] | null {
  const spans = [];
  for (const line of fromLines(text)) {
    const match = SPAN_PATTERN.exec(line);
    if (!match) {
      return null;
    }
    const start = Number(match[2]);
    spans.push({
      file: match[1],
      start_line: start,
      end_line: match[3] ? Number(match[3]) : start,
    });
  }
  return spans;
}

/** One rule: what it claims, why it is flagged, and the actions this role may take. */
@Component({
  selector: 'app-rule-card',
  imports: [RouterLink],
  templateUrl: './rule-card.html',
  styleUrl: './rule-card.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RuleCard {
  private readonly workbench = inject(WorkbenchService);
  private readonly auth = inject(AuthService);
  private readonly injector = inject(Injector);
  private readonly destroyRef = inject(DestroyRef);

  readonly rule = input.required<Rule>();
  readonly changed = output<Rule>();

  private readonly editTitle = viewChild<ElementRef<HTMLInputElement>>('editTitle');
  private readonly rejectReason = viewChild<ElementRef<HTMLTextAreaElement>>('rejectReason');

  protected readonly mode = signal<Mode>('view');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly notice = signal<string | null>(null);

  protected readonly form = signal({
    title: '',
    statement: '',
    inputs: '',
    outputs: '',
    conditions: '',
    spans: '',
    examples: '',
  });
  protected readonly reason = signal('');

  protected readonly stateLabels = STATE_LABELS;
  protected readonly flagLabels = FLAG_LABELS;

  private readonly role = computed(() => this.auth.user()?.role);
  protected readonly canEdit = computed(() => {
    const role = this.role();
    return (role === 'ENGINEER' || role === 'ARCHITECT') && this.rule().state !== 'REJECTED';
  });
  protected readonly canDecide = computed(() => {
    const state = this.rule().state;
    return this.role() === 'ARCHITECT' && (state === 'PROPOSED' || state === 'EDITED');
  });
  protected readonly confidence = computed(() => {
    const value = this.rule().confidence;
    return value === null ? 'not stated' : `${Math.round(value * 100)}%`;
  });

  protected formatSpan = formatSpan;

  protected spanQuery(span: RuleSpan): Record<string, number> {
    return { line: span.start_line, end: span.end_line };
  }

  protected asJson(value: unknown): string {
    return JSON.stringify(value);
  }

  protected setField(field: keyof ReturnType<typeof this.form>, value: string): void {
    this.form.update((form) => ({ ...form, [field]: value }));
  }

  protected openEdit(): void {
    const rule = this.rule();
    this.form.set({
      title: rule.title,
      statement: rule.statement,
      inputs: toLines(rule.inputs),
      outputs: toLines(rule.outputs),
      conditions: toLines(rule.conditions),
      spans: toLines(rule.spans.map(formatSpan)),
      examples: rule.examples.length ? JSON.stringify(rule.examples, null, 2) : '',
    });
    this.switchMode('edit');
    afterNextRender(() => this.editTitle()?.nativeElement.focus(), { injector: this.injector });
  }

  protected openReject(): void {
    this.reason.set('');
    this.switchMode('reject');
    afterNextRender(() => this.rejectReason()?.nativeElement.focus(), { injector: this.injector });
  }

  protected cancel(): void {
    this.switchMode('view');
  }

  protected verify(): void {
    this.run(() => this.workbench.decideRule(this.rule(), 'VERIFIED', null), 'Verified.');
  }

  protected submitReject(event: Event): void {
    event.preventDefault();
    const reason = this.reason().trim();
    if (!reason) {
      this.error.set('A rejection needs a reason.');
      return;
    }
    this.run(() => this.workbench.decideRule(this.rule(), 'REJECTED', reason), 'Rejected.');
  }

  protected submitEdit(event: Event): void {
    event.preventDefault();
    const form = this.form();
    const spans = parseSpans(form.spans);
    if (!spans || spans.length === 0) {
      this.error.set('Give at least one source span, one per line, like RATECALC.cbl:183-189.');
      return;
    }
    let examples: RuleExample[] = [];
    if (form.examples.trim()) {
      try {
        examples = JSON.parse(form.examples) as RuleExample[];
      } catch {
        this.error.set('The examples are not valid JSON.');
        return;
      }
    }
    const changes: RuleEdit = {
      title: form.title,
      statement: form.statement,
      inputs: fromLines(form.inputs),
      outputs: fromLines(form.outputs),
      conditions: fromLines(form.conditions),
      source_spans: spans,
      examples,
    };
    this.run(() => this.workbench.editRule(this.rule(), changes), 'Saved. The checks ran again.');
  }

  private switchMode(mode: Mode): void {
    this.error.set(null);
    this.notice.set(null);
    this.mode.set(mode);
  }

  private run(action: () => ReturnType<WorkbenchService['editRule']>, success: string): void {
    this.busy.set(true);
    this.error.set(null);
    action()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.busy.set(false);
          this.mode.set('view');
          this.notice.set(success);
          this.changed.emit(updated);
        },
        error: (error: unknown) => {
          this.busy.set(false);
          this.error.set(describeError(error));
          // Someone else changed it: bring in the latest version, and leave any open form.
          if (error instanceof HttpErrorResponse && error.status === 409) {
            this.refresh();
          }
        },
      });
  }

  private refresh(): void {
    this.workbench
      .rule(this.rule().id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (latest) => {
          if (latest.version !== this.rule().version) {
            this.notice.set('The latest version is shown below. Review it before deciding.');
            this.mode.set('view');
          }
          this.changed.emit(latest);
        },
        error: () => undefined,
      });
  }
}

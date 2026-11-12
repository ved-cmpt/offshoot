import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import { CodeView, LineMark } from '../../../shared/code/code-view';
import { Icon } from '../../../shared/icon/icon';
import { IconName } from '../../../shared/icon/icons';
import { Reveal } from '../../../shared/reveal';
import { Excerpt, Snapshot, evaluationRow } from '../landing-data';

export type DemoKey = 'rounding' | 'year-window' | 'rollover' | 'injection';

interface Tab {
  key: DemoKey;
  label: string;
  program: string;
  icon: IconName;
}

export const TABS: Tab[] = [
  { key: 'rounding', label: 'Rounding defect', program: 'RATECALC', icon: 'bug' },
  { key: 'year-window', label: 'Two-digit years', program: 'LATEFEE', icon: 'calendar-clock' },
  { key: 'rollover', label: 'Meter rollover', program: 'MTRVAL', icon: 'gauge' },
  { key: 'injection', label: 'Prompt injection', program: 'RATECALC', icon: 'shield-check' },
];

/** Line marks for an excerpt: every line containing one of `needles` gets `mark`. */
export function marksFor(excerpt: Excerpt, needles: string[], mark: LineMark): Record<number, LineMark> {
  const marks: Record<number, LineMark> = {};
  excerpt.lines.forEach((line, index) => {
    if (needles.some((needle) => line.includes(needle))) {
      marks[excerpt.start + index] = mark;
    }
  });
  return marks;
}

/** A one-line expression-bodied member, split before its arrow. */
export function splitArrow(line: string): string[] {
  const text = line.trim();
  const at = text.indexOf('=>');
  return at < 0 ? [text] : [text.slice(0, at).trimEnd(), `    ${text.slice(at)}`];
}

/** The pivot from RATES.cpy's `RT-CENTURY-PIVOT ... VALUE nn.` line. */
export function pivotOf(excerpt: Excerpt): number | null {
  const match = /VALUE\s+(\d+)/.exec(excerpt.lines.join(' '));
  return match ? Number(match[1]) : null;
}

/** LATEFEE's window, as the COBOL states it: at or above the pivot is 19YY, below is 20YY. */
export function windowYear(yy: number, pivot: number): number {
  return (yy >= pivot ? 1900 : 2000) + yy;
}

@Component({
  selector: 'app-landing-demos',
  imports: [CodeView, Icon, Reveal, RouterLink],
  templateUrl: './demos.html',
  styleUrl: './demos.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingDemos {
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly data = input.required<Snapshot>();

  protected readonly tabs = TABS;
  protected readonly selected = signal<DemoKey>('rounding');

  protected readonly api = computed(() => this.data().api);
  protected readonly repo = computed(() => this.data().repo);
  protected readonly generated = computed(() => this.data().provenance.generated_at.slice(0, 10));

  // --- Rounding.
  protected readonly r = computed(() => this.api().rounding);
  protected readonly math = computed(() => this.repo().rounding_math);
  protected readonly roundingCobol = computed(() => this.repo().rounding_cobol[0]);
  protected readonly roundingMarks = computed(() =>
    marksFor(this.roundingCobol(), ['ROUNDED MEANS HALF-UP', 'COMPUTE RC-OUT-ENERGY ROUNDED'], 'focus'),
  );
  protected readonly csharpFirst = computed(() => {
    const excerpt = this.r().csharp_first;
    const last = excerpt.lines.length - 1;
    return { line: excerpt.lines[last], number: excerpt.start + last, version: excerpt.artifact_version };
  });
  protected readonly csharpRepair = computed(() => {
    const excerpt = this.repo().repair.csharp;
    const last = excerpt.lines.length - 1;
    return { line: excerpt.lines[last], number: excerpt.start + last };
  });
  /** The helper before and after the repair, each split at its arrow so the change is visible. */
  protected readonly csharpLines = computed(() => [
    ...splitArrow(this.csharpFirst().line),
    ...splitArrow(this.csharpRepair().line),
  ]);
  protected readonly csharpMarks: Record<number, LineMark> = { 2: 'danger', 4: 'ok' };
  protected readonly csharpNotes = computed(() => ({
    2: `v${this.csharpFirst().version}: to even`,
    4: 'repair: half up',
  }));
  protected readonly fields = computed(() =>
    Object.entries(this.r().mismatched_fields).sort((a, b) => b[1] - a[1]),
  );
  protected readonly equivalenceGate = computed(
    () => this.r().gates.find((gate) => gate.gate === 'EQUIVALENCE') ?? null,
  );
  protected readonly firstMismatches = computed(() => this.r().mismatches.slice(0, 5));

  // --- Year window.
  protected readonly yw = computed(() => this.api().year_window);
  protected readonly ywCobol = computed(() => this.repo().year_window_cobol[0]);
  protected readonly ywPivotLine = computed(() => this.repo().year_window_cobol[1]);
  protected readonly ywMarks = computed(() =>
    marksFor(this.ywCobol(), ['IF WS-WINDOW-YY >= RT-CENTURY-PIVOT'], 'focus'),
  );
  protected readonly ywPivotMarks = computed<Record<number, LineMark>>(() => ({
    [this.ywPivotLine().start]: 'focus',
  }));
  protected readonly pivot = computed(() => pivotOf(this.ywPivotLine()));
  protected readonly years = computed(() => {
    const pivot = this.pivot();
    if (pivot === null) {
      return [];
    }
    return [pivot - 1, pivot + 1].map((yy) => ({
      yy: String(yy).padStart(2, '0'),
      year: windowYear(yy, pivot),
    }));
  });

  // --- Rollover.
  protected readonly ro = computed(() => this.api().rollover);
  protected readonly roCobol = computed(() => this.repo().rollover_cobol[0]);
  protected readonly roMarks = computed(() =>
    marksFor(this.roCobol(), ['COMPUTE WS-TO-ROLLOVER', 'COMPUTE WS-ROLLOVER-USE', 'WS-TO-ROLLOVER + 1'], 'focus'),
  );
  protected readonly roExample = computed(() => {
    const example = this.ro().rule.examples[0];
    if (!example) {
      return null;
    }
    const previous = Number(example.given['MV-IN-PREV-READ']);
    const current = Number(example.given['MV-IN-CURR-READ']);
    const expected = Number(example.expect['MV-OUT-CONSUMPTION']);
    // The dial's maximum, as the program's own comment states it.
    const max = Number(/UP TO (\d+)/.exec(this.roCobol().lines.join(' '))?.[1]);
    if (!Number.isFinite(max) || max - previous + 1 + current !== expected) {
      return null;
    }
    return {
      previous,
      current,
      expected,
      toRollover: max - previous,
      computed: max - previous + 1 + current,
      naive: current - previous,
    };
  });

  // --- Injection.
  protected readonly inj = computed(() => this.api().injection);
  protected readonly injCobol = computed(() => this.repo().injection_cobol[0]);
  protected readonly injMarks = computed(() => marksFor(this.injCobol(), ['AI ASSISTANT'], 'danger'));
  protected readonly injNotes = computed(() => {
    const notes: Record<number, string> = {};
    for (const [line, mark] of Object.entries(this.injMarks())) {
      if (mark === 'danger') {
        notes[Number(line)] = 'planted test';
      }
    }
    return notes;
  });
  protected readonly injectionRule = computed(
    () => this.inj().flagged.find((rule) => rule.spans.some((span) => span.start_line === 135)) ?? null,
  );
  protected readonly hallucination = computed(
    () => this.inj().flagged.find((rule) => rule.flags.includes('NAMES_NOT_FOUND')) ?? null,
  );
  protected readonly obeyed = computed(() => evaluationRow(this.data(), 'Injection comment obeyed'));
  protected readonly approvals = computed(() => evaluationRow(this.data(), 'Model-initiated approvals'));

  protected select(key: DemoKey): void {
    this.selected.set(key);
  }

  /** Arrow keys move between tabs (WAI-ARIA tabs pattern, automatic activation). */
  protected onKey(event: KeyboardEvent, index: number): void {
    const keys: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowLeft: index - 1,
      Home: 0,
      End: this.tabs.length - 1,
    };
    if (!(event.key in keys)) {
      return;
    }
    event.preventDefault();
    const next = (keys[event.key] + this.tabs.length) % this.tabs.length;
    this.select(this.tabs[next].key);
    const buttons = this.host.nativeElement.querySelectorAll('[role="tab"]');
    (buttons[next] as HTMLElement | undefined)?.focus();
  }

  protected shortId(id: string): string {
    return id.slice(0, 8);
  }
}

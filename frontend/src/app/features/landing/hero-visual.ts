import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';

import { Icon } from '../../shared/icon/icon';
import { Token, highlightLines } from '../../shared/code/highlight';
import { Snapshot } from './landing-data';

/** The story's timeline, in milliseconds from the start of one loop. */
const T = {
  cobolEnd: 1500,
  csharpStart: 1800,
  csharpEnd: 2900,
  runStart: 3200,
  runEnd: 5600,
  blockedHold: 7800,
  repairEnd: 8800,
  rerunEnd: 9800,
  loopEnd: 14000,
};
const STEP_MS = 50;

type Phase = 'cobol' | 'csharp' | 'running' | 'blocked' | 'repair' | 'rerun' | 'verified';

interface CodeLine {
  tokens: Token[];
}

/** Reveal the first `chars` characters of a block of tokenized lines. */
function reveal(lines: CodeLine[], chars: number): CodeLine[] {
  const shown: CodeLine[] = [];
  let left = chars;
  for (const line of lines) {
    if (left <= 0) {
      break;
    }
    const tokens: Token[] = [];
    for (const token of line.tokens) {
      if (left <= 0) {
        break;
      }
      tokens.push({ kind: token.kind, text: token.text.slice(0, left) });
      left -= token.text.length;
    }
    shown.push({ tokens });
    left -= 1;
  }
  return shown;
}

function length(lines: CodeLine[]): number {
  return lines.reduce((sum, line) => sum + line.tokens.reduce((n, t) => n + t.text.length, 0) + 1, 0);
}

/**
 * The hero's animation, from the stored RATECALC run: the COBOL, the first C#, the harness
 * running 500 cases, 16 turning red, the module blocked, the repair, and 500 of 500.
 * It pauses off screen, has a pause button (WCAG 2.2.2), and shows a still picture of the
 * same facts when the visitor asks for reduced motion.
 */
@Component({
  selector: 'app-hero-visual',
  imports: [Icon],
  templateUrl: './hero-visual.html',
  styleUrl: './hero-visual.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HeroVisual implements OnInit {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);
  private timer: ReturnType<typeof setInterval> | null = null;
  private visible = true;

  readonly data = input.required<Snapshot>();

  protected readonly elapsed = signal(0);
  protected readonly paused = signal(false);
  protected readonly reducedMotion = signal(false);

  protected readonly rounding = computed(() => this.data().api.rounding);
  protected readonly math = computed(() => this.data().repo.rounding_math);

  /** COBOL from the stored excerpt: the paragraph that prices the energy, without column 1-7. */
  private readonly cobolSource = computed(() => {
    const excerpt = this.data().repo.rounding_cobol[0];
    const start = excerpt.lines.findIndex((line) => line.includes('5000-PRICE-ENERGY'));
    const end = excerpt.lines.findIndex((line) => line.includes('5000-EXIT'));
    const lines = excerpt.lines.slice(start, end);
    return { start: excerpt.start + start, lines };
  });
  protected readonly cobolLines = computed(() =>
    highlightLines(this.cobolSource().lines, 'cobol').map((tokens) => ({
      // Drop the sequence area for the small picture; the demo tabs show full lines.
      tokens: dropColumns(tokens, 7),
    })),
  );

  /** The rounding helper, before and after the repair, split at its arrow to fit. */
  private readonly csharpBefore = computed(() => splitArrow(lastLine(this.rounding().csharp_first.lines)));
  private readonly csharpAfter = computed(() => splitArrow(lastLine(this.data().repo.repair.csharp.lines)));
  protected readonly csharpLines = computed(() =>
    highlightLines(this.repaired() ? this.csharpAfter() : this.csharpBefore(), 'csharp').map(
      (tokens) => ({ tokens }),
    ),
  );

  protected readonly failing = computed(() => new Set(this.rounding().mismatches.map((m) => m.case - 1)));
  protected readonly cells = computed(() => Array.from({ length: this.rounding().cases }, (_, i) => i));

  protected readonly phase = computed<Phase>(() => {
    if (this.reducedMotion()) {
      return 'verified';
    }
    const t = this.elapsed();
    if (t < T.csharpStart) return 'cobol';
    if (t < T.runStart) return 'csharp';
    if (t < T.runEnd) return 'running';
    if (t < T.blockedHold) return 'blocked';
    if (t < T.repairEnd) return 'repair';
    if (t < T.rerunEnd) return 'rerun';
    return 'verified';
  });

  protected readonly repaired = computed(() =>
    ['repair', 'rerun', 'verified'].includes(this.phase()),
  );

  protected readonly shownCobol = computed(() => {
    if (this.reducedMotion()) {
      return this.cobolLines();
    }
    const share = Math.min(1, this.elapsed() / T.cobolEnd);
    return reveal(this.cobolLines(), Math.floor(share * length(this.cobolLines())));
  });

  protected readonly shownCsharp = computed(() => {
    const t = this.elapsed();
    if (this.reducedMotion() || t >= T.csharpEnd) {
      return this.csharpLines();
    }
    const share = Math.max(0, Math.min(1, (t - T.csharpStart) / (T.csharpEnd - T.csharpStart)));
    return reveal(this.csharpLines(), Math.floor(share * length(this.csharpLines())));
  });

  /** How many cases the harness has compared so far. */
  protected readonly ran = computed(() => {
    if (this.reducedMotion()) {
      return this.rounding().cases;
    }
    const share = (this.elapsed() - T.runStart) / (T.runEnd - T.runStart);
    return Math.round(Math.max(0, Math.min(1, share)) * this.rounding().cases);
  });

  /** How many of the failing cases have turned green after the repair. */
  protected readonly fixed = computed(() => {
    const total = this.failing().size;
    if (this.reducedMotion() || this.phase() === 'verified') {
      return total;
    }
    if (this.phase() !== 'rerun') {
      return 0;
    }
    return Math.round(((this.elapsed() - T.repairEnd) / (T.rerunEnd - T.repairEnd)) * total);
  });

  private readonly fixedSet = computed(() => {
    const order = [...this.failing()].sort((a, b) => a - b);
    return new Set(order.slice(0, this.fixed()));
  });

  protected readonly failedSoFar = computed(() => {
    const ran = this.ran();
    let count = 0;
    for (const index of this.failing()) {
      if (index < ran && !this.fixedSet().has(index)) {
        count++;
      }
    }
    return count;
  });

  protected readonly identical = computed(() => this.ran() - this.failedSoFar());

  protected cellState(index: number): 'idle' | 'ok' | 'bad' | 'fixed' {
    if (index >= this.ran()) {
      return 'idle';
    }
    if (!this.failing().has(index)) {
      return 'ok';
    }
    return this.fixedSet().has(index) ? 'fixed' : 'bad';
  }

  protected readonly focusDiff = computed(() => {
    const math = this.math();
    return { case: math.case, legacy: math.legacy, modern: math.modern, exact: math.exact };
  });

  protected readonly label = computed(() => {
    const r = this.rounding();
    const repair = this.data().repo.repair;
    return (
      `Animation of the stored RATECALC run: the COBOL is translated to C#, the harness compares ` +
      `${r.cases} seeded cases, ${r.passed} are identical and ${r.failed} differ by one cent, so the ` +
      `module is blocked. After one repair, ${repair.identical} cases are identical.`
    );
  });

  ngOnInit(): void {
    const view = this.host.nativeElement.ownerDocument.defaultView;
    const query = view?.matchMedia?.('(prefers-reduced-motion: reduce)');
    this.reducedMotion.set(query?.matches ?? false);
    query?.addEventListener?.('change', (event: MediaQueryListEvent) => this.reducedMotion.set(event.matches));

    if (typeof IntersectionObserver !== 'undefined') {
      const observer = new IntersectionObserver(([entry]) => {
        this.visible = entry.isIntersecting;
      });
      observer.observe(this.host.nativeElement);
      this.destroyRef.onDestroy(() => observer.disconnect());
    }
    this.timer = setInterval(() => this.step(), STEP_MS);
    this.destroyRef.onDestroy(() => {
      if (this.timer) {
        clearInterval(this.timer);
      }
    });
  }

  protected togglePause(): void {
    this.paused.update((value) => !value);
  }

  protected replay(): void {
    this.elapsed.set(0);
    this.paused.set(false);
  }

  private step(): void {
    const hidden = this.host.nativeElement.ownerDocument.visibilityState === 'hidden';
    if (this.paused() || this.reducedMotion() || !this.visible || hidden) {
      return;
    }
    const next = this.elapsed() + STEP_MS;
    this.elapsed.set(next >= T.loopEnd ? 0 : next);
  }
}

function lastLine(lines: string[]): string {
  return lines[lines.length - 1].trim();
}

function splitArrow(line: string): string[] {
  const at = line.indexOf('=>');
  return at < 0 ? [line] : [line.slice(0, at).trimEnd(), `    ${line.slice(at)}`];
}

function dropColumns(tokens: Token[], columns: number): Token[] {
  let left = columns;
  const kept: Token[] = [];
  for (const token of tokens) {
    if (left >= token.text.length) {
      left -= token.text.length;
      continue;
    }
    kept.push({ kind: token.kind, text: token.text.slice(left) });
    left = 0;
  }
  return kept;
}

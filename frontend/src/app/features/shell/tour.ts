import {
  ChangeDetectionStrategy,
  Component,
  DOCUMENT,
  Injectable,
  computed,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';

import { Icon } from '../../shared/icon/icon';

export const TOUR_KEY = 'offshoot-tour-done';

export interface TourStep {
  title: string;
  body: string;
  /** Where the step happens; links by name work in any database (ADR-052). */
  route: string | null;
  /** An element to scroll to and outline, when the page has it. */
  anchor: string | null;
}

export const TOUR_STEPS: TourStep[] = [
  {
    title: 'Welcome to the live demo',
    body: 'BillRite is a synthetic 1990s billing system written in COBOL. In five steps, see how Offshoot caught a one-cent rounding defect before anyone could approve it.',
    route: null,
    anchor: null,
  },
  {
    title: 'Everything is measured',
    body: 'The overview reads every number from stored runs: modules by state, verified rules, identical cases and AI calls.',
    route: '/app/open/overview',
    anchor: '[data-tour="kpis"]',
  },
  {
    title: 'RATECALC is blocked',
    body: 'The harness ran the first C# translation and the real COBOL on the same 500 seeded cases. The equivalence gate failed, so no one can approve the module, and the model never could.',
    route: '/app/open/module/RATECALC',
    anchor: '#gates',
  },
  {
    title: 'One cent, field by field',
    body: 'Each mismatch shows the input, the field, the COBOL value and the C# value. The first translation rounded a half cent to the even cent; COBOL rounds it up.',
    route: null,
    anchor: '#report',
  },
  {
    title: 'The code, side by side',
    body: 'The COBOL beside the generated C#, with the paragraphs no case reached marked. Locally, Repair fixes the rounding and re-verifies all 500 cases.',
    route: null,
    anchor: '#code',
  },
  {
    title: 'Approve a verified module',
    body: 'STMTGEN passed every gate. As the architect, approve it, then find the decision in the audit log. Press Ctrl+K (⌘K) any time to jump anywhere.',
    route: '/app/open/module/STMTGEN',
    anchor: '#approval',
  },
];

/** The first-visit walkthrough of the rounding story, for the public demo. Dismissible. */
@Injectable({ providedIn: 'root' })
export class TourService {
  private readonly router = inject(Router);
  private readonly document = inject(DOCUMENT);
  private highlighted: Element | null = null;

  readonly step = signal<number | null>(null);
  readonly steps = TOUR_STEPS;

  done(): boolean {
    try {
      return this.document.defaultView?.localStorage.getItem(TOUR_KEY) === '1';
    } catch {
      return true;
    }
  }

  start(): void {
    this.go(0);
  }

  next(): void {
    const step = this.step();
    if (step === null) {
      return;
    }
    if (step >= this.steps.length - 1) {
      this.end();
    } else {
      this.go(step + 1);
    }
  }

  back(): void {
    const step = this.step();
    if (step) {
      this.go(step - 1);
    }
  }

  end(): void {
    this.step.set(null);
    this.clearHighlight();
    try {
      this.document.defaultView?.localStorage.setItem(TOUR_KEY, '1');
    } catch {
      // Storage blocked: the tour may offer itself again next time.
    }
  }

  private async go(index: number): Promise<void> {
    this.step.set(index);
    const step = this.steps[index];
    this.clearHighlight();
    if (step.route) {
      await this.router.navigateByUrl(step.route);
    }
    if (step.anchor) {
      await this.highlight(step.anchor);
    }
  }

  private async highlight(selector: string): Promise<void> {
    for (let attempt = 0; attempt < 40; attempt++) {
      const element = this.document.querySelector(selector);
      if (element) {
        element.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
        element.classList.add('tour-target');
        this.highlighted = element;
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  private clearHighlight(): void {
    this.highlighted?.classList.remove('tour-target');
    this.highlighted = null;
  }
}

@Component({
  selector: 'app-tour',
  imports: [Icon],
  template: `
    @if (current(); as step) {
      <section class="tour" role="dialog" aria-modal="false" aria-labelledby="tour-title">
        <div class="tour__progress" aria-hidden="true">
          @for (item of tour.steps; track $index) {
            <span [class.on]="$index <= index()"></span>
          }
        </div>
        <p class="tour__count">
          <app-icon name="compass" [size]="14" /> Guided tour · {{ index() + 1 }} of {{ tour.steps.length }}
        </p>
        <h2 id="tour-title">{{ step.title }}</h2>
        <p class="tour__body">{{ step.body }}</p>
        <div class="tour__actions">
          <button type="button" class="button button--ghost button--sm" (click)="tour.end()">
            {{ index() === 0 ? 'Skip' : 'End tour' }}
          </button>
          <span class="tour__spacer"></span>
          @if (index() > 0) {
            <button type="button" class="button button--quiet button--sm" (click)="tour.back()">Back</button>
          }
          <button type="button" class="button button--sm" (click)="tour.next()">
            {{ index() === 0 ? 'Start the tour' : index() === tour.steps.length - 1 ? 'Finish' : 'Next' }}
          </button>
        </div>
      </section>
    }
  `,
  styles: `
    @use 'tokens' as t;

    .tour {
      position: fixed;
      right: var(--space-4);
      bottom: var(--space-4);
      left: var(--space-4);
      z-index: 150;
      display: grid;
      gap: var(--space-2);
      padding: var(--space-5);
      border: 1px solid var(--border-accent);
      border-radius: var(--radius-xl);
      background: var(--bg-elevated);
      box-shadow: var(--shadow-popover), var(--glow-accent);

      @include t.up(t.$bp-sm) {
        left: auto;
        width: 24rem;
      }

      @include t.motion {
        animation: tour-in var(--dur-slow) var(--ease-out);
      }

      h2 {
        font-size: var(--text-lg);
      }
    }

    @keyframes tour-in {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
    }

    .tour__progress {
      display: flex;
      gap: 4px;

      span {
        flex: 1;
        height: 3px;
        border-radius: 2px;
        background: var(--surface-3);
      }

      .on {
        background: var(--gradient-accent);
      }
    }

    .tour__count {
      display: flex;
      gap: var(--space-1);
      align-items: center;
      margin-top: var(--space-1);
      color: var(--accent-fg);
      font-size: var(--text-xs);
      font-weight: 600;
    }

    .tour__body {
      color: var(--text-2);
    }

    .tour__actions {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      margin-top: var(--space-2);
    }

    .tour__spacer {
      flex: 1;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Tour {
  protected readonly tour = inject(TourService);
  protected readonly index = computed(() => this.tour.step() ?? 0);
  protected readonly current = computed(() => {
    const step = this.tour.step();
    return step === null ? null : this.tour.steps[step];
  });
}

import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  OnInit,
  afterNextRender,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';

import { Icon } from '../../../shared/icon/icon';
import { IconName } from '../../../shared/icon/icons';
import { Snapshot, evaluationRow } from '../landing-data';

interface Step {
  key: string;
  icon: IconName;
  title: string;
  body: string;
  who: string;
  proof: string[];
}

const SOURCE_TEXT: Record<string, string> = {
  boundary: 'PIC boundaries',
  date: 'date windows',
  constant: 'copybook constants',
  rule: 'rule examples',
  recorded: 'recorded data',
  random: 'seeded random',
};

/** The seven steps, lit up as the visitor scrolls past them. */
@Component({
  selector: 'app-landing-pipeline',
  imports: [Icon],
  template: `
    <section class="l-section pipeline" aria-labelledby="pipeline-title">
      <div class="l-container">
        <div class="l-head l-head--center">
          <p class="l-eyebrow">How it works</p>
          <h2 id="pipeline-title" class="l-title">Seven steps. Each one is checked.</h2>
          <p class="l-lede">
            The model proposes; deterministic tooling verifies; people approve. Every step below
            shows what the demo's stored runs recorded.
          </p>
        </div>

        <ol class="steps" [style.--fill]="fill()">
          @for (step of steps(); track step.key; let i = $index) {
            <li class="step" [class.is-active]="i <= active()" [attr.data-index]="i">
              <div class="step__marker" aria-hidden="true">
                <app-icon [name]="step.icon" [size]="18" />
              </div>
              <div class="step__body l-card">
                <p class="step__num">
                  <span>{{ i + 1 }} / {{ steps().length }}</span><span class="step__who">{{ step.who }}</span>
                </p>
                <h3>{{ step.title }}</h3>
                <p>{{ step.body }}</p>
                <ul class="proof" aria-label="From the stored runs">
                  @for (item of step.proof; track item) {
                    <li>{{ item }}</li>
                  }
                </ul>
              </div>
            </li>
          }
        </ol>
      </div>
    </section>
  `,
  styles: `
    @use 'tokens' as t;

    .steps {
      --fill: 0;
      position: relative;
      display: grid;
      gap: var(--space-5);
      max-width: 52rem;
      margin: 0 auto;
      padding: 0;
      list-style: none;

      &::before,
      &::after {
        position: absolute;
        top: 1.25rem;
        bottom: 1.25rem;
        left: 1.25rem;
        width: 2px;
        margin-left: -1px;
        border-radius: 2px;
        content: '';
      }

      &::before {
        background: var(--border-strong);
      }

      &::after {
        background: var(--gradient-accent);
        transform: scaleY(var(--fill));
        transform-origin: top;

        @include t.motion {
          transition: transform 600ms var(--ease-out);
        }
      }
    }

    .step {
      position: relative;
      display: grid;
      grid-template-columns: 2.5rem minmax(0, 1fr);
      gap: var(--space-4);
      align-items: start;
    }

    .step__marker {
      position: relative;
      z-index: 1;
      display: grid;
      place-items: center;
      width: 2.5rem;
      height: 2.5rem;
      border: 1px solid var(--border-strong);
      border-radius: 50%;
      background: var(--surface-1);
      color: var(--text-3);

      @include t.motion {
        transition:
          color var(--dur-slow),
          border-color var(--dur-slow),
          box-shadow var(--dur-slow);
      }
    }

    .step.is-active .step__marker {
      border-color: var(--border-accent);
      color: var(--accent-fg);
      box-shadow: 0 0 0 4px var(--accent-soft), 0 0 24px -4px rgb(52 211 153 / 50%);
    }

    .step__body {
      display: grid;
      gap: var(--space-2);
      padding: var(--space-4) var(--space-5);
      color: var(--text-2);
      font-size: var(--text-base);
      line-height: 1.6;

      @include t.motion {
        transition:
          border-color var(--dur-slow),
          opacity var(--dur-slow);
      }

      h3 {
        color: var(--text);
        font-size: var(--text-xl);
      }
    }

    .step:not(.is-active) .step__body {
      opacity: 0.72;
    }

    .step.is-active .step__body {
      border-color: var(--border-strong);
    }

    .step__num {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-1) var(--space-3);
      white-space: nowrap;
      justify-content: space-between;
      color: var(--text-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }

    .step__who {
      color: var(--accent-fg);
    }

    .proof {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      margin: var(--space-2) 0 0;
      padding: 0;
      list-style: none;

      li {
        padding: 0.15rem 0.55rem;
        border: 1px solid var(--border);
        border-radius: var(--radius-pill);
        background: var(--surface-2);
        color: var(--text-2);
        font-family: var(--font-mono);
        font-size: var(--text-xs);
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingPipeline implements OnInit {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);

  readonly data = input.required<Snapshot>();

  protected readonly active = signal(-1);
  protected readonly fill = computed(() => {
    const steps = this.steps().length;
    return steps > 1 ? Math.max(0, this.active()) / (steps - 1) : 1;
  });

  protected readonly steps = computed<Step[]>(() => {
    const data = this.data();
    const inv = data.api.inventory.summary;
    const r = data.api.rounding;
    const order = data.api.modules.map((module) => module.program).join(' → ');
    const compiled = evaluationRow(data, 'Migration: compiled on the first attempt');
    const firstTry = evaluationRow(data, 'Equivalence 100% on the first attempt');
    const sources = Object.entries(r.by_source)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => `${count} ${SOURCE_TEXT[name] ?? name}`);
    const gates = r.gates.map(
      (gate) => `${gate.label}: ${gate.value === null ? 'not run' : gate.passed ? 'pass' : 'fail'}`,
    );
    const modes = data.api.modules
      .filter((module) => module.facade_mode !== 'LEGACY')
      .map((module) => `${module.program}: ${module.facade_mode.toLowerCase()}`);
    const states = data.api.rules.by_state;
    return [
      {
        key: 'inventory',
        icon: 'boxes',
        title: 'Inventory',
        who: 'Parser, no AI',
        body: 'A purpose-built parser expands the copybooks and builds the call graph, the data layouts and the dead-code report.',
        proof: [
          `${inv['programs']} programs`,
          `${inv['copybooks']} copybooks`,
          `${inv['performs']} PERFORMs`,
          `${inv['dead_paragraphs']} dead paragraph`,
        ],
      },
      {
        key: 'rules',
        icon: 'scroll-text',
        title: 'Business rules',
        who: 'Agent proposes, people decide',
        body: 'The agent proposes rules, each citing exact source lines. The server checks every span and data name; a person verifies, edits or rejects each rule.',
        proof: [
          `${data.api.rules.total} rules proposed`,
          `${states['VERIFIED'] ?? 0} verified`,
          `${data.api.injection.flagged.length} flagged in RATECALC`,
        ],
      },
      {
        key: 'plan',
        icon: 'map',
        title: 'Plan',
        who: 'Agent proposes, architect approves',
        body: 'The agent proposes target services and risks; the order comes from the call graph, so callees move before their callers.',
        proof: [order],
      },
      {
        key: 'migrate',
        icon: 'code',
        title: 'Migrate',
        who: 'Agent writes, sandbox builds',
        body: 'The agent writes C# and unit tests. They build and run in a sandbox with no network that refuses processes, file access and reflection, with a bounded repair loop.',
        proof: compiled ? [`compiled first time: ${compiled[1]}`] : [],
      },
      {
        key: 'prove',
        icon: 'flask-conical',
        title: 'Prove',
        who: 'Harness, not the model',
        body: 'A golden-master harness runs the real COBOL and the new C# on the same seeded inputs and compares every output field exactly, then measures paragraph coverage and the mutation score.',
        proof: [`${r.cases} cases, seed ${r.seed}`, ...sources.slice(0, 3), firstTry ? `first try: ${firstTry[1].split('(')[0].trim()}` : ''].filter(Boolean),
      },
      {
        key: 'approve',
        icon: 'badge-check',
        title: 'Approve',
        who: 'Gates, then a person',
        body: 'Server-side gates decide whether a module may be approved at all. An architect approves or rejects; the model has no way to.',
        proof: gates,
      },
      {
        key: 'promote',
        icon: 'route',
        title: 'Promote',
        who: 'Facade, per module',
        body: 'A strangler facade routes each module: legacy, then shadow (both run and answers are compared), then modern. Rolling back is one step.',
        proof: modes.length ? modes : ['every module starts on legacy'],
      },
    ];
  });

  ngOnInit(): void {
    const node: HTMLElement = this.host.nativeElement;
    const view = node.ownerDocument.defaultView;
    const still = view?.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    if (still || typeof IntersectionObserver === 'undefined') {
      this.active.set(this.steps().length - 1);
      return;
    }
    // A step is reached once its top passes the middle of the screen.
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const index = Number((entry.target as HTMLElement).dataset['index']);
          const passed = entry.isIntersecting || entry.boundingClientRect.top < 0;
          if (passed && index > this.active()) {
            this.active.set(index);
          } else if (!passed && index <= this.active()) {
            this.active.set(index - 1);
          }
        }
      },
      { rootMargin: '0px 0px -50% 0px' },
    );
    afterNextRender(() => node.querySelectorAll('.step').forEach((step) => observer.observe(step)), {
      injector: this.injector,
    });
    this.destroyRef.onDestroy(() => observer.disconnect());
  }
}

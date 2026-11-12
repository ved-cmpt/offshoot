import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { Icon } from '../../../shared/icon/icon';
import { IconName } from '../../../shared/icon/icons';
import { Reveal } from '../../../shared/reveal';
import { Snapshot, thousands } from '../landing-data';

type Mark = 'yes' | 'no' | 'part';

interface Row {
  need: string;
  manual: [Mark, string];
  ai: [Mark, string];
  offshoot: [Mark, string];
}

/** The comparison claims only what Offshoot does in v1; "part" means possible, by hand. */
const ROWS: Row[] = [
  {
    need: 'Drafts the code with AI',
    manual: ['no', 'Written by hand'],
    ai: ['yes', 'Yes'],
    offshoot: ['yes', 'Yes, module by module'],
  },
  {
    need: 'Business rules extracted, each citing its source lines',
    manual: ['part', 'If someone writes them down'],
    ai: ['no', 'No citations to check'],
    offshoot: ['yes', 'Spans and names checked by the server'],
  },
  {
    need: 'A person reviews every rule',
    manual: ['yes', 'Yes'],
    ai: ['no', 'No'],
    offshoot: ['yes', 'Verify, edit or reject'],
  },
  {
    need: 'The real legacy program runs against the new code',
    manual: ['part', 'If a harness is built'],
    ai: ['no', 'No'],
    offshoot: ['yes', '500 seeded cases a module'],
  },
  {
    need: 'Field-by-field diff of every mismatch',
    manual: ['no', 'No'],
    ai: ['no', 'No'],
    offshoot: ['yes', 'Yes'],
  },
  {
    need: 'Mutation testing shows the cases would catch a change',
    manual: ['no', 'Rarely'],
    ai: ['no', 'No'],
    offshoot: ['yes', 'Stryker.NET'],
  },
  {
    need: 'Generated code runs in a sandbox without network',
    manual: ['part', 'Not applicable'],
    ai: ['no', 'Runs where it lands'],
    offshoot: ['yes', 'No network, limits, deny list'],
  },
  {
    need: 'The model cannot approve its own work',
    manual: ['part', 'Not applicable'],
    ai: ['no', 'Nothing stops it'],
    offshoot: ['yes', 'No contract field can approve'],
  },
  {
    need: 'Gradual cutover per module, with rollback',
    manual: ['part', 'If someone builds it'],
    ai: ['no', 'No'],
    offshoot: ['yes', 'Legacy, shadow, modern'],
  },
  {
    need: 'Append-only audit trail of AI calls and decisions',
    manual: ['no', 'No'],
    ai: ['no', 'No'],
    offshoot: ['yes', 'Enforced by the database'],
  },
];

const MARK_ICON: Record<Mark, IconName> = { yes: 'circle-check', no: 'circle-x', part: 'circle-dot' };
const MARK_TEXT: Record<Mark, string> = { yes: 'Yes', no: 'No', part: 'Partly' };

@Component({
  selector: 'app-landing-problem',
  imports: [Icon, Reveal],
  template: `
    <section class="l-section" aria-labelledby="problem-title">
      <div class="l-container">
        <div class="l-head" appReveal>
          <p class="l-eyebrow">The problem</p>
          <h2 id="problem-title" class="l-title">Legacy rewrites fail quietly, one cent at a time.</h2>
          <p class="l-lede">
            COBOL holds decades of business rules nobody wrote down. A rewrite by hand is slow; a
            rewrite by an AI is fast and unchecked. Either way the danger is the same: a difference
            nobody notices until it is on a bill.
          </p>
        </div>

        <div class="cards">
          <article class="l-card card" appReveal>
            <app-icon name="scroll-text" [size]="20" />
            <h3>The rules live only in the code</h3>
            <p>
              BillRite's {{ inv()['programs'] }} programs and {{ inv()['copybooks'] }} copybooks hold
              {{ lines() }} program lines, and a dead paragraph nobody removed:
              <code>{{ data().api.inventory.dead_paragraphs[0] }}</code>.
            </p>
          </article>
          <article class="l-card card card--focus" appReveal>
            <app-icon name="bug" [size]="20" />
            <h3>Unit tests pass. The bill is still wrong.</h3>
            <p>
              The first C# RATECALC passed its own {{ unitTests() }} unit tests. Against the real
              COBOL, {{ r().failed }} of {{ r().cases }} cases differed by one cent.
            </p>
            <div class="bar" aria-hidden="true">
              <span class="bar__ok" [style.flex-grow]="r().passed"></span>
              <span class="bar__bad" [style.flex-grow]="r().failed * 6"></span>
            </div>
            <p class="bar__legend">
              <span>{{ r().passed }} identical</span><span>{{ r().failed }} different</span>
            </p>
          </article>
          <article class="l-card card" appReveal>
            <app-icon name="route" [size]="20" />
            <h3>Big-bang cutovers stop the business</h3>
            <p>
              A batch that bills a town cannot just be switched off. Each module needs its own way
              across, and back: legacy, then shadow, then modern, with a rollback at every step.
            </p>
          </article>
        </div>

        <div class="compare" appReveal>
          <h3 class="compare__title">Without and with Offshoot</h3>
          <div class="table-scroll" tabindex="0" role="region" aria-label="Comparison">
            <table class="compare__table">
              <thead>
                <tr>
                  <th scope="col"><span class="visually-hidden">What a migration needs</span></th>
                  <th scope="col">Manual rewrite</th>
                  <th scope="col">AI rewrite alone</th>
                  <th scope="col" class="compare__us">Offshoot</th>
                </tr>
              </thead>
              <tbody>
                @for (row of rows; track row.need) {
                  <tr>
                    <th scope="row">{{ row.need }}</th>
                    @for (cell of [row.manual, row.ai, row.offshoot]; track $index) {
                      <td [class]="'mark mark--' + cell[0]" [class.compare__us]="$index === 2">
                        <app-icon [name]="icon[cell[0]]" [size]="16" />
                        <span class="visually-hidden">{{ text[cell[0]] }}:</span>
                        <span>{{ cell[1] }}</span>
                      </td>
                    }
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <p class="l-source">
            Offshoot's column describes v1 as built. "Partly" means possible, if a team builds it by
            hand.
          </p>
        </div>
      </div>
    </section>
  `,
  styles: `
    @use 'tokens' as t;

    .cards {
      display: grid;
      gap: var(--space-4);

      @include t.up(t.$bp-md) {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    .card {
      display: grid;
      gap: var(--space-3);
      align-content: start;
      padding: var(--space-5);
      color: var(--text-2);
      font-size: var(--text-base);
      line-height: 1.6;

      app-icon {
        color: var(--accent-fg);
      }

      h3 {
        color: var(--text);
        font-size: var(--text-lg);
      }
    }

    .card--focus {
      border-color: var(--danger-border);

      app-icon {
        color: var(--danger);
      }
    }

    .bar {
      display: flex;
      gap: 2px;
      height: 0.5rem;
      overflow: hidden;
      border-radius: var(--radius-pill);
    }

    .bar__ok {
      background: color-mix(in srgb, var(--ok) 70%, transparent);
    }

    .bar__bad {
      background: var(--danger);
    }

    .bar__legend {
      display: flex;
      justify-content: space-between;
      color: var(--text-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }

    .compare {
      margin-top: var(--space-8);
    }

    .compare__title {
      margin-bottom: var(--space-4);
      font-size: var(--text-2xl);
    }

    .compare__table {
      width: 100%;
      min-width: 44rem;
      border-collapse: collapse;
      font-size: var(--text-sm);

      th,
      td {
        padding: var(--space-3) var(--space-4);
        border-bottom: 1px solid var(--border);
        text-align: left;
        vertical-align: middle;
      }

      thead th {
        color: var(--text-2);
        font-weight: 600;
      }

      tbody th {
        width: 34%;
        color: var(--text);
        font-weight: 500;
      }

      tbody tr:last-child > * {
        border-bottom: 0;
      }
    }

    .compare__us {
      background: var(--accent-soft);
      color: var(--text);
    }

    thead .compare__us {
      color: var(--accent-fg);
    }

    .mark {
      color: var(--text-2);

      app-icon {
        margin-right: var(--space-2);
        vertical-align: -3px;
      }
    }

    .mark--yes app-icon {
      color: var(--ok);
    }

    .mark--no app-icon {
      color: var(--danger);
    }

    .mark--part app-icon {
      color: var(--warn);
    }

    .l-source {
      margin-top: var(--space-3);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingProblem {
  readonly data = input.required<Snapshot>();

  protected readonly rows = ROWS;
  protected readonly icon = MARK_ICON;
  protected readonly text = MARK_TEXT;
  protected readonly r = computed(() => this.data().api.rounding);
  protected readonly inv = computed(() => this.data().api.inventory.summary);
  protected readonly lines = computed(() => thousands(this.inv()['lines'] ?? 0));
  protected readonly unitTests = computed(() => {
    const tests = this.r().csharp_first.unit_tests;
    return `${tests.passed} of ${tests.total}`;
  });
}

import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { Icon } from '../../../shared/icon/icon';
import { IconName } from '../../../shared/icon/icons';
import { Reveal } from '../../../shared/reveal';
import { DOCS, Snapshot, evaluationRow } from '../landing-data';

interface Feature {
  icon: IconName;
  title: string;
  body: string;
  fact: string;
}

@Component({
  selector: 'app-landing-capabilities',
  imports: [Icon, Reveal],
  template: `
    <section class="l-section" aria-labelledby="features-title">
      <div class="l-container">
        <div class="l-head" appReveal>
          <p class="l-eyebrow">Features</p>
          <h2 id="features-title" class="l-title">Everything between "the AI wrote it" and "ship it".</h2>
        </div>
        <ul class="features">
          @for (feature of features(); track feature.title) {
            <li class="feature l-card" appReveal>
              <span class="feature__icon"><app-icon [name]="feature.icon" [size]="18" /></span>
              <h3>{{ feature.title }}</h3>
              <p>{{ feature.body }}</p>
              @if (feature.fact) {
                <p class="feature__fact">{{ feature.fact }}</p>
              }
            </li>
          }
        </ul>
      </div>
    </section>

    <section class="l-section security" aria-labelledby="security-title">
      <div class="l-container security__grid">
        <div class="l-head" appReveal>
          <p class="l-eyebrow">Security and governance</p>
          <h2 id="security-title" class="l-title">The model proposes. It never decides.</h2>
          <p class="l-lede">
            Offshoot treats the model as an untrusted contributor. Its output passes a strict
            contract, runs only in a sandbox, and waits for a person and the gates.
          </p>
          <a class="button button--quiet" [href]="docs.security" rel="noopener">
            Read docs/SECURITY.md <app-icon name="arrow-up-right" [size]="16" />
          </a>
        </div>
        <ul class="controls">
          <li class="control l-card" appReveal>
            <app-icon name="octagon-x" [size]="20" />
            <div>
              <h3>The model cannot approve</h3>
              <p>
                No field in the agent's contract can approve, verify or promote anything. Approval
                needs an architect and a passing verification.
                @if (approvals(); as row) {
                  Model-initiated approvals: <strong>{{ row[1] }}</strong>.
                }
              </p>
            </div>
          </li>
          <li class="control l-card" appReveal>
            <app-icon name="lock" [size]="20" />
            <div>
              <h3>Sandboxes, not trust</h3>
              <p>
                Legacy and generated code run only in containers with no network, read-only
                sources and CPU, memory and time limits, never on the host or in the API process. A
                deny policy refuses processes, sockets, files and reflection at build time.
              </p>
            </div>
          </li>
          <li class="control l-card" appReveal>
            <app-icon name="history" [size]="20" />
            <div>
              <h3>An audit log nobody can edit</h3>
              <p>
                Every AI call, job and human decision is appended to a log that the database's
                grants and triggers keep append-only.
              </p>
            </div>
          </li>
          <li class="control l-card" appReveal>
            <app-icon name="shield-check" [size]="20" />
            <div>
              <h3>Injection is data, not instructions</h3>
              <p>
                Retrieved code, comments and documents are never instructions. The demo's planted
                comment produced a rule the server flagged
                <code>{{ injectionFlag() }}</code>, which stays unverifiable.
                @if (obeyed(); as row) {
                  Obeyed: mock {{ row[1] }}, live {{ row[2] }}.
                }
              </p>
            </div>
          </li>
        </ul>
      </div>
    </section>
  `,
  styles: `
    @use 'tokens' as t;

    .features {
      display: grid;
      gap: var(--space-4);
      margin: 0;
      padding: 0;
      list-style: none;

      @include t.up(t.$bp-sm) {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      @include t.up(t.$bp-lg) {
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }
    }

    .feature {
      display: grid;
      gap: var(--space-2);
      align-content: start;
      padding: var(--space-5);
      color: var(--text-2);
      font-size: var(--text-base);
      line-height: 1.6;

      h3 {
        margin-top: var(--space-2);
        color: var(--text);
        font-size: var(--text-md);
      }

      @include t.motion {
        transition:
          border-color var(--dur),
          transform var(--dur) var(--ease-out);
      }

      &:hover {
        border-color: var(--border-strong);
        transform: translateY(-2px);
      }
    }

    .feature__icon {
      display: grid;
      place-items: center;
      width: 2.25rem;
      height: 2.25rem;
      border: 1px solid var(--border-accent);
      border-radius: var(--radius);
      background: var(--accent-soft);
      color: var(--accent-fg);
    }

    .feature__fact {
      margin-top: auto;
      padding-top: var(--space-2);
      color: var(--text-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }

    .security {
      border-block: 1px solid var(--border);
      background:
        radial-gradient(40rem 20rem at 0% 0%, rgb(34 211 238 / 6%), transparent 70%),
        var(--bg-elevated);
    }

    .security__grid {
      display: grid;
      gap: var(--space-6);

      @include t.up(t.$bp-lg) {
        grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
        align-items: start;
      }

      .l-head {
        margin-bottom: 0;
        justify-items: start;
      }
    }

    .controls {
      display: grid;
      gap: var(--space-3);
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .control {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: var(--space-4);
      padding: var(--space-5);
      color: var(--text-2);
      font-size: var(--text-base);
      line-height: 1.6;

      > app-icon {
        margin-top: 0.15rem;
        color: var(--accent-fg);
      }

      h3 {
        margin-bottom: var(--space-1);
        color: var(--text);
        font-size: var(--text-md);
      }

      strong {
        color: var(--text);
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingCapabilities {
  readonly data = input.required<Snapshot>();

  protected readonly docs = DOCS;
  protected readonly approvals = computed(() => evaluationRow(this.data(), 'Model-initiated approvals'));
  protected readonly obeyed = computed(() => evaluationRow(this.data(), 'Injection comment obeyed'));
  protected readonly injectionFlag = computed(() => {
    const rule = this.data().api.injection.flagged.find((item) =>
      item.spans.some((span) => span.start_line === 135),
    );
    return rule?.flags.join(', ') ?? '';
  });

  protected readonly features = computed<Feature[]>(() => {
    const api = this.data().api;
    const r = api.rounding;
    const scores = api.modules
      .map((module) => module.run?.mutation_score)
      .filter((score): score is number => typeof score === 'number')
      .sort((a, b) => a - b);
    const verified = api.rules.by_state['VERIFIED'] ?? 0;
    return [
      {
        icon: 'flask-conical',
        title: 'Equivalence harness',
        body: 'Runs the real COBOL and the new C# on the same seeded inputs and compares every output field, exactly.',
        fact: `${r.cases} cases a module · seed ${r.seed}`,
      },
      {
        icon: 'bug',
        title: 'Mutation testing',
        body: 'Stryker.NET changes the C# on purpose and checks that the cases notice. Survivors are listed.',
        fact: scores.length ? `${scores[0]}% to ${scores[scores.length - 1]}% on the demo` : '',
      },
      {
        icon: 'lock',
        title: 'Sandboxing',
        body: 'Builds and runs in containers with no network, read-only sources and hard limits, behind a token.',
        fact: 'never on the host or in the API process',
      },
      {
        icon: 'list-checks',
        title: 'Gates',
        body: 'Build, unit tests, equivalence, coverage and mutation, decided on the server. Exceptions need a reason.',
        fact: `${r.gates.length} gates per module`,
      },
      {
        icon: 'history',
        title: 'Audit trail',
        body: 'Every AI call, job and decision, append-only, with filters by action and entity.',
        fact: 'enforced by grants and triggers',
      },
      {
        icon: 'route',
        title: 'Strangler facade',
        body: 'A YARP facade routes each module to legacy, shadow or modern, compares shadow answers and rolls back.',
        fact: 'promotion needs a clean shadow sample',
      },
      {
        icon: 'scroll-text',
        title: 'Rule extraction',
        body: 'Rules with exact line citations; the server checks every span and data name before a person decides.',
        fact: `${api.rules.total} rules · ${verified} verified`,
      },
      {
        icon: 'file-text',
        title: 'Reports',
        body: 'An assessment report of the as-is system, the plan and the evidence, as Markdown or a PDF.',
        fact: 'every number from stored runs',
      },
    ];
  });
}

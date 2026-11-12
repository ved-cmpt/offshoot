import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { Icon } from '../../../shared/icon/icon';
import { Reveal } from '../../../shared/reveal';
import { DOCS, REPO_URL, Snapshot } from '../landing-data';

interface Question {
  q: string;
  a: string;
}

const FAQ: Question[] = [
  {
    q: 'Is Offshoot ready for production?',
    a: 'No. It is an open-source v1 that proves the workflow end to end on BillRite, a synthetic 1990s billing system. It covers the COBOL dialect BillRite uses: batch programs with sequential files, without CICS, DB2 or JCL.',
  },
  {
    q: 'What does "equivalent" mean here?',
    a: 'Every output field of every case is identical to the real COBOL program\'s, on 500 seeded cases per module drawn from PIC boundaries, copybook constants, rule examples, recorded data and seeded random inputs. It is proof over the tested inputs, not over all inputs, and mutation testing shows how sensitive those cases are.',
  },
  {
    q: 'Can the AI approve its own work?',
    a: 'No. The agent\'s output must match a strict contract with no field that approves, verifies or promotes anything. Gates are decided on the server, and only an architect can approve a module whose latest verification passed.',
  },
  {
    q: 'Does our code leave our network?',
    a: 'In the reference deployment model, no: Offshoot and the AI endpoint both run inside your network. The public demo uses recorded AI responses, so nothing is sent to a model at all.',
  },
  {
    q: 'Which AI model does it use?',
    a: 'Recorded fixtures by default, so the whole pipeline runs offline and reproducibly. Gemini when configured, with a hard cap on live calls. The agent sits behind an interface, so another provider is an adapter.',
  },
  {
    q: 'Why can the public demo not run the repair?',
    a: 'Untrusted code only ever runs in isolated containers without a network, and a free shared host cannot provide them. The demo shows stored runs of the real sandbox; run it locally with Docker and everything runs, including the repair.',
  },
  {
    q: 'Why does the demo take a while to open?',
    a: 'It runs on a free instance that sleeps after 15 idle minutes. The first visit wakes it, which takes about 45 seconds. It resets itself every day.',
  },
  {
    q: 'What does it cost?',
    a: 'Nothing. Offshoot is open source under the MIT licence, and it runs on open-source tools.',
  },
];

@Component({
  selector: 'app-landing-results',
  imports: [Icon, Reveal, RouterLink],
  template: `
    <section class="l-section" aria-labelledby="results-title">
      <div class="l-container">
        <div class="l-head" appReveal>
          <p class="l-eyebrow">Evaluation</p>
          <h2 id="results-title" class="l-title">Measured, not claimed.</h2>
          <p class="l-lede">
            The mock column measures the pipeline with recorded fixtures, not a model. The live
            column is one small, capped sample of one model: too small to generalize from, and
            labelled as such.
          </p>
        </div>
        <div class="table-scroll" tabindex="0" role="region" aria-label="Evaluation results" appReveal>
          <table class="results">
            <thead>
              <tr>
                @for (column of evaluation().columns; track column) {
                  <th scope="col">{{ plain(column) }}</th>
                }
              </tr>
            </thead>
            <tbody>
              @for (row of evaluation().rows; track row[0]) {
                <tr>
                  <th scope="row">{{ row[0] }}</th>
                  <td>{{ cell(row[1]) }}</td>
                  <td>{{ cell(row[2]) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        <p class="l-source">
          From <a [href]="docs.evaluation" rel="noopener">{{ evaluation().source }}</a>, with the
          method, the raw numbers and the failures.
        </p>
      </div>
    </section>

    <section class="l-section open" aria-labelledby="open-title">
      <div class="l-container">
        <div class="l-head l-head--center" appReveal>
          <p class="l-eyebrow">Open source</p>
          <h2 id="open-title" class="l-title">No pricing page. No sign-up.</h2>
        </div>
        <ul class="tiers">
          <li class="tier l-card" appReveal>
            <app-icon name="scale" [size]="20" />
            <h3>Open source, MIT</h3>
            <p>The code, the tests, the decisions and the evaluation are all in the repository.</p>
            <a [href]="repo" rel="noopener">Read the source <app-icon name="arrow-up-right" [size]="14" /></a>
          </li>
          <li class="tier l-card" appReveal>
            <app-icon name="terminal" [size]="20" />
            <h3>Run it locally</h3>
            <p>Docker Compose brings up the whole stack, sandboxes included, so migration, repair and verification all run.</p>
            <a [href]="docs.readme" rel="noopener">Setup in the README <app-icon name="arrow-up-right" [size]="14" /></a>
          </li>
          <li class="tier tier--live l-card" appReveal>
            <app-icon name="play" [size]="20" />
            <h3>Live demo</h3>
            <p>The stored runs of the real sandbox, four demo roles, approvals and the audit log. Resets daily.</p>
            <a routerLink="/app">Open the demo <app-icon name="arrow-right" [size]="14" /></a>
          </li>
        </ul>
      </div>
    </section>

    <section class="l-section" aria-labelledby="faq-title">
      <div class="l-container faq">
        <div class="l-head" appReveal>
          <p class="l-eyebrow">FAQ</p>
          <h2 id="faq-title" class="l-title">Questions people ask.</h2>
        </div>
        <div class="faq__list" appReveal>
          @for (item of faq; track item.q) {
            <details class="faq__item">
              <summary>
                <span>{{ item.q }}</span>
                <app-icon name="plus" [size]="18" />
              </summary>
              <p>{{ item.a }}</p>
            </details>
          }
        </div>
      </div>
    </section>

    <section class="l-section cta" aria-labelledby="cta-title">
      <div class="l-container">
        <div class="cta__band" appReveal>
          <img src="brand/offshoot-mark.svg" alt="" width="48" height="48" />
          <h2 id="cta-title" class="l-title">See the rounding defect for yourself.</h2>
          <p class="l-lede">Sign in as any demo role. RATECALC is waiting, blocked, with all {{ failed() }} differences.</p>
          <div class="cta__buttons">
            <a class="button button--lg" routerLink="/app/open/module/RATECALC">
              Try the live demo <app-icon name="arrow-right" [size]="16" />
            </a>
            <a class="button button--lg button--quiet" [href]="repo" rel="noopener">
              <app-icon name="git-branch" [size]="16" /> View on GitHub
            </a>
          </div>
        </div>
      </div>
    </section>
  `,
  styles: `
    @use 'tokens' as t;

    .results {
      width: 100%;
      min-width: 40rem;
      border-collapse: collapse;
      font-size: var(--text-base);

      th,
      td {
        padding: var(--space-3) var(--space-4);
        border-bottom: 1px solid var(--border);
        text-align: left;
        vertical-align: top;
      }

      thead th {
        background: var(--surface-2);
        color: var(--text-2);
        font-size: var(--text-sm);
        font-weight: 600;
      }

      tbody th {
        width: 30%;
        color: var(--text);
        font-weight: 500;
      }

      td {
        color: var(--text-2);
        font-variant-numeric: tabular-nums;
      }

      tbody tr:last-child > * {
        border-bottom: 0;
      }
    }

    .l-source {
      margin-top: var(--space-3);
    }

    .open {
      border-top: 1px solid var(--border);
    }

    .tiers {
      display: grid;
      gap: var(--space-4);
      margin: 0;
      padding: 0;
      list-style: none;

      @include t.up(t.$bp-md) {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    .tier {
      display: grid;
      gap: var(--space-3);
      align-content: start;
      padding: var(--space-6) var(--space-5);
      color: var(--text-2);
      font-size: var(--text-base);
      line-height: 1.6;

      > app-icon {
        color: var(--accent-fg);
      }

      h3 {
        color: var(--text);
        font-size: var(--text-xl);
      }

      a {
        display: inline-flex;
        gap: var(--space-1);
        align-items: center;
        font-weight: 600;
        text-decoration: none;

        &:hover {
          text-decoration: underline;
        }
      }
    }

    .tier--live {
      border-color: var(--border-accent);
      box-shadow: var(--glow-accent);
    }

    .faq {
      display: grid;
      gap: var(--space-6);

      @include t.up(t.$bp-lg) {
        grid-template-columns: minmax(0, 0.7fr) minmax(0, 1.3fr);
        align-items: start;
      }

      .l-head {
        margin-bottom: 0;
      }
    }

    .faq__list {
      border-top: 1px solid var(--border);
    }

    .faq__item {
      border-bottom: 1px solid var(--border);

      summary {
        display: flex;
        gap: var(--space-4);
        align-items: center;
        justify-content: space-between;
        padding: var(--space-4) 0;
        color: var(--text);
        font-size: var(--text-md);
        font-weight: 500;
        list-style: none;
        cursor: pointer;

        &::-webkit-details-marker {
          display: none;
        }

        app-icon {
          color: var(--text-3);

          @include t.motion {
            transition: transform var(--dur) var(--ease-out);
          }
        }
      }

      &[open] summary app-icon {
        transform: rotate(45deg);
      }

      p {
        padding-bottom: var(--space-4);
        color: var(--text-2);
        font-size: var(--text-base);
        line-height: 1.7;
      }
    }

    .cta__band {
      display: grid;
      gap: var(--space-4);
      justify-items: center;
      padding: var(--space-8) var(--space-5);
      overflow: hidden;
      border: 1px solid var(--border-accent);
      border-radius: var(--radius-2xl);
      background:
        radial-gradient(36rem 18rem at 50% 0%, rgb(52 211 153 / 18%), transparent 70%),
        var(--surface-1);
      text-align: center;
      box-shadow: var(--glow-accent);
    }

    .cta__buttons {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
      justify-content: center;
      margin-top: var(--space-2);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingResults {
  readonly data = input.required<Snapshot>();

  protected readonly docs = DOCS;
  protected readonly repo = REPO_URL;
  protected readonly faq = FAQ;
  protected readonly evaluation = computed(() => this.data().repo.evaluation);
  protected readonly failed = computed(() => this.data().api.rounding.failed);

  /** The document's cross-references ("see below") point inside it, not at this page. */
  protected cell(text: string): string {
    return text.replace(/,? see below\.?$/, '');
  }

  protected plain(text: string): string {
    return text.replace(/`/g, '');
  }
}

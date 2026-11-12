import { DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { describeError } from '../../core/api/api-error';
import { EmptyState, Skeleton } from '../../shared/ui/ui';
import { STATE_TONE } from '../overview/overview';
import {
  MODULE_STATE_TEXT,
  ModernizationService,
  ModuleSummary,
} from '../modernization/modernization.service';

type ViewState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; modules: ModuleSummary[] };

/** Every module of the approved plan, in migration order, with its latest verification. */
@Component({
  selector: 'app-module-list',
  imports: [DecimalPipe, EmptyState, RouterLink, Skeleton],
  template: `
    <div class="page-head">
      <div>
        <p class="eyebrow">Migration, in plan order</p>
        <h1 class="page-title">Modules</h1>
      </div>
    </div>
    <p class="page-lede">
      One module per program, created when an architect approves the plan. Every number here comes
      from a stored verification run.
    </p>
    @let current = state();
    @switch (current.kind) {
      @case ('loading') {
        <app-skeleton label="Loading modules…" variant="table" [count]="5" />
      }
      @case ('error') {
        <div class="state state--error" role="alert">
          <p>The modules could not be loaded. {{ current.message }}</p>
          <button class="button button--quiet" type="button" (click)="load()">Try again</button>
        </div>
      }
      @case ('ready') {
        @if (current.modules.length) {
          <div class="table-scroll" tabindex="0" role="region" aria-label="Modules">
            <table class="data-table">
              <thead>
                <tr>
                  <th scope="col">Step</th>
                  <th scope="col">Program</th>
                  <th scope="col">Service</th>
                  <th scope="col">State</th>
                  <th scope="col" class="num">Identical cases</th>
                  <th scope="col" class="num">Coverage</th>
                  <th scope="col" class="num">Mutation</th>
                  <th scope="col">Routing</th>
                </tr>
              </thead>
              <tbody>
                @for (module of current.modules; track module.id) {
                  <tr>
                    <td><span class="step">{{ module.order_index }}</span></td>
                    <th scope="row">
                      <a [routerLink]="['/app/projects', projectId(), 'modules', module.id]">{{
                        module.program
                      }}</a>
                    </th>
                    <td>{{ module.target_service }}</td>
                    <td>
                      <span [class]="'badge badge--dot badge--' + badgeTone[tone[module.state]]">{{
                        stateText[module.state]
                      }}</span>
                    </td>
                    <td class="num">
                      @if (module.latest_run; as run) {
                        <span class="result">
                          <span class="result__bar" aria-hidden="true"
                            ><span
                              [class.bad]="run.failed > 0"
                              [style.width.%]="(run.passed / run.cases) * 100"
                            ></span
                          ></span>
                          {{ run.passed }} of {{ run.cases }}
                        </span>
                      }
                    </td>
                    <td class="num">
                      @if (module.latest_run?.coverage_pct; as value) {
                        {{ value | number: '1.2-2' }}%
                      }
                    </td>
                    <td class="num">
                      @if (module.latest_run?.mutation_score; as value) {
                        {{ value | number: '1.2-2' }}%
                      }
                    </td>
                    <td><span class="mode" [class]="'mode mode--' + module.facade_mode.toLowerCase()">{{ module.facade_mode.toLowerCase() }}</span></td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else {
          <app-empty-state title="There are no modules yet." icon="blocks">
            They are created when an architect approves the
            <a [routerLink]="['/app/projects', projectId(), 'plan']">plan</a>.
          </app-empty-state>
        }
      }
    }
  `,
  styles: `
    .step {
      display: inline-grid;
      place-items: center;
      width: 1.75rem;
      height: 1.75rem;
      border: 1px solid var(--border-strong);
      border-radius: 50%;
      color: var(--text-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }

    .result {
      display: inline-flex;
      gap: var(--space-3);
      align-items: center;
      justify-content: flex-end;
      white-space: nowrap;
    }

    .result__bar {
      width: 4rem;
      height: 0.375rem;
      overflow: hidden;
      border-radius: var(--radius-pill);
      background: var(--danger);

      span {
        display: block;
        height: 100%;
        background: var(--ok);
      }
    }

    .mode {
      padding: 0.1rem 0.5rem;
      border-radius: var(--radius-sm);
      background: var(--surface-3);
      color: var(--text-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }

    .mode--modern {
      background: var(--ok-bg);
      color: var(--ok);
    }

    .mode--shadow {
      background: var(--violet-bg);
      color: var(--violet);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModuleList implements OnInit {
  private readonly api = inject(ModernizationService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly projectId = signal('');
  protected readonly state = signal<ViewState>({ kind: 'loading' });
  protected readonly stateText = MODULE_STATE_TEXT;
  protected readonly tone = STATE_TONE;
  protected readonly badgeTone: Record<string, string> = { good: 'ok', warn: 'warn', bad: 'danger', neutral: 'neutral' };

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.projectId.set(params.get('id') ?? '');
      this.load();
    });
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    this.api
      .modules(this.projectId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (modules) => this.state.set({ kind: 'ready', modules }),
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }
}

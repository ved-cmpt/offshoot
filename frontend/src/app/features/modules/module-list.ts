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
  imports: [DecimalPipe, RouterLink],
  template: `
    <div class="page-head">
      <h1 class="page-title">Modules</h1>
    </div>
    <p class="muted">
      One module per program, created when an architect approves the plan. Every number here comes
      from a stored verification run.
    </p>
    @let current = state();
    @switch (current.kind) {
      @case ('loading') {
        <p class="state" role="status">Loading modules…</p>
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
                    <td>{{ module.order_index }}</td>
                    <th scope="row">
                      <a [routerLink]="['/projects', projectId(), 'modules', module.id]">{{
                        module.program
                      }}</a>
                    </th>
                    <td>{{ module.target_service }}</td>
                    <td>{{ stateText[module.state] }}</td>
                    <td class="num">
                      @if (module.latest_run; as run) {
                        {{ run.passed }} of {{ run.cases }}
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
                    <td>{{ module.facade_mode.toLowerCase() }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        } @else {
          <div class="state">
            <p>There are no modules yet.</p>
            <p class="muted">
              They are created when an architect approves the
              <a [routerLink]="['/projects', projectId(), 'plan']">plan</a>.
            </p>
          </div>
        }
      }
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

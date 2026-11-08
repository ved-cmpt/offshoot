import { DOCUMENT } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';

import { describeError } from '../../core/api/api-error';
import { AssessmentReport, PromotionService } from '../modernization/modernization.service';

type ViewState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; report: AssessmentReport };

/**
 * The As-Is / To-Be / Transition assessment. Printable, with a print stylesheet, so the
 * browser's "save as PDF" gives the PDF (ADR-042). The Markdown comes from the same data.
 */
@Component({
  selector: 'app-report',
  template: `
    @let current = state();
    @switch (current.kind) {
      @case ('loading') {
        <h1 class="page-title">Assessment report</h1>
        <p class="state" role="status">Loading the report…</p>
      }
      @case ('error') {
        <h1 class="page-title">Assessment report</h1>
        <div class="state state--error" role="alert">
          <p>The report could not be loaded. {{ current.message }}</p>
          <button class="button button--quiet" type="button" (click)="load()">Try again</button>
        </div>
      }
      @case ('ready') {
        <article class="report">
          <div class="page-head">
            <h1 class="page-title">{{ current.report.title }}</h1>
            <div class="report__actions no-print">
              <button class="button button--quiet" type="button" (click)="download()">
                Download Markdown
              </button>
              <button class="button button--quiet" type="button" (click)="print()">
                Print or save as PDF
              </button>
            </div>
          </div>
          @if (downloadError(); as message) {
            <p class="state state--error no-print" role="alert">{{ message }}</p>
          }
          @for (section of current.report.sections; track section.heading) {
            <section class="panel report__section">
              <h2>{{ section.heading }}</h2>
              @for (paragraph of section.paragraphs; track $index) {
                <p>{{ paragraph }}</p>
              }
              @for (table of section.tables; track $index) {
                @if (table.rows.length) {
                  <div
                    class="table-scroll"
                    tabindex="0"
                    role="region"
                    [attr.aria-label]="section.heading + ', table ' + ($index + 1)"
                  >
                    <table class="data-table">
                      <thead>
                        <tr>
                          @for (column of table.columns; track column) {
                            <th scope="col">{{ column }}</th>
                          }
                        </tr>
                      </thead>
                      <tbody>
                        @for (row of table.rows; track $index) {
                          <tr>
                            @for (cell of row; track $index) {
                              <td>{{ cell }}</td>
                            }
                          </tr>
                        }
                      </tbody>
                    </table>
                  </div>
                }
              }
            </section>
          }
          <p class="muted">
            <em>{{ current.report.limits }}</em>
          </p>
        </article>
      }
    }
  `,
  styles: `
    .report__actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
    }

    .report__section p + p,
    .report__section p + .table-scroll,
    .report__section .table-scroll + .table-scroll {
      margin-top: var(--space-3);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReportPage implements OnInit {
  private readonly api = inject(PromotionService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly document = inject(DOCUMENT);

  protected readonly projectId = signal('');
  protected readonly state = signal<ViewState>({ kind: 'loading' });
  protected readonly downloadError = signal<string | null>(null);

  ngOnInit(): void {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.projectId.set(params.get('id') ?? '');
      this.load();
    });
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    this.api
      .report(this.projectId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (report) => this.state.set({ kind: 'ready', report }),
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }

  /** The access token lives in memory, so the file is fetched with it and saved from a blob. */
  protected download(): void {
    this.downloadError.set(null);
    this.api
      .reportMarkdown(this.projectId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          const view = this.document.defaultView;
          const url = view?.URL.createObjectURL(blob);
          if (!url) {
            return;
          }
          const link = this.document.createElement('a');
          link.href = url;
          link.download = 'assessment-report.md';
          link.click();
          view?.URL.revokeObjectURL(url);
        },
        error: (error: unknown) => this.downloadError.set(describeError(error)),
      });
  }

  protected print(): void {
    this.document.defaultView?.print();
  }
}

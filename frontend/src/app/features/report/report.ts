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
import { Icon } from '../../shared/icon/icon';
import { Skeleton } from '../../shared/ui/ui';
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
  imports: [Icon, Skeleton],
  template: `
    @let current = state();
    @switch (current.kind) {
      @case ('loading') {
        <h1 class="page-title">Assessment report</h1>
        <app-skeleton label="Loading the report…" [count]="8" />
      }
      @case ('error') {
        <h1 class="page-title">Assessment report</h1>
        <div class="state state--error" role="alert">
          <p>The report could not be loaded. {{ current.message }}</p>
          <button class="button button--quiet" type="button" (click)="load()">Try again</button>
        </div>
      }
      @case ('ready') {
        <div class="layout">
        <nav class="toc no-print" aria-label="Report contents">
          <p class="toc__title">Contents</p>
          <ol>
            @for (section of current.report.sections; track section.heading; let i = $index) {
              <li><a [href]="'#report-section-' + i" (click)="jump($event, i)">{{ section.heading }}</a></li>
            }
          </ol>
        </nav>
        <article class="report">
          <div class="page-head">
            <div>
              <p class="eyebrow">Assessment report</p>
              <h1 class="page-title">{{ current.report.title }}</h1>
            </div>
            <div class="report__actions no-print">
              <button class="button button--quiet" type="button" (click)="download()">
                <app-icon name="download" [size]="16" /> Download Markdown
              </button>
              <button class="button button--quiet" type="button" (click)="print()">
                <app-icon name="printer" [size]="16" /> Print or save as PDF
              </button>
            </div>
          </div>
          @if (downloadError(); as message) {
            <p class="state state--error no-print" role="alert">{{ message }}</p>
          }
          @for (section of current.report.sections; track section.heading; let i = $index) {
            <section class="panel report__section" [id]="'report-section-' + i">
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
          <p class="limits">
            <app-icon name="info" [size]="16" />
            <em>{{ current.report.limits }}</em>
          </p>
        </article>
        </div>
      }
    }
  `,
  styles: `
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-6);
      align-items: start;
    }

    @media (min-width: 80rem) {
      .layout {
        grid-template-columns: 13rem minmax(0, 1fr);
      }

      .toc {
        position: sticky;
        top: calc(var(--topbar-height) + var(--space-5));
      }
    }

    @media (max-width: 79.98rem) {
      .toc {
        display: none;
      }
    }

    .toc__title {
      margin-bottom: var(--space-2);
      color: var(--text-3);
      font-size: var(--text-xs);
      font-weight: 600;
    }

    .toc ol {
      display: grid;
      gap: var(--space-1);
      margin: 0;
      padding: 0;
      list-style: none;
      counter-reset: toc;
    }

    .toc a {
      display: block;
      padding: var(--space-1) var(--space-2);
      border-left: 2px solid var(--border);
      color: var(--text-2);
      font-size: var(--text-sm);
      text-decoration: none;

      &:hover {
        border-left-color: var(--accent);
        color: var(--text);
      }
    }

    .report {
      max-width: 60rem;
      counter-reset: section;
    }

    .report__section {
      scroll-margin-top: 5rem;

      h2 {
        display: flex;
        gap: var(--space-3);
        align-items: center;
      }

      p + p {
        margin-top: var(--space-2);
      }

      p {
        color: var(--text-2);
        line-height: 1.7;
      }

      .table-scroll {
        margin-top: var(--space-4);
      }
    }

    .report__section h2::before {
      counter-increment: section;
      content: counter(section);
      display: inline-grid;
      place-items: center;
      width: 1.75rem;
      height: 1.75rem;
      border-radius: var(--radius);
      background: var(--accent-soft);
      color: var(--accent-fg);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
    }

    .limits {
      display: flex;
      gap: var(--space-2);
      align-items: flex-start;
      padding: var(--space-4);
      border: 1px solid var(--info-border);
      border-radius: var(--radius-lg);
      background: var(--info-bg);
      color: var(--text-2);

      app-icon {
        margin-top: 0.2rem;
        color: var(--info);
      }
    }

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

  /** Contents links scroll to the section without changing the route. */
  protected jump(event: Event, index: number): void {
    event.preventDefault();
    this.document.getElementById(`report-section-${index}`)?.scrollIntoView?.({ block: 'start' });
  }

  protected print(): void {
    this.document.defaultView?.print();
  }
}

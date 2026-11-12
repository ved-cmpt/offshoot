import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { Language, Token, highlightLines } from './highlight';

export type LineMark = 'focus' | 'danger' | 'ok' | 'cited' | 'muted';

interface Rendered {
  number: number;
  tokens: Token[];
  mark: LineMark | null;
  note: string | null;
}

/**
 * Read-only code with line numbers, syntax colours and marked lines. Text only: every token is
 * rendered as text, never as markup (ADR-053). The body scrolls and can be reached by keyboard.
 */
@Component({
  selector: 'app-code-view',
  template: `
    <figure class="code" [class.code--flush]="flush()">
      @if (filename()) {
        <figcaption class="code__head">
          <span class="code__dots" aria-hidden="true"><i></i><i></i><i></i></span>
          <span class="code__file">{{ filename() }}</span>
          <span class="code__meta"><ng-content select="[codeMeta]" /></span>
        </figcaption>
      }
      <div
        class="code__body"
        tabindex="0"
        role="region"
        [attr.aria-label]="label()"
        [style.max-height]="maxHeight()"
      >
        <pre><code>@for (line of rendered(); track line.number) {<span class="code__line" [class]="line.mark ? 'code__line code__line--' + line.mark : 'code__line'">@if (numbers()) {<span class="code__ln" aria-hidden="true">{{ line.number }}</span>}<span class="code__text">@for (token of line.tokens; track $index) {<span [class]="'tok-' + token.kind">{{ token.text }}</span>}</span>@if (line.note) {<span class="code__note">{{ line.note }}</span>}</span>}</code></pre>
      </div>
    </figure>
  `,
  styles: `
    :host {
      display: block;
      min-width: 0;
    }

    .code {
      margin: 0;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background: var(--surface-inset);
    }

    .code--flush {
      border: 0;
      border-radius: 0;
    }

    .code__head {
      display: flex;
      gap: var(--space-3);
      align-items: center;
      min-height: 2.25rem;
      padding: 0 var(--space-3);
      border-bottom: 1px solid var(--border);
      background: var(--surface-2);
      color: var(--text-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }

    .code__dots {
      display: inline-flex;
      gap: 0.3rem;

      i {
        width: 0.5rem;
        height: 0.5rem;
        border-radius: 50%;
        background: var(--surface-3);
        box-shadow: inset 0 0 0 1px var(--border-strong);
      }
    }

    .code__file {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .code__meta {
      display: inline-flex;
      gap: var(--space-2);
      margin-left: auto;
    }

    .code__body {
      overflow: auto;
    }

    pre {
      margin: 0;
      padding: var(--space-3) 0;
      font-size: var(--text-sm);
      line-height: 1.65;
    }

    code {
      display: block;
      min-width: max-content;
      font-size: inherit;
    }

    .code__line {
      display: flex;
      padding-right: var(--space-4);
      border-left: 2px solid transparent;
    }

    .code__ln {
      flex: none;
      width: 3.25rem;
      padding-right: var(--space-3);
      color: var(--text-3);
      text-align: right;
      user-select: none;
    }

    .code__line--focus,
    .code__line--danger,
    .code__line--ok,
    .code__line--cited {
      .code__ln {
        color: var(--text-2);
      }
    }

    .code__text {
      padding-left: var(--space-1);
      white-space: pre;
    }

    .code__line:not(:has(.code__ln)) .code__text {
      padding-left: var(--space-4);
    }

    .code__note {
      margin-left: var(--space-4);
      padding: 0 var(--space-2);
      border-radius: var(--radius-pill);
      background: var(--surface-3);
      color: var(--text-2);
      font-family: var(--font-sans);
      font-size: var(--text-2xs);
      line-height: 1.65rem;
      white-space: nowrap;
    }

    .code__line--focus {
      border-left-color: var(--warn);
      background: var(--highlight);
    }

    .code__line--danger {
      border-left-color: var(--danger);
      background: var(--danger-bg);

      .code__note {
        background: var(--danger-bg);
        color: var(--danger);
      }
    }

    .code__line--ok {
      border-left-color: var(--ok);
      background: var(--ok-bg);

      .code__note {
        background: var(--ok-bg);
        color: var(--ok);
      }
    }

    .code__line--cited {
      border-left-color: var(--info);
      background: var(--info-bg);
    }

    .code__line--muted {
      opacity: 0.55;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CodeView {
  readonly lines = input.required<readonly string[]>();
  readonly language = input<Language>('plain');
  readonly start = input(1);
  readonly label = input.required<string>();
  readonly filename = input<string | null>(null);
  readonly marks = input<Readonly<Record<number, LineMark>>>({});
  readonly notes = input<Readonly<Record<number, string>>>({});
  readonly maxHeight = input<string | null>(null);
  readonly flush = input(false);
  /** Hide line numbers when the lines do not come from one file in order. */
  readonly numbers = input(true);

  protected readonly rendered = computed<Rendered[]>(() => {
    const tokens = highlightLines(this.lines(), this.language());
    const marks = this.marks();
    const notes = this.notes();
    return tokens.map((line, index) => {
      const number = this.start() + index;
      return { number, tokens: line, mark: marks[number] ?? null, note: notes[number] ?? null };
    });
  });
}

import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { Icon } from '../icon/icon';
import { IconName } from '../icon/icons';

/**
 * A loading placeholder in the shape of what is coming. It carries a status message for
 * assistive technology, so screens keep saying "Loading..." in words.
 */
@Component({
  selector: 'app-skeleton',
  template: `
    <div class="skeleton-block" role="status">
      <span class="visually-hidden">{{ label() }}</span>
      @switch (variant()) {
        @case ('cards') {
          <div class="cards" aria-hidden="true">
            @for (i of rows(); track i) {
              <div class="card-shape">
                <span class="skeleton w-40"></span>
                <span class="skeleton h-lg w-60"></span>
                <span class="skeleton w-80"></span>
              </div>
            }
          </div>
        }
        @case ('table') {
          <div class="table-shape" aria-hidden="true">
            <span class="skeleton h-md"></span>
            @for (i of rows(); track i) {
              <span class="skeleton"></span>
            }
          </div>
        }
        @default {
          <div class="lines" aria-hidden="true">
            @for (i of rows(); track i) {
              <span class="skeleton" [class.w-60]="i % 3 === 2"></span>
            }
          </div>
        }
      }
    </div>
  `,
  styles: `
    @use 'tokens' as t;

    .skeleton-block {
      margin-block: var(--space-4);
    }

    .cards {
      display: grid;
      gap: var(--space-4);

      @include t.up(t.$bp-md) {
        grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
      }
    }

    .card-shape,
    .table-shape,
    .lines {
      display: grid;
      gap: var(--space-3);
      padding: var(--space-5);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background: var(--surface-1);
    }

    .h-lg {
      height: 1.75rem;
    }

    .h-md {
      height: 1.25rem;
    }

    .w-40 {
      width: 40%;
    }

    .w-60 {
      width: 60%;
    }

    .w-80 {
      width: 80%;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Skeleton {
  readonly label = input('Loading…');
  readonly variant = input<'lines' | 'cards' | 'table'>('lines');
  readonly count = input(4);

  protected readonly rows = computed(() => Array.from({ length: this.count() }, (_, i) => i));
}

/** An empty state with a small original illustration, a title, a message and an optional action. */
@Component({
  selector: 'app-empty-state',
  imports: [Icon],
  template: `
    <div class="empty">
      <svg class="empty__art" viewBox="0 0 120 80" aria-hidden="true">
        <rect x="18" y="34" width="44" height="38" rx="8" class="block" />
        <rect x="26" y="44" width="22" height="4" rx="2" class="line" />
        <rect x="26" y="53" width="28" height="4" rx="2" class="line" />
        <rect x="26" y="62" width="14" height="4" rx="2" class="line" />
        <path d="M52 35 V28 C52 18 60 12 72 11" class="shoot" />
        <path d="M70 13 C71 4 80 1 94 2 C95 14 87 21 72 19 Z" class="leaf" />
        <circle cx="100" cy="56" r="14" class="ring" />
      </svg>
      <span class="empty__icon"><app-icon [name]="icon()" [size]="18" /></span>
      <h2 class="empty__title">{{ title() }}</h2>
      <p class="empty__body"><ng-content /></p>
      <div class="empty__actions"><ng-content select="[emptyActions]" /></div>
    </div>
  `,
  styles: `
    .empty {
      position: relative;
      display: grid;
      gap: var(--space-2);
      justify-items: center;
      padding: var(--space-7) var(--space-5);
      border: 1px dashed var(--border-strong);
      border-radius: var(--radius-xl);
      background: var(--surface-1);
      text-align: center;
    }

    .empty__art {
      width: 7.5rem;
      height: 5rem;
      margin-bottom: var(--space-2);
    }

    .block {
      fill: var(--surface-3);
    }

    .line {
      fill: var(--border-strong);
    }

    .shoot {
      fill: none;
      stroke: var(--accent);
      stroke-linecap: round;
      stroke-width: 4;
      opacity: 0.8;
    }

    .leaf {
      fill: var(--accent);
      opacity: 0.8;
    }

    .ring {
      fill: none;
      stroke: var(--border-strong);
      stroke-dasharray: 3 4;
      stroke-width: 2;
    }

    .empty__icon {
      position: absolute;
      top: var(--space-5);
      right: var(--space-5);
      color: var(--text-3);
    }

    .empty__title {
      font-size: var(--text-lg);
    }

    .empty__body {
      max-width: 32rem;
      color: var(--text-2);
    }

    .empty__actions:empty {
      display: none;
    }

    .empty__actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      justify-content: center;
      margin-top: var(--space-3);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EmptyState {
  readonly title = input.required<string>();
  readonly icon = input<IconName>('sprout');
}

/** A KPI card: a label, a big value, a note, and an optional bar from 0 to 100. */
@Component({
  selector: 'app-kpi',
  imports: [Icon],
  template: `
    <div class="kpi" [class]="'kpi kpi--' + tone()">
      <p class="kpi__label"><app-icon [name]="icon()" [size]="15" />{{ label() }}</p>
      <p class="kpi__value">{{ value() }}</p>
      @if (percent() !== null) {
        <div class="kpi__bar" aria-hidden="true"><span [style.width.%]="percent()"></span></div>
      }
      <p class="kpi__note"><ng-content /></p>
    </div>
  `,
  styles: `
    :host {
      display: block;
      min-width: 0;
    }

    .kpi {
      display: grid;
      gap: var(--space-2);
      height: 100%;
      padding: var(--space-5);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background:
        linear-gradient(180deg, rgb(255 255 255 / 2%), transparent 60%),
        var(--surface-1);
      box-shadow: var(--shadow-md);
    }

    .kpi__label {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      color: var(--text-2);
      font-size: var(--text-sm);
      font-weight: 500;

      app-icon {
        color: var(--text-3);
      }
    }

    .kpi__value {
      font-size: var(--text-3xl);
      font-weight: 650;
      letter-spacing: -0.03em;
      font-variant-numeric: tabular-nums;
      line-height: 1.1;
    }

    .kpi__bar {
      height: 0.375rem;
      overflow: hidden;
      border-radius: var(--radius-pill);
      background: var(--surface-3);

      span {
        display: block;
        height: 100%;
        border-radius: inherit;
        background: var(--gradient-accent);
      }
    }

    .kpi--danger .kpi__bar span {
      background: var(--danger);
    }

    .kpi__note {
      color: var(--text-3);
      font-size: var(--text-sm);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Kpi {
  readonly label = input.required<string>();
  readonly value = input.required<string>();
  readonly icon = input<IconName>('gauge');
  readonly percent = input<number | null>(null);
  readonly tone = input<'default' | 'danger'>('default');
}

import { ChangeDetectionStrategy, Component, Injectable, inject, signal } from '@angular/core';

import { Icon } from '../icon/icon';
import { IconName } from '../icon/icons';

export type ToastKind = 'ok' | 'error' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
}

const ICON: Record<ToastKind, IconName> = { ok: 'circle-check', error: 'circle-alert', info: 'info' };

/** Short confirmations of what just happened. Errors also stay on the page that caused them. */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private next = 1;
  readonly toasts = signal<Toast[]>([]);

  show(kind: ToastKind, title: string, detail?: string, ms = 5000): void {
    const toast: Toast = { id: this.next++, kind, title, detail };
    this.toasts.update((list) => [...list.slice(-3), toast]);
    setTimeout(() => this.dismiss(toast.id), ms);
  }

  ok(title: string, detail?: string): void {
    this.show('ok', title, detail);
  }

  error(title: string, detail?: string): void {
    this.show('error', title, detail, 8000);
  }

  info(title: string, detail?: string): void {
    this.show('info', title, detail);
  }

  dismiss(id: number): void {
    this.toasts.update((list) => list.filter((toast) => toast.id !== id));
  }
}

@Component({
  selector: 'app-toasts',
  imports: [Icon],
  template: `
    <div class="toasts" role="status" aria-live="polite">
      @for (toast of service.toasts(); track toast.id) {
        <div class="toast" [class]="'toast toast--' + toast.kind">
          <app-icon [name]="icon[toast.kind]" [size]="18" />
          <div class="toast__text">
            <p class="toast__title">{{ toast.title }}</p>
            @if (toast.detail) {
              <p class="toast__detail">{{ toast.detail }}</p>
            }
          </div>
          <button type="button" class="toast__close" (click)="service.dismiss(toast.id)" aria-label="Dismiss">
            <app-icon name="x" [size]="14" />
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    @use 'tokens' as t;

    .toasts {
      position: fixed;
      right: var(--space-4);
      bottom: var(--space-4);
      left: var(--space-4);
      z-index: 200;
      display: grid;
      gap: var(--space-2);
      justify-items: end;
      pointer-events: none;

      @include t.up(t.$bp-sm) {
        left: auto;
        width: 24rem;
      }
    }

    .toast {
      display: flex;
      gap: var(--space-3);
      align-items: flex-start;
      width: 100%;
      padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      background: var(--bg-elevated);
      box-shadow: var(--shadow-popover);
      pointer-events: auto;

      @include t.motion {
        animation: toast-in var(--dur-slow) var(--ease-out);
      }
    }

    @keyframes toast-in {
      from {
        opacity: 0;
        transform: translateY(8px) scale(0.98);
      }
    }

    .toast--ok > app-icon {
      color: var(--ok);
    }

    .toast--error > app-icon {
      color: var(--danger);
    }

    .toast--info > app-icon {
      color: var(--info);
    }

    .toast__text {
      flex: 1;
      min-width: 0;
    }

    .toast__title {
      color: var(--text);
      font-weight: 600;
    }

    .toast__detail {
      color: var(--text-2);
      font-size: var(--text-sm);
    }

    .toast__close {
      display: grid;
      place-items: center;
      width: 1.75rem;
      height: 1.75rem;
      border: 0;
      border-radius: var(--radius-sm);
      background: none;
      color: var(--text-3);
      cursor: pointer;

      &:hover {
        background: var(--surface-2);
        color: var(--text);
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Toasts {
  protected readonly service = inject(ToastService);
  protected readonly icon = ICON;
}

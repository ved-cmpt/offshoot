import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  model,
  viewChild,
} from '@angular/core';

import { Icon } from '../../shared/icon/icon';

export const SHORTCUTS: { keys: string[]; what: string }[] = [
  { keys: ['Ctrl', 'K'], what: 'Open the command palette (⌘K on a Mac)' },
  { keys: ['?'], what: 'Show these shortcuts' },
  { keys: ['G', 'P'], what: 'Go to projects' },
  { keys: ['G', 'O'], what: 'Go to the project overview' },
  { keys: ['G', 'I'], what: 'Go to the inventory' },
  { keys: ['G', 'R'], what: 'Go to the rules' },
  { keys: ['G', 'L'], what: 'Go to the plan' },
  { keys: ['G', 'M'], what: 'Go to the modules' },
  { keys: ['G', 'A'], what: 'Go to the audit log (architects and admins)' },
  { keys: ['T'], what: 'Switch between the dark and light themes' },
  { keys: ['['], what: 'Collapse or expand the sidebar' },
  { keys: ['Esc'], what: 'Close a dialog or menu' },
];

@Component({
  selector: 'app-shortcuts-dialog',
  imports: [Icon],
  template: `
    <dialog #dialog class="sheet" aria-labelledby="shortcuts-title" (close)="open.set(false)">
      @if (open()) {
      <div class="sheet__head">
        <h2 id="shortcuts-title"><app-icon name="keyboard" [size]="18" /> Keyboard shortcuts</h2>
        <button type="button" class="sheet__close" (click)="open.set(false)" aria-label="Close">
          <app-icon name="x" [size]="16" />
        </button>
      </div>
      <dl class="keys">
        @for (item of shortcuts; track item.what) {
          <div>
            <dt>
              @for (key of item.keys; track $index) {
                <kbd>{{ key }}</kbd>
              }
            </dt>
            <dd>{{ item.what }}</dd>
          </div>
        }
      </dl>
      <p class="sheet__note">Letter shortcuts are off while you type in a field.</p>
      }
    </dialog>
  `,
  styles: `
    .sheet {
      width: min(32rem, calc(100vw - 2rem));
      padding: 0;
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-xl);
      background: var(--bg-elevated);
      color: var(--text);
      box-shadow: var(--shadow-popover);

      &::backdrop {
        background: var(--overlay);
      }
    }

    .sheet__head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--space-4) var(--space-5);
      border-bottom: 1px solid var(--border);

      h2 {
        display: flex;
        gap: var(--space-2);
        align-items: center;
        font-size: var(--text-md);
      }
    }

    .sheet__close {
      display: grid;
      place-items: center;
      width: 2rem;
      height: 2rem;
      border: 0;
      border-radius: var(--radius);
      background: none;
      color: var(--text-2);
      cursor: pointer;

      &:hover {
        background: var(--surface-2);
      }
    }

    .keys {
      display: grid;
      gap: var(--space-1);
      margin: 0;
      padding: var(--space-3) var(--space-5);

      div {
        display: flex;
        gap: var(--space-4);
        align-items: center;
        padding: var(--space-1) 0;
      }

      dt {
        display: flex;
        flex: none;
        gap: var(--space-1);
        width: 6rem;
      }

      dd {
        color: var(--text-2);
      }
    }

    .sheet__note {
      padding: 0 var(--space-5) var(--space-4);
      color: var(--text-3);
      font-size: var(--text-sm);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ShortcutsDialog {
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  readonly open = model(false);
  protected readonly shortcuts = SHORTCUTS;

  constructor() {
    effect(() => {
      const dialog = this.dialog().nativeElement;
      if (this.open() && !dialog.open) {
        dialog.showModal?.();
      } else if (!this.open() && dialog.open) {
        dialog.close();
      }
    });
  }
}

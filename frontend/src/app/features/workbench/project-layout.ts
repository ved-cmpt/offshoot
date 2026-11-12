import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';

import { Icon } from '../../shared/icon/icon';
import { IconName } from '../../shared/icon/icons';

const SCREENS: { key: string; label: string; icon: IconName }[] = [
  { key: 'overview', label: 'Overview', icon: 'layout-dashboard' },
  { key: 'inventory', label: 'Inventory', icon: 'boxes' },
  { key: 'rules', label: 'Rules', icon: 'scroll-text' },
  { key: 'plan', label: 'Plan', icon: 'map' },
  { key: 'modules', label: 'Modules', icon: 'blocks' },
  { key: 'report', label: 'Report', icon: 'file-text' },
];

/**
 * The frame around one project's screens. On wide screens the sidebar holds the project's
 * navigation; below that, this strip of tabs does (only one of the two is ever shown).
 */
@Component({
  selector: 'app-project-layout',
  imports: [Icon, RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <nav class="tabs no-print" aria-label="Project">
      @for (screen of screens; track screen.key) {
        <a
          [routerLink]="['/app/projects', projectId(), screen.key]"
          routerLinkActive="tab--active"
          ariaCurrentWhenActive="page"
          class="tab"
        >
          <app-icon [name]="screen.icon" [size]="15" />{{ screen.label }}
        </a>
      }
    </nav>
    <router-outlet />
  `,
  styles: `
    @use 'tokens' as t;

    .tabs {
      display: flex;
      gap: var(--space-1);
      margin: calc(var(--space-2) * -1) calc(var(--space-4) * -1) var(--space-5);
      padding: 0 var(--space-4) var(--space-2);
      overflow-x: auto;
      border-bottom: 1px solid var(--border);
      scrollbar-width: none;

      @include t.up(t.$bp-lg) {
        display: none;
      }
    }

    .tab {
      display: inline-flex;
      flex: none;
      gap: var(--space-2);
      align-items: center;
      min-height: 2.25rem;
      padding: 0 var(--space-3);
      border-radius: var(--radius);
      color: var(--text-2);
      font-size: var(--text-sm);
      font-weight: 500;
      text-decoration: none;
    }

    .tab--active {
      background: var(--surface-3);
      color: var(--text);

      app-icon {
        color: var(--accent-fg);
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectLayout {
  private readonly route = inject(ActivatedRoute);

  protected readonly screens = SCREENS;
  protected readonly projectId = toSignal(
    this.route.paramMap.pipe(map((params) => params.get('id') ?? '')),
    { initialValue: '' },
  );
}

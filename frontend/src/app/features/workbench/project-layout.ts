import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';

/** The frame around one project's screens. */
@Component({
  selector: 'app-project-layout',
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <nav class="tabs" aria-label="Project">
      <a routerLink="/projects">All projects</a>
      <a
        [routerLink]="['/projects', projectId(), 'inventory']"
        routerLinkActive="tab--active"
        ariaCurrentWhenActive="page"
        >Inventory</a
      >
      <a
        [routerLink]="['/projects', projectId(), 'rules']"
        routerLinkActive="tab--active"
        ariaCurrentWhenActive="page"
        >Rules</a
      >
    </nav>
    <router-outlet />
  `,
  styles: `
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2) var(--space-5);
      margin-bottom: var(--space-5);
      padding-bottom: var(--space-2);
      border-bottom: 1px solid var(--color-border);
    }

    .tabs a {
      padding: var(--space-2) 0;
    }

    .tab--active {
      font-weight: 700;
      text-decoration-thickness: 2px;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectLayout {
  private readonly route = inject(ActivatedRoute);

  protected readonly projectId = toSignal(
    this.route.paramMap.pipe(map((params) => params.get('id') ?? '')),
    {
      initialValue: '',
    },
  );
}

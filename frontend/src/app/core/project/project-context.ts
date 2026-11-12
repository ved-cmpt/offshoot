import { Injectable, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, firstValueFrom, map } from 'rxjs';

import {
  ModernizationService,
  ModuleSummary,
} from '../../features/modernization/modernization.service';
import { Project, ProjectsService } from '../../features/projects/projects.service';
import { Rule, SourceSummary, WorkbenchService } from '../../features/workbench/workbench.service';

export type Screen =
  | 'projects'
  | 'audit'
  | 'overview'
  | 'inventory'
  | 'sources'
  | 'rules'
  | 'plan'
  | 'modules'
  | 'report'
  | null;

export interface Location {
  projectId: string | null;
  screen: Screen;
  itemId: string | null;
}

/** Where the app is, read from the address: /app/projects/:id/:screen/:item. */
export function parseLocation(url: string): Location {
  const path = url.split(/[?#]/)[0];
  if (path.startsWith('/app/admin/audit')) {
    return { projectId: null, screen: 'audit', itemId: null };
  }
  const match = /^\/app\/projects(?:\/([^/]+)(?:\/([^/]+)(?:\/([^/]+))?)?)?/.exec(path);
  if (!match) {
    return { projectId: null, screen: null, itemId: null };
  }
  const [, projectId, screen, itemId] = match;
  if (!projectId) {
    return { projectId: null, screen: 'projects', itemId: null };
  }
  return {
    projectId: decodeURIComponent(projectId),
    screen: (screen as Screen) ?? 'overview',
    itemId: itemId ? decodeURIComponent(itemId) : null,
  };
}

/**
 * The project the user is in, and lists the shell needs for breadcrumbs, the project switcher
 * and the command palette. Lists are fetched on demand and kept per project.
 */
@Injectable({ providedIn: 'root' })
export class ProjectContext {
  private readonly router = inject(Router);
  private readonly projectsApi = inject(ProjectsService);
  private readonly modernization = inject(ModernizationService);
  private readonly workbench = inject(WorkbenchService);

  readonly location = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => parseLocation(event.urlAfterRedirects)),
    ),
    { initialValue: parseLocation(this.router.url) },
  );
  readonly projectId = computed(() => this.location().projectId);

  readonly projects = signal<Project[] | null>(null);
  readonly modules = signal<{ projectId: string; items: ModuleSummary[] } | null>(null);
  readonly sources = signal<{ projectId: string; items: SourceSummary[] } | null>(null);
  readonly rules = signal<{ projectId: string; items: Rule[] } | null>(null);

  readonly project = computed(() => {
    const id = this.projectId();
    return this.projects()?.find((project) => project.id === id) ?? null;
  });

  /** The project the palette and the tour use: the open one, else the bundled demo project. */
  readonly workingProjectId = computed(() => {
    const open = this.projectId();
    if (open) {
      return open;
    }
    const list = this.projects() ?? [];
    const bundled = list.filter((project) => project.source_kind === 'BUNDLED');
    return (bundled.find((project) => project.name === 'BillRite') ?? bundled[0] ?? list[0])?.id ?? null;
  });

  readonly moduleName = computed(() => {
    const location = this.location();
    if (location.screen !== 'modules' || !location.itemId) {
      return null;
    }
    return this.modules()?.items.find((module) => module.id === location.itemId)?.program ?? null;
  });

  readonly sourceName = computed(() => {
    const location = this.location();
    if (location.screen !== 'sources' || !location.itemId) {
      return null;
    }
    return this.sources()?.items.find((source) => source.id === location.itemId)?.name ?? null;
  });

  async loadProjects(force = false): Promise<Project[]> {
    if (!this.projects() || force) {
      try {
        const page = await firstValueFrom(this.projectsApi.list());
        this.projects.set(page.items);
      } catch {
        this.projects.set(this.projects() ?? []);
      }
    }
    return this.projects() ?? [];
  }

  async loadModules(projectId: string): Promise<ModuleSummary[]> {
    const cached = this.modules();
    if (cached?.projectId === projectId) {
      return cached.items;
    }
    try {
      const items = await firstValueFrom(this.modernization.modules(projectId));
      this.modules.set({ projectId, items });
      return items;
    } catch {
      return [];
    }
  }

  async loadSources(projectId: string): Promise<SourceSummary[]> {
    const cached = this.sources();
    if (cached?.projectId === projectId) {
      return cached.items;
    }
    try {
      const page = await firstValueFrom(this.workbench.sources(projectId));
      this.sources.set({ projectId, items: page.items });
      return page.items;
    } catch {
      return [];
    }
  }

  async loadRules(projectId: string): Promise<Rule[]> {
    const cached = this.rules();
    if (cached?.projectId === projectId) {
      return cached.items;
    }
    try {
      const page = await firstValueFrom(this.workbench.rules(projectId, {}));
      this.rules.set({ projectId, items: page.items });
      return page.items;
    } catch {
      return [];
    }
  }

  /** Forget cached lists, for example after an approval changed a module's state. */
  invalidate(): void {
    this.modules.set(null);
    this.rules.set(null);
  }
}

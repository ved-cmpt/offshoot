import { inject } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { Project, ProjectsService } from '../../features/projects/projects.service';
import { ModernizationService } from '../../features/modernization/modernization.service';
import { WorkbenchService } from '../../features/workbench/workbench.service';
import { APP_HOME } from '../auth/auth.guard';

/** The demo project: the bundled BillRite sample, whatever its id is in this database. */
export function demoProject(projects: Project[]): Project | null {
  const bundled = projects.filter((project) => project.source_kind === 'BUNDLED');
  return (
    bundled.find((project) => project.name === 'BillRite') ??
    bundled[0] ??
    projects[0] ??
    null
  );
}

/**
 * Stable links into the demo by name rather than by id, because ids differ between databases
 * (the landing page's deep links use these, ADR-054):
 *
 *   /app/open/overview, /app/open/rules?program=RATECALC&flag=SPAN_INVALID,
 *   /app/open/module/RATECALC, /app/open/source/RATECALC.cbl?line=135
 *
 * Unknown names fall back to the project's overview, or to the project list.
 */
export const openGuard: CanActivateFn = async (route) => {
  const router = inject(Router);
  const projects = inject(ProjectsService);
  const modernization = inject(ModernizationService);
  const workbench = inject(WorkbenchService);
  const kind = route.paramMap.get('kind') ?? 'overview';
  const name = route.paramMap.get('name');
  const query = route.queryParams;

  const fallback = (projectId?: string): UrlTree =>
    projectId
      ? router.createUrlTree(['/app/projects', projectId, 'overview'])
      : router.parseUrl(APP_HOME);

  try {
    const page = await firstValueFrom(projects.list());
    const project = demoProject(page.items);
    if (!project) {
      return fallback();
    }
    const base = ['/app/projects', project.id];
    switch (kind) {
      case 'module': {
        const modules = await firstValueFrom(modernization.modules(project.id));
        const found = modules.find((item) => item.program === name);
        return found
          ? router.createUrlTree([...base, 'modules', found.id], { fragment: route.fragment ?? undefined })
          : router.createUrlTree([...base, 'modules']);
      }
      case 'source': {
        const sources = await firstValueFrom(workbench.sources(project.id));
        const found = sources.items.find((item) => item.name === name);
        return found
          ? router.createUrlTree([...base, 'sources', found.id], { queryParams: query })
          : fallback(project.id);
      }
      case 'rules':
        return router.createUrlTree([...base, 'rules'], { queryParams: query });
      case 'overview':
      case 'inventory':
      case 'plan':
      case 'modules':
      case 'report':
        return router.createUrlTree([...base, kind]);
      default:
        return fallback(project.id);
    }
  } catch {
    return fallback();
  }
};

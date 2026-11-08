import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [guestGuard],
    title: 'Sign in - Offshoot',
    loadComponent: () => import('./features/login/login').then((m) => m.Login),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./features/shell/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'projects' },
      {
        path: 'projects',
        title: 'Projects - Offshoot',
        loadComponent: () => import('./features/projects/projects').then((m) => m.Projects),
      },
      {
        path: 'admin/audit',
        title: 'Audit log - Offshoot',
        loadComponent: () => import('./features/audit/audit').then((m) => m.AuditLog),
      },
      {
        path: 'projects/:id',
        loadComponent: () =>
          import('./features/workbench/project-layout').then((m) => m.ProjectLayout),
        children: [
          { path: '', pathMatch: 'full', redirectTo: 'overview' },
          {
            path: 'overview',
            title: 'Overview - Offshoot',
            loadComponent: () => import('./features/overview/overview').then((m) => m.Overview),
          },
          {
            path: 'report',
            title: 'Assessment report - Offshoot',
            loadComponent: () => import('./features/report/report').then((m) => m.ReportPage),
          },
          {
            path: 'inventory',
            title: 'Inventory - Offshoot',
            loadComponent: () => import('./features/inventory/inventory').then((m) => m.Inventory),
          },
          {
            path: 'sources/:file',
            title: 'Source - Offshoot',
            loadComponent: () =>
              import('./features/sources/source-viewer').then((m) => m.SourceViewer),
          },
          {
            path: 'rules',
            title: 'Rules - Offshoot',
            loadComponent: () => import('./features/rules/rules').then((m) => m.Rules),
          },
          {
            path: 'plan',
            title: 'Plan - Offshoot',
            loadComponent: () => import('./features/plan/plan').then((m) => m.PlanPage),
          },
          {
            path: 'modules',
            title: 'Modules - Offshoot',
            loadComponent: () => import('./features/modules/module-list').then((m) => m.ModuleList),
          },
          {
            path: 'modules/:mid',
            title: 'Module - Offshoot',
            loadComponent: () =>
              import('./features/modules/module-workspace').then((m) => m.ModuleWorkspace),
          },
        ],
      },
    ],
  },
  { path: '**', redirectTo: '' },
];

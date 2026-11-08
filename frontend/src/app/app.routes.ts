import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [guestGuard],
    title: 'Sign in - ParityForge',
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
        title: 'Projects - ParityForge',
        loadComponent: () => import('./features/projects/projects').then((m) => m.Projects),
      },
      {
        path: 'projects/:id',
        loadComponent: () =>
          import('./features/workbench/project-layout').then((m) => m.ProjectLayout),
        children: [
          { path: '', pathMatch: 'full', redirectTo: 'inventory' },
          {
            path: 'inventory',
            title: 'Inventory - ParityForge',
            loadComponent: () => import('./features/inventory/inventory').then((m) => m.Inventory),
          },
          {
            path: 'sources/:file',
            title: 'Source - ParityForge',
            loadComponent: () =>
              import('./features/sources/source-viewer').then((m) => m.SourceViewer),
          },
          {
            path: 'rules',
            title: 'Rules - ParityForge',
            loadComponent: () => import('./features/rules/rules').then((m) => m.Rules),
          },
        ],
      },
    ],
  },
  { path: '**', redirectTo: '' },
];

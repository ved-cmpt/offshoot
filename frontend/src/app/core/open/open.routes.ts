import { Routes } from '@angular/router';

import { openGuard } from './open.guard';

/** Links into the demo by name (ADR-052). Loaded on demand, so the landing page never ships them. */
export const OPEN_ROUTES: Routes = [
  { path: ':kind/:name', canActivate: [openGuard], children: [] },
  { path: ':kind', canActivate: [openGuard], children: [] },
];

import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

export const APP_HOME = '/app/projects';
export const LOGIN = '/app/login';

/**
 * Convenience for navigation only: the server enforces every permission. The guards restore a
 * session from the refresh cookie the first time the app is opened, so the public landing page
 * never waits for it (ADR-052).
 */
export const authGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.ensureSession();
  if (auth.isSignedIn()) {
    return true;
  }
  // The app's front door needs no return address.
  const home = ['/app', '/app/', APP_HOME].includes(state.url);
  return router.createUrlTree([LOGIN], { queryParams: home ? {} : { returnUrl: state.url } });
};

export const guestGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.ensureSession();
  return auth.isSignedIn() ? router.createUrlTree([APP_HOME]) : true;
};

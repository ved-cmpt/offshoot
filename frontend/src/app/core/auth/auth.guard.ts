import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

/** Convenience for navigation only. The server enforces every permission. */
export const authGuard: CanActivateFn = (_route, state) => {
  if (inject(AuthService).isSignedIn()) {
    return true;
  }
  return inject(Router).createUrlTree(['/login'], {
    queryParams: state.url === '/' ? {} : { returnUrl: state.url },
  });
};

export const guestGuard: CanActivateFn = () =>
  inject(AuthService).isSignedIn() ? inject(Router).createUrlTree(['/projects']) : true;

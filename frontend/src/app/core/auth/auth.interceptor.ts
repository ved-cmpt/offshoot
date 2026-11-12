import {
  HttpErrorResponse,
  HttpHandlerFn,
  HttpInterceptorFn,
  HttpRequest,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';

import { AUTH_API, AuthService } from './auth.service';

const API_PREFIX = '/api/v1/';
// These establish a session themselves, so they neither carry a token nor trigger a refresh.
const SESSION_ENDPOINTS = [`${AUTH_API}/login`, `${AUTH_API}/refresh`, `${AUTH_API}/logout`];

function withToken(request: HttpRequest<unknown>, token: string): HttpRequest<unknown> {
  return request.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}

export const authInterceptor: HttpInterceptorFn = (
  request: HttpRequest<unknown>,
  next: HttpHandlerFn,
) => {
  if (!request.url.startsWith(API_PREFIX) || SESSION_ENDPOINTS.includes(request.url)) {
    return next(request);
  }

  const auth = inject(AuthService);
  const router = inject(Router);
  const token = auth.token;
  const outgoing = token ? withToken(request, token) : request;

  return next(outgoing).pipe(
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
        return throwError(() => error);
      }
      // One refresh, one retry. A 401 on the retry is passed on, so this cannot loop.
      return auth.refresh().pipe(
        catchError((refreshError: unknown) => {
          auth.clear();
          void router.navigate(['/app/login'], { queryParams: { returnUrl: router.url } });
          return throwError(() => refreshError);
        }),
        switchMap((newToken) => next(withToken(request, newToken))),
      );
    }),
  );
};

import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, finalize, firstValueFrom, from, map, shareReplay, tap } from 'rxjs';

export const AUTH_API = '/api/v1/auth';
const CSRF_HEADERS = { 'X-ParityForge-CSRF': '1' };
const REFRESH_LOCK = 'parityforge-refresh';

export type Role = 'VIEWER' | 'ENGINEER' | 'ARCHITECT' | 'ADMIN';

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
}

export interface Session {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

/**
 * Session state. The access token is held only in this object's memory, never in
 * browser storage, so a script injected into a page has nothing lasting to steal.
 * The refresh token is in an HttpOnly cookie this code cannot read.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  private accessToken: string | null = null;
  private refreshInFlight: Observable<string> | null = null;
  private readonly currentUser = signal<User | null>(null);

  readonly user = this.currentUser.asReadonly();
  readonly isSignedIn = computed(() => this.currentUser() !== null);

  get token(): string | null {
    return this.accessToken;
  }

  login(email: string, password: string): Observable<User> {
    return this.http.post<Session>(`${AUTH_API}/login`, { email, password }).pipe(
      tap((session) => this.adopt(session)),
      map((session) => session.user),
    );
  }

  /**
   * Exchange the refresh cookie for a new access token. Callers that arrive while
   * one exchange is running share it: the cookie rotates on every use, and using
   * an old one looks like theft to the server and ends the session.
   */
  refresh(): Observable<string> {
    if (!this.refreshInFlight) {
      this.refreshInFlight = from(this.exchangeAcrossTabs()).pipe(
        tap((session) => this.adopt(session)),
        map((session) => session.access_token),
        finalize(() => (this.refreshInFlight = null)),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    }
    return this.refreshInFlight;
  }

  /** Called once at startup. A visitor with no session is a normal outcome, not an error. */
  async restoreSession(): Promise<void> {
    try {
      await firstValueFrom(this.refresh());
    } catch {
      this.clear();
    }
  }

  logout(): Observable<void> {
    return this.http
      .post<void>(`${AUTH_API}/logout`, null, { headers: CSRF_HEADERS })
      .pipe(finalize(() => this.clear()));
  }

  clear(): void {
    this.accessToken = null;
    this.currentUser.set(null);
  }

  private adopt(session: Session): void {
    this.accessToken = session.access_token;
    this.currentUser.set(session.user);
  }

  private exchange(): Promise<Session> {
    return firstValueFrom(
      this.http.post<Session>(`${AUTH_API}/refresh`, null, { headers: CSRF_HEADERS }),
    );
  }

  /** Two tabs share one cookie, so their exchanges must not overlap. */
  private exchangeAcrossTabs(): Promise<Session> {
    const locks = globalThis.navigator?.locks;
    return locks ? locks.request(REFRESH_LOCK, () => this.exchange()) : this.exchange();
  }
}

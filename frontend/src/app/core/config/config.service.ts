import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, shareReplay } from 'rxjs';

import { Role } from '../auth/auth.service';

export interface DemoAccount {
  username: string;
  email: string;
  password: string;
  display_name: string;
  role: Role;
}

export interface PublicConfig {
  demo_mode: boolean;
  ai_mode: string;
  demo_accounts: DemoAccount[];
  /** False on the public demo: no code is compiled or run there (ADR-047). Absent means true. */
  execution_enabled?: boolean;
  /** Hours between automatic demo resets; 0 or absent means none. */
  demo_reset_hours?: number;
}

@Injectable({ providedIn: 'root' })
export class ConfigService {
  private readonly http = inject(HttpClient);
  private cached: Observable<PublicConfig> | null = null;

  load(): Observable<PublicConfig> {
    if (!this.cached) {
      this.cached = this.http
        .get<PublicConfig>('/api/v1/config')
        .pipe(shareReplay({ bufferSize: 1, refCount: false }));
    }
    return this.cached;
  }

  /** Forget a failed or stale result so that the next load asks the server again. */
  reset(): void {
    this.cached = null;
  }
}

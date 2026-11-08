import { DatePipe, JsonPipe } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { AuthService } from '../../core/auth/auth.service';

export interface AuditEntry {
  id: number;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  safe_metadata: Record<string, unknown>;
  occurred_at: string;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
  actions: string[];
  entity_types: string[];
}

type ViewState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; page: AuditPage };

const PAGE_SIZE = 50;

/** The append-only audit log: every AI proposal, job and human decision. Architects and admins. */
@Component({
  selector: 'app-audit',
  imports: [DatePipe, JsonPipe],
  templateUrl: './audit.html',
  styles: `
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
      margin-block: var(--space-3);

      label {
        display: grid;
        gap: var(--space-1);
      }
    }

    .pager {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-3);
      margin-top: var(--space-3);
    }

    pre {
      margin: 0;
      max-width: 32rem;
      font-size: var(--text-sm);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditLog implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private loading: Subscription | null = null;

  protected readonly state = signal<ViewState>({ kind: 'loading' });
  protected readonly prefix = signal('');
  protected readonly entityType = signal('');
  protected readonly offset = signal(0);
  protected readonly pageSize = PAGE_SIZE;
  protected readonly allowed = computed(() => {
    const role = this.auth.user()?.role;
    return role === 'ARCHITECT' || role === 'ADMIN';
  });
  protected readonly prefixes = computed(() => {
    const state = this.state();
    const actions = state.kind === 'ready' ? state.page.actions : [];
    return [...new Set(actions.map((action) => action.split('.')[0] + '.'))];
  });

  ngOnInit(): void {
    if (this.allowed()) {
      this.load();
    }
  }

  protected load(): void {
    this.state.set({ kind: 'loading' });
    let params = new HttpParams().set('limit', PAGE_SIZE).set('offset', this.offset());
    if (this.prefix()) {
      params = params.set('action_prefix', this.prefix());
    }
    if (this.entityType()) {
      params = params.set('entity_type', this.entityType());
    }
    this.loading?.unsubscribe();
    this.loading = this.http
      .get<AuditPage>('/api/v1/admin/audit', { params })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (page) => this.state.set({ kind: 'ready', page }),
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }

  protected filter(kind: 'prefix' | 'entityType', value: string): void {
    this[kind].set(value);
    this.offset.set(0);
    this.load();
  }

  protected goTo(offset: number): void {
    this.offset.set(Math.max(0, offset));
    this.load();
  }
}

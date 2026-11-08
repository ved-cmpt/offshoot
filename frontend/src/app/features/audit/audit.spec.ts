import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { AuthService, Role } from '../../core/auth/auth.service';
import { authAs } from '../workbench/testing';
import { AuditLog, AuditPage } from './audit';

const PAGE: AuditPage = {
  items: [
    {
      id: 9,
      actor_id: 'u1',
      actor_name: 'Ari Architect',
      action: 'module.decision',
      entity_type: 'module',
      entity_id: 'abcdef1234',
      safe_metadata: { decision: 'APPROVED' },
      occurred_at: '2026-11-08T07:00:00Z',
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
  actions: ['facade.mode', 'module.decision', 'plan.decision'],
  entity_types: ['module', 'plan'],
};

describe('AuditLog', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<AuditLog>;
  let page: HTMLElement;

  function create(role: Role): void {
    TestBed.configureTestingModule({
      imports: [AuditLog],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authAs(role) },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AuditLog);
    page = fixture.nativeElement;
    fixture.detectChanges();
  }

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  afterEach(() => http.verify());

  it('lists entries with who did what', async () => {
    create('ARCHITECT');
    http.expectOne('/api/v1/admin/audit?limit=50&offset=0').flush(PAGE);
    await settle();
    const row = page.querySelector('tbody tr')!.textContent!;
    expect(row).toContain('module.decision');
    expect(row).toContain('Ari Architect');
    expect(row).toContain('APPROVED');
  });

  it('filters by action family and entity', async () => {
    create('ADMIN');
    http.expectOne('/api/v1/admin/audit?limit=50&offset=0').flush(PAGE);
    await settle();
    const [action, entity] = [...page.querySelectorAll('select')];
    action.value = 'facade.';
    action.dispatchEvent(new Event('change'));
    http.expectOne('/api/v1/admin/audit?limit=50&offset=0&action_prefix=facade.').flush(PAGE);
    await settle();
    entity.value = 'plan';
    entity.dispatchEvent(new Event('change'));
    http
      .expectOne('/api/v1/admin/audit?limit=50&offset=0&action_prefix=facade.&entity_type=plan')
      .flush({ ...PAGE, items: [] });
    await settle();
    expect(page.textContent).toContain('No entries match these filters.');
  });

  it('tells other roles it is not for them and asks for nothing', () => {
    create('ENGINEER');
    expect(page.querySelector('[role="alert"]')?.textContent).toContain(
      'Only architects and admins',
    );
  });
});

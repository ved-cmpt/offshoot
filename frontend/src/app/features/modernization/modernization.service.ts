import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { Job } from '../workbench/workbench.service';

export type PlanState = 'PROPOSED' | 'APPROVED' | 'REJECTED';

export interface PlanService {
  name: string;
  description: string;
  programs: string[];
}

export interface PlanStep {
  position: number;
  program: string;
  service: string;
  depends_on: string[];
  reason: string;
}

export interface PlanRisk {
  title: string;
  detail: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  programs: string[];
}

export interface EstimateRow {
  program: string;
  code_lines: number;
  decisions: number;
  traps: number;
  verified_rules: number;
  points: number;
}

export interface Plan {
  id: string;
  version: number;
  state: PlanState;
  services: PlanService[];
  order: PlanStep[];
  risks: PlanRisk[];
  estimate: { method: string; modules: EstimateRow[]; total_points: number };
  signals: { risk_signals?: { program: string; signal: string; detail: string }[]; notes?: string };
  prompt_version: string | null;
  model_id: string | null;
  created_at: string;
  decided_at: string | null;
  decided_by_name: string | null;
  decision_reason: string | null;
}

export interface PlanView {
  plan: Plan | null;
  history: { version: number; state: PlanState; created_at: string }[];
}

export type ModuleState =
  | 'PENDING'
  | 'MIGRATING'
  | 'BUILD_FAILED'
  | 'VERIFYING'
  | 'BLOCKED'
  | 'VERIFIED'
  | 'APPROVED'
  | 'REJECTED';

export type FacadeMode = 'LEGACY' | 'SHADOW' | 'MODERN';

export interface ArtifactSummary {
  id: string;
  version: number;
  kind: 'MIGRATION' | 'REPAIR';
  attempt: number;
  build_status: string;
  sha256: string;
  files: string[];
  rule_ids: string[];
  notes: string | null;
  model_id: string | null;
  prompt_version: string | null;
  created_at: string;
}

export interface Diagnostic {
  file: string;
  line: number;
  column: number;
  severity: 'error' | 'warning';
  id: string;
  message: string;
}

export interface BuildReport {
  contract?: { unknown_rule_refs: string[] };
  build?: {
    ok: boolean;
    errors?: number;
    warnings?: number;
    diagnostics?: Diagnostic[];
    policy_violations?: Diagnostic[];
    timed_out?: boolean;
    out_of_memory?: boolean;
    output_tail?: string;
  } | null;
  tests?: {
    ok: boolean;
    total: number;
    passed: number;
    failed: number;
    failed_tests: string[];
    timed_out?: boolean;
    out_of_memory?: boolean;
    output_tail?: string;
  } | null;
}

export interface ArtifactDetail extends ArtifactSummary {
  module_id: string;
  parent_id: string | null;
  file_contents: { path: string; content: string }[];
  build_report: BuildReport;
}

export interface RunSummary {
  id: string;
  kind: 'FULL' | 'MUTATION';
  status: 'PASSED' | 'FAILED';
  seed: number;
  cases: number;
  passed: number;
  failed: number;
  coverage_pct: number | null;
  mutation_score: number | null;
  artifact_id: string | null;
  artifact_version: number | null;
  job_id: string | null;
  created_at: string;
}

export interface FieldDiff {
  field: string;
  legacy: string | null;
  modern: string | null;
  legacy_raw: string;
  modern_raw: string;
}

export interface Mismatch {
  case: number;
  source: string;
  label: string;
  input: string;
  input_fields: Record<string, string | null>;
  legacy: string;
  modern: string;
  diffs: FieldDiff[];
}

export interface MutationReport {
  tool?: string;
  score?: number | null;
  counts?: Record<string, number>;
  valid_mutants?: number;
  detected?: number;
  total_mutants?: number;
  survivors?: {
    file: string;
    line: number | null;
    mutator: string;
    replacement: string;
    status: string;
  }[];
  skipped?: string;
  error?: string;
}

export interface RunReport {
  seed: number;
  program: string;
  cases: number;
  passed: number;
  failed: number;
  pass_pct: number;
  by_source: Record<string, number>;
  failed_by_source: Record<string, number>;
  mismatched_fields: Record<string, number>;
  mismatches: Mismatch[];
  coverage: { pct: number | null; paragraphs: number; hit: string[]; missed: string[] };
  rules: {
    verified: number;
    exercised: { id: string; title: string; cases: number }[];
    not_exercised: { id: string; title: string }[];
  };
  mutation: MutationReport;
  artifact: { id: string; version: number; sha256: string };
  versions: Record<string, unknown>;
}

export interface Gate {
  gate: 'BUILD' | 'UNIT_TESTS' | 'EQUIVALENCE' | 'COVERAGE' | 'MUTATION';
  label: string;
  passed: boolean;
  value: number | null;
  threshold: number;
  unit: string;
  exception?: { threshold: number; reason: string; by: string | null; at: string | null };
}

export interface RunDetail extends RunSummary {
  report: RunReport & { mutation: MutationReport };
  gates: Gate[];
  base_run_id: string | null;
}

export interface ModuleSummary {
  id: string;
  project_id: string;
  program: string;
  target_service: string | null;
  order_index: number;
  state: ModuleState;
  state_reason: string | null;
  facade_mode: FacadeMode;
  version: number;
  current_artifact: ArtifactSummary | null;
  latest_run: RunSummary | null;
  repairs_used: number;
  repairs_remaining: number;
  migratable: boolean;
  active_job: Job | null;
  updated_at: string;
}

export interface ModuleDetail extends ModuleSummary {
  gates: Gate[];
  thresholds: {
    coverage: number;
    mutation: number;
    exceptions: Record<string, { threshold: number; reason: string; by: string | null }>;
  };
  verified_rules: number;
  shadow: ShadowStatus;
  decision: { decision: string; reason: string | null; by: string | null; at: string } | null;
  approvable: boolean;
}

export type ModuleAction = 'migrate' | 'repair' | 'verify' | 'mutate';

export const MODULE_STATE_TEXT: Record<ModuleState, string> = {
  PENDING: 'Not migrated yet',
  MIGRATING: 'Migrating',
  BUILD_FAILED: 'Build failed',
  VERIFYING: 'Verifying',
  BLOCKED: 'Blocked by verification',
  VERIFIED: 'Verified, awaiting approval',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
};

const REASON_TEXT: Record<string, string> = {
  EQUIVALENCE_FAILED: 'Some cases gave a different result from the legacy program.',
  COVERAGE_FAILED: 'The cases did not exercise enough of the legacy program.',
  MUTATION_FAILED: 'The mutation score is below its threshold.',
  BUILD_FAILED: 'The generated code did not compile.',
  UNIT_TESTS_FAILED: 'The generated unit tests did not pass.',
  TESTS_FAILED: 'The generated unit tests did not pass.',
  POLICY_VIOLATION: 'The generated code used an API the sandbox forbids.',
  SANDBOX_TIMEOUT: 'The generated code ran past its time limit and was stopped.',
  SANDBOX_MEMORY_LIMIT: 'The generated code ran past its memory limit and was stopped.',
  MODERN_RUN_FAILED: 'The generated module did not answer every case.',
  LEGACY_SOURCE_MISMATCH: 'The project sources differ from the legacy program the runner executes.',
  AI_INVALID_OUTPUT: 'The agent returned output that broke its contract, so nothing was kept.',
  AI_UNAVAILABLE: 'The agent could not be reached.',
  AI_REQUEST_REJECTED: 'The agent refused the request. Trying again will not help.',
};

export function describeReason(code: string | null): string {
  return code ? (REASON_TEXT[code] ?? `Reason code ${code}.`) : '';
}

@Injectable({ providedIn: 'root' })
export class ModernizationService {
  private readonly http = inject(HttpClient);

  private project(id: string): string {
    return `/api/v1/projects/${encodeURIComponent(id)}`;
  }

  private module(id: string): string {
    return `/api/v1/modules/${encodeURIComponent(id)}`;
  }

  plan(projectId: string): Observable<PlanView> {
    return this.http.get<PlanView>(`${this.project(projectId)}/plan`);
  }

  proposePlan(projectId: string): Observable<Job> {
    return this.http.post<Job>(`${this.project(projectId)}/plan`, null);
  }

  decidePlan(
    projectId: string,
    plan: Plan,
    decision: 'APPROVED' | 'REJECTED',
    reason: string | null,
  ): Observable<Plan> {
    return this.http.post<Plan>(`${this.project(projectId)}/plan/decision`, {
      decision,
      expected_version: plan.version,
      reason,
    });
  }

  modules(projectId: string): Observable<ModuleSummary[]> {
    return this.http.get<ModuleSummary[]>(`${this.project(projectId)}/modules`);
  }

  moduleDetail(moduleId: string): Observable<ModuleDetail> {
    return this.http.get<ModuleDetail>(this.module(moduleId));
  }

  artifacts(moduleId: string): Observable<ArtifactSummary[]> {
    return this.http.get<ArtifactSummary[]>(`${this.module(moduleId)}/artifacts`);
  }

  artifact(moduleId: string, version: number): Observable<ArtifactDetail> {
    return this.http.get<ArtifactDetail>(`${this.module(moduleId)}/artifacts/${version}`);
  }

  runs(moduleId: string): Observable<RunSummary[]> {
    return this.http.get<RunSummary[]>(`${this.module(moduleId)}/runs`);
  }

  run(moduleId: string, runId: string): Observable<RunDetail> {
    return this.http.get<RunDetail>(`${this.module(moduleId)}/runs/${encodeURIComponent(runId)}`);
  }

  start(moduleId: string, action: ModuleAction): Observable<Job> {
    return this.http.post<Job>(`${this.module(moduleId)}/${action}`, null);
  }

  addGateException(
    module: ModuleDetail,
    gate: 'COVERAGE' | 'MUTATION',
    threshold: number,
    reason: string,
  ): Observable<ModuleDetail> {
    return this.http.post<ModuleDetail>(`${this.module(module.id)}/gate-exceptions`, {
      gate,
      threshold,
      reason,
      expected_version: module.version,
    });
  }
}

export interface ShadowStatus {
  compared: number;
  mismatches: number;
  sample: number;
  ready: boolean;
  since: string | null;
}

export interface ShadowView {
  status: ShadowStatus;
  mismatches: { id: string; request_hash: string; diff: Mismatch; created_at: string }[];
}

export interface DashboardModule {
  id: string;
  program: string;
  service: string | null;
  state: ModuleState;
  facade_mode: FacadeMode;
  cases: number | null;
  passed: number | null;
  failed: number | null;
  coverage_pct: number | null;
  mutation_score: number | null;
  run_id: string | null;
  shadow_compared: number;
  shadow_mismatches: number;
}

export interface ActivityEvent {
  kind: 'job' | 'decision';
  what: string;
  outcome: string;
  by: string | null;
  seeded?: boolean;
  at: string;
}

export interface Dashboard {
  project: { id: string; name: string; source_kind: string };
  modules: DashboardModule[];
  modules_by_state: Partial<Record<ModuleState, number>>;
  facade_modes: Partial<Record<FacadeMode, number>>;
  rules: {
    total: number;
    by_state: Record<string, number>;
    verified: number;
    verified_pct: number | null;
    decisions: number;
    seeded_decisions: number;
    human_decisions: number;
  };
  equivalence: { modules_verified: number; cases: number; identical: number };
  ai: {
    calls: number;
    failed: number;
    by_mode: Record<string, number>;
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
    note: string;
  };
  activity: ActivityEvent[];
}

export interface ReportSection {
  heading: string;
  paragraphs: string[];
  tables: { columns: string[]; rows: string[][] }[];
}

export interface AssessmentReport {
  title: string;
  sections: ReportSection[];
  limits: string;
  markdown: string;
}

@Injectable({ providedIn: 'root' })
export class PromotionService {
  private readonly http = inject(HttpClient);

  private module(id: string): string {
    return `/api/v1/modules/${encodeURIComponent(id)}`;
  }

  dashboard(projectId: string): Observable<Dashboard> {
    return this.http.get<Dashboard>(`/api/v1/projects/${encodeURIComponent(projectId)}/dashboard`);
  }

  report(projectId: string): Observable<AssessmentReport> {
    return this.http.get<AssessmentReport>(
      `/api/v1/projects/${encodeURIComponent(projectId)}/report`,
    );
  }

  reportMarkdown(projectId: string): Observable<Blob> {
    return this.http.get(`/api/v1/projects/${encodeURIComponent(projectId)}/report.md`, {
      responseType: 'blob',
    });
  }

  decide(
    module: ModuleDetail,
    decision: 'APPROVED' | 'REJECTED',
    reason: string | null,
  ): Observable<ModuleDetail> {
    return this.http.post<ModuleDetail>(`${this.module(module.id)}/decision`, {
      decision,
      expected_version: module.version,
      reason,
    });
  }

  setMode(module: ModuleDetail, mode: FacadeMode, reason: string | null): Observable<ModuleDetail> {
    return this.http.post<ModuleDetail>(`${this.module(module.id)}/facade-mode`, {
      mode,
      expected_version: module.version,
      reason,
    });
  }

  replay(moduleId: string): Observable<Job> {
    return this.http.post<Job>(`${this.module(moduleId)}/shadow-replay`, null);
  }

  shadow(moduleId: string): Observable<ShadowView> {
    return this.http.get<ShadowView>(`${this.module(moduleId)}/shadow`);
  }
}

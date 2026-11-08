import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, InjectionToken, inject } from '@angular/core';
import { Observable, switchMap, takeWhile, timer } from 'rxjs';

export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';

export interface Job {
  id: string;
  project_id: string;
  kind: string;
  status: JobStatus;
  payload: { program?: string };
  attempts: number;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  error_code: string | null;
  metrics: Record<string, unknown>;
  deduplicated: boolean;
}

export interface ProgramCopybook {
  name: string;
  line: number;
  file_id: string | null;
}

export interface ProgramSummary {
  id: string;
  name: string;
  file_id: string | null;
  start_line: number | null;
  end_line: number | null;
  is_entry: boolean;
  calls: string[];
  copybooks: ProgramCopybook[];
  metrics: Record<string, number>;
}

export interface FileSummary {
  id: string;
  name: string;
  file_id: string | null;
  start_line: number | null;
  program: string;
  assign: string | null;
  organization: string | null;
  record: string | null;
  mode: string | null;
  read_in: { paragraph: string; line: number }[];
  written_in: { paragraph: string; line: number }[];
}

export interface CopybookSummary {
  id: string;
  name: string;
  file_id: string | null;
  used_by: string[];
}

export interface DeadParagraph {
  id: string;
  name: string;
  program: string;
  file_id: string | null;
  start_line: number | null;
  end_line: number | null;
}

export interface ObsoleteRecord {
  id: string;
  name: string;
  file_id: string | null;
  start_line: number | null;
  end_line: number | null;
  length: number;
  used_by: string[];
}

export interface Inventory {
  analyzed: boolean;
  job_id: string | null;
  analyzer_version: string | null;
  summary: Record<string, number>;
  programs: ProgramSummary[];
  copybooks: CopybookSummary[];
  files: FileSummary[];
  dead_code: { paragraphs: DeadParagraph[]; records: ObsoleteRecord[] };
  diagnostics: string[];
}

export interface LayoutField {
  name: string;
  line: number | null;
  order: number;
  level: number;
  picture: string | null;
  category: string;
  offset: number;
  length: number;
  total_length: number;
  occurs: number | null;
  digits: number | null;
  scale: number | null;
  signed: boolean;
  redefines: string | null;
  value: string | null;
}

export interface LayoutRecord {
  id: string;
  name: string;
  file: string;
  file_id: string | null;
  start_line: number | null;
  section: string;
  length: number;
  redefines: string | null;
  used_by: string[];
  obsolete: boolean;
  fields: LayoutField[];
}

export interface LayoutPage {
  items: LayoutRecord[];
  total: number;
  limit: number;
  offset: number;
}

export interface GraphNode {
  id: string;
  kind: 'PROGRAM' | 'COPYBOOK' | 'PARAGRAPH' | 'FILE';
  name: string;
  file_id: string | null;
  start_line: number | null;
  end_line: number | null;
  program: string | null;
  dead: boolean;
  is_exit_label: boolean;
  is_entry: boolean;
}

export interface GraphEdge {
  from: string;
  to: string;
  kind: 'PERFORMS' | 'GOES_TO' | 'CALLS' | 'READS' | 'WRITES' | 'USES';
  lines: number[];
  thru: boolean;
  by_name: boolean;
}

export interface Graph {
  program: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SourceSummary {
  id: string;
  path: string;
  name: string;
  kind: string;
  line_count: number;
  sha256: string;
}

export interface RuleSpanHit {
  rule_id: string;
  title: string;
  state: RuleState;
  flags: string[];
  start_line: number;
  end_line: number;
}

export interface SourceDetail extends SourceSummary {
  project_id: string;
  lines: string[];
  copy_links: { line: number; name: string; file_id: string | null }[];
  rule_spans: RuleSpanHit[];
}

export type RuleState = 'PROPOSED' | 'VERIFIED' | 'REJECTED' | 'EDITED';
export type RuleFlag = 'SPAN_INVALID' | 'NAMES_NOT_FOUND' | 'LOW_CONFIDENCE';

export interface RuleSpan {
  file: string;
  file_id: string | null;
  start_line: number;
  end_line: number;
  valid: boolean;
}

export interface RuleExample {
  given: Record<string, unknown>;
  expect: Record<string, unknown>;
}

export interface Rule {
  id: string;
  project_id: string;
  program: string;
  title: string;
  statement: string;
  kind: string;
  inputs: string[];
  outputs: string[];
  conditions: string[];
  examples: RuleExample[];
  spans: RuleSpan[];
  flags: RuleFlag[];
  flag_details: { code: string; detail: string }[];
  confidence: number | null;
  state: RuleState;
  version: number;
  verifiable: boolean;
  decided_at: string | null;
  decided_by_name: string | null;
  decision_reason: string | null;
  edited_at: string | null;
  prompt_version: string;
  model_id: string | null;
}

export interface RulePage {
  items: Rule[];
  total: number;
  limit: number;
  offset: number;
  counts: Partial<Record<RuleState, number>>;
  programs: string[];
}

export interface RuleFilters {
  program?: string;
  state?: string;
  flag?: string;
  offset?: number;
}

export interface RuleEdit {
  title?: string;
  statement?: string;
  inputs?: string[];
  outputs?: string[];
  conditions?: string[];
  source_spans?: { file: string; start_line: number; end_line: number }[];
  examples?: RuleExample[];
}

/** How often a running job is checked. Tests shorten it. */
export const JOB_POLL_INTERVAL_MS = new InjectionToken<number>('JOB_POLL_INTERVAL_MS', {
  factory: () => 1000,
});

const JOB_ERROR_TEXT: Record<string, string> = {
  AI_TIMEOUT: 'The AI provider took too long to answer.',
  AI_RATE_LIMITED: 'The AI provider is rate limiting requests. Wait a little and try again.',
  AI_INVALID_OUTPUT:
    'The AI provider returned output that failed validation, so nothing was stored.',
  AI_AUTH: 'The AI provider refused the configured key.',
  AI_UNAVAILABLE: 'The AI provider could not be reached.',
  AI_REQUEST_REJECTED: 'The AI provider refused the request. Trying again will not help.',
  AI_NOT_CONFIGURED: 'Live AI mode is selected, but no key or model is configured.',
  AI_BUDGET_EXCEEDED: 'This project has used its AI call budget.',
  NO_PROGRAMS: 'This project has no COBOL programs to analyze.',
  PROGRAM_NOT_FOUND: 'That program is not part of this project.',
  JOB_ABANDONED: 'The job stopped responding and was given up on.',
  NOT_ANALYZED: 'Run the analysis first.',
  PLAN_PROGRAMS_MISMATCH:
    'The proposed plan did not place every program in exactly one service, so it was not stored.',
  PLAN_UNKNOWN_PROGRAM:
    'The proposed plan named a program that does not exist, so it was not stored.',
  PLAN_DUPLICATE_SERVICE: 'The proposed plan named a service twice, so it was not stored.',
  NO_VERIFIED_RULES: 'This program has no verified rules to migrate from.',
  POLICY_VIOLATION: 'The generated code used an API the sandbox forbids, so the build failed.',
  BUILD_FAILED: 'The generated code did not compile, and the repair budget is spent.',
  TESTS_FAILED: 'The generated unit tests failed, and the repair budget is spent.',
  SANDBOX_TIMEOUT: 'The code ran past its time limit in the sandbox and was stopped.',
  SANDBOX_MEMORY_LIMIT: 'The code ran past its memory limit in the sandbox and was stopped.',
  SANDBOX_UNAVAILABLE: 'The sandbox could not be reached.',
  MODERN_RUN_FAILED: 'The generated module did not answer every case.',
  LEGACY_SOURCE_MISMATCH: 'The project sources differ from the legacy program the runner executes.',
  UPLOAD_NOT_EXECUTABLE: 'Uploaded sources are never executed.',
  REPAIR_LIMIT: 'The repair budget for this module is spent.',
  INVALID_STATE: 'The module is not in a state that allows this.',
  NO_BUILT_ARTIFACT: 'There is no built artifact to verify.',
  EQUIVALENCE_NOT_PASSED: 'Mutation testing needs a verification where every case matched.',
  INTERNAL_ERROR: 'The job failed unexpectedly.',
};

export function describeJobError(code: string | null): string {
  return (code && JOB_ERROR_TEXT[code]) || 'The job failed unexpectedly.';
}

export function isJobFinished(job: Job): boolean {
  return job.status === 'SUCCEEDED' || job.status === 'FAILED';
}

@Injectable({ providedIn: 'root' })
export class WorkbenchService {
  private readonly http = inject(HttpClient);
  private readonly pollInterval = inject(JOB_POLL_INTERVAL_MS);

  private project(id: string): string {
    return `/api/v1/projects/${encodeURIComponent(id)}`;
  }

  startAnalysis(projectId: string): Observable<Job> {
    return this.http.post<Job>(`${this.project(projectId)}/analyze`, null);
  }

  startExtraction(projectId: string, program: string): Observable<Job> {
    const name = encodeURIComponent(program);
    return this.http.post<Job>(`${this.project(projectId)}/programs/${name}/extract-rules`, null);
  }

  job(id: string): Observable<Job> {
    return this.http.get<Job>(`/api/v1/jobs/${encodeURIComponent(id)}`);
  }

  /** Emits the job on every check and completes after the check that finds it finished. */
  pollJob(id: string): Observable<Job> {
    return timer(0, this.pollInterval).pipe(
      switchMap(() => this.job(id)),
      takeWhile((job) => !isJobFinished(job), true),
    );
  }

  inventory(projectId: string): Observable<Inventory> {
    return this.http.get<Inventory>(`${this.project(projectId)}/inventory`);
  }

  layouts(projectId: string, program: string | null, offset = 0): Observable<LayoutPage> {
    let params = new HttpParams().set('limit', 50).set('offset', offset);
    if (program) {
      params = params.set('program', program);
    }
    return this.http.get<LayoutPage>(`${this.project(projectId)}/inventory/layouts`, { params });
  }

  graph(projectId: string, program: string | null): Observable<Graph> {
    const params = program ? new HttpParams().set('program', program) : undefined;
    return this.http.get<Graph>(`${this.project(projectId)}/graph`, { params });
  }

  sources(projectId: string): Observable<{ items: SourceSummary[]; total: number }> {
    return this.http.get<{ items: SourceSummary[]; total: number }>(
      `${this.project(projectId)}/sources`,
    );
  }

  source(projectId: string, fileId: string): Observable<SourceDetail> {
    return this.http.get<SourceDetail>(
      `${this.project(projectId)}/sources/${encodeURIComponent(fileId)}`,
    );
  }

  rules(projectId: string, filters: RuleFilters): Observable<RulePage> {
    let params = new HttpParams().set('limit', 50);
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') {
        params = params.set(key, value);
      }
    }
    return this.http.get<RulePage>(`${this.project(projectId)}/rules`, { params });
  }

  rule(ruleId: string): Observable<Rule> {
    return this.http.get<Rule>(`/api/v1/rules/${encodeURIComponent(ruleId)}`);
  }

  editRule(rule: Rule, changes: RuleEdit): Observable<Rule> {
    return this.http.patch<Rule>(`/api/v1/rules/${encodeURIComponent(rule.id)}`, {
      expected_version: rule.version,
      ...changes,
    });
  }

  decideRule(
    rule: Rule,
    decision: 'VERIFIED' | 'REJECTED',
    reason: string | null,
  ): Observable<Rule> {
    return this.http.post<Rule>(`/api/v1/rules/${encodeURIComponent(rule.id)}/decision`, {
      decision,
      expected_version: rule.version,
      reason,
    });
  }
}

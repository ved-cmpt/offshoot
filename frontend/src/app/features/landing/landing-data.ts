import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';

/**
 * The landing page's data: frontend/public/data/landing-snapshot.json, written from stored runs
 * by scripts/landing_snapshot.py (ADR-054). The landing page never calls the API.
 */
export interface Excerpt {
  file: string;
  start: number;
  lines: string[];
  sha256?: string;
  matches_run?: boolean;
}

export interface CsharpExcerpt extends Excerpt {
  artifact_version: number;
  artifact_kind: string;
  unit_tests: { passed: number | null; total: number | null };
}

export interface RunSummary {
  id: string;
  status: string;
  seed: number;
  cases: number;
  passed: number;
  failed: number;
  coverage_pct: number | null;
  mutation_score: number | null;
  created_at: string;
}

export interface ModuleRow {
  program: string;
  id: string;
  service: string | null;
  order: number;
  state: string;
  facade_mode: 'LEGACY' | 'SHADOW' | 'MODERN';
  run: RunSummary | null;
}

export interface FieldDiff {
  field: string;
  legacy: string;
  modern: string;
}

export interface Mismatch {
  case: number;
  input: string;
  input_fields: Record<string, string>;
  label: string;
  source: string;
  diffs: FieldDiff[];
}

export interface Gate {
  gate: string;
  label: string;
  passed: boolean;
  value: number | null;
  threshold: number;
  unit: string;
}

export interface SnapshotRule {
  id: string;
  program: string;
  title: string;
  statement: string;
  state: string;
  flags: string[];
  flag_details: { code: string; detail: string }[];
  spans: { file: string; start_line: number; end_line: number; valid: boolean }[];
  examples: { given: Record<string, unknown>; expect: Record<string, unknown> }[];
}

export interface VerifiedStory {
  module_id: string;
  run_id: string;
  created_at: string;
  seed: number;
  cases: number;
  passed: number;
  by_source: Record<string, number>;
  coverage_pct: number | null;
  mutation_score: number | null;
  rule: SnapshotRule;
  csharp: CsharpExcerpt;
}

export interface Snapshot {
  schema: number;
  provenance: { generated_at: string; read_from: string; read_as: string; script: string; note: string };
  api: {
    project: { id: string; name: string; files: number; lines: number };
    inventory: { summary: Record<string, number>; dead_paragraphs: string[] };
    modules: ModuleRow[];
    rules: { total: number; by_state: Record<string, number> };
    rounding: {
      module_id: string;
      run_id: string;
      created_at: string;
      seed: number;
      cases: number;
      passed: number;
      failed: number;
      by_source: Record<string, number>;
      failed_by_source: Record<string, number>;
      mismatched_fields: Record<string, number>;
      mismatches: Mismatch[];
      coverage: { pct: number | null; missed: string[] };
      gates: Gate[];
      versions: Record<string, string>;
      csharp_first: CsharpExcerpt;
      artifact_notes: string | null;
    };
    year_window: VerifiedStory;
    rollover: VerifiedStory;
    injection: { rules_proposed: number; flagged: SnapshotRule[] };
  };
  repo: {
    rounding_cobol: Excerpt[];
    rounding_math: {
      case: number;
      input: string;
      label: string;
      kwh: number;
      month: number;
      season: string;
      tier_limit: number;
      tier1: { kwh: number; rate: string; amount: string };
      tier2: { kwh: number; rate: string; amount: string };
      exact: string;
      half_up: string;
      half_even: string;
      legacy: string;
      modern: string;
      consistent: boolean;
      constants: Record<string, { value: string; line: number }>;
    };
    repair: {
      source: string;
      measured_in: string;
      unit_tests: string;
      identical: string;
      coverage: string;
      mutation: string;
      state: string;
      csharp: Excerpt;
    };
    year_window_cobol: Excerpt[];
    rollover_cobol: Excerpt[];
    injection_cobol: Excerpt[];
    evaluation: { source: string; columns: string[]; rows: string[][] };
  };
}

export const SNAPSHOT_URL = '/data/landing-snapshot.json';
export const REPO_URL = 'https://github.com/ved-cmpt/offshoot';
export const DOCS = {
  readme: `${REPO_URL}#readme`,
  evaluation: `${REPO_URL}/blob/main/docs/EVALUATION.md`,
  security: `${REPO_URL}/blob/main/docs/SECURITY.md`,
  decisions: `${REPO_URL}/blob/main/docs/ARCHITECTURE_DECISIONS.md`,
  brand: `${REPO_URL}/blob/main/docs/BRAND.md`,
  changelog: `${REPO_URL}/blob/main/CHANGELOG.md`,
  license: `${REPO_URL}/blob/main/LICENSE`,
  snapshot: `${REPO_URL}/blob/main/frontend/public/data/landing-snapshot.json`,
};

@Injectable({ providedIn: 'root' })
export class LandingData {
  private readonly http = inject(HttpClient);
  private requested = false;

  readonly snapshot = signal<Snapshot | null>(null);
  readonly failed = signal(false);

  load(): void {
    if (this.requested) {
      return;
    }
    this.requested = true;
    this.http.get<Snapshot>(SNAPSHOT_URL).subscribe({
      next: (snapshot) => this.snapshot.set(snapshot),
      error: () => this.failed.set(true),
    });
  }
}

/** "1,464" */
export function thousands(value: number): string {
  return value.toLocaleString('en-US');
}

/** A row of docs/EVALUATION.md's headline table, by the start of its measure's name. */
export function evaluationRow(data: Snapshot, measure: string): string[] | null {
  return data.repo.evaluation.rows.find((row) => row[0].startsWith(measure)) ?? null;
}

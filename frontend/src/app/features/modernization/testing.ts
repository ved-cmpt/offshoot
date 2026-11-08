import {
  ArtifactDetail,
  Gate,
  ModuleDetail,
  ModuleSummary,
  Plan,
  RunDetail,
  RunSummary,
} from './modernization.service';

export function makePlan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: 'plan1',
    version: 1,
    state: 'PROPOSED',
    services: [
      { name: 'meter-service', description: 'Meter reads.', programs: ['MTRVAL'] },
      {
        name: 'billing-service',
        description: 'Rates and fees.',
        programs: ['RATECALC', 'BILLRUN'],
      },
    ],
    order: [
      {
        position: 1,
        program: 'MTRVAL',
        service: 'meter-service',
        depends_on: [],
        reason: 'Calls no other program.',
      },
      {
        position: 2,
        program: 'RATECALC',
        service: 'billing-service',
        depends_on: [],
        reason: 'Calls no other program.',
      },
      {
        position: 3,
        program: 'BILLRUN',
        service: 'billing-service',
        depends_on: ['MTRVAL', 'RATECALC'],
        reason: 'Calls MTRVAL, RATECALC, so it moves after them.',
      },
    ],
    risks: [
      {
        title: 'Half-up rounding',
        detail: 'COMPUTE ROUNDED rounds a midpoint up.',
        severity: 'HIGH',
        programs: ['RATECALC'],
      },
    ],
    estimate: {
      method: 'Relative effort points.',
      modules: [
        {
          program: 'RATECALC',
          code_lines: 150,
          decisions: 12,
          traps: 4,
          verified_rules: 12,
          points: 29,
        },
      ],
      total_points: 29,
    },
    signals: {
      risk_signals: [{ program: 'RATECALC', signal: 'COMPUTE ROUNDED sites', detail: '4 found' }],
    },
    prompt_version: 'plan-v1',
    model_id: 'mock-fixtures-v1',
    created_at: '2026-11-08T01:00:00Z',
    decided_at: null,
    decided_by_name: null,
    decision_reason: null,
    ...overrides,
  };
}

export function makeRunSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: 'run1',
    kind: 'FULL',
    status: 'FAILED',
    seed: 20261107,
    cases: 500,
    passed: 484,
    failed: 16,
    coverage_pct: 93.33,
    mutation_score: null,
    artifact_id: 'a1',
    artifact_version: 1,
    job_id: 'j9',
    created_at: '2026-11-08T02:00:00Z',
    ...overrides,
  };
}

export const FAILED_GATES: Gate[] = [
  {
    gate: 'BUILD',
    label: 'Build and analyzers',
    passed: true,
    value: 0,
    threshold: 0,
    unit: 'errors',
  },
  {
    gate: 'UNIT_TESTS',
    label: 'Unit tests',
    passed: true,
    value: 8,
    threshold: 8,
    unit: 'tests passed',
  },
  {
    gate: 'EQUIVALENCE',
    label: 'Equivalence',
    passed: false,
    value: 96.8,
    threshold: 100,
    unit: '% of cases',
  },
  {
    gate: 'COVERAGE',
    label: 'Legacy paragraph coverage',
    passed: true,
    value: 93.33,
    threshold: 85,
    unit: '%',
  },
  {
    gate: 'MUTATION',
    label: 'Mutation score',
    passed: false,
    value: null,
    threshold: 70,
    unit: '%',
  },
];

export function makeRunDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...makeRunSummary(),
    gates: FAILED_GATES,
    base_run_id: null,
    report: {
      seed: 20261107,
      program: 'RATECALC',
      cases: 500,
      passed: 484,
      failed: 16,
      pass_pct: 96.8,
      by_source: { boundary: 26, recorded: 150, random: 300 },
      failed_by_source: { random: 16 },
      mismatched_fields: { 'RC-OUT-ENERGY': 8, 'RC-OUT-TOTAL': 16 },
      mismatches: [
        {
          case: 7,
          source: 'random',
          label: 'seeded draw 3',
          input: 'R0100610',
          input_fields: { 'RC-IN-CLASS': 'R', 'RC-IN-MONTH': '10', 'RC-IN-KWH': '610' },
          legacy: 'E0000600006000001000000559100425000006016N0000150000006166',
          modern: 'E0000600006000001000000559000425000006015N0000150000006165',
          diffs: [
            {
              field: 'RC-OUT-ENERGY',
              legacy: '55.91',
              modern: '55.90',
              legacy_raw: '000005591',
              modern_raw: '000005590',
            },
            {
              field: 'RC-OUT-TOTAL',
              legacy: '61.66',
              modern: '61.65',
              legacy_raw: '000006166',
              modern_raw: '000006165',
            },
          ],
        },
      ],
      coverage: {
        pct: 93.33,
        paragraphs: 15,
        hit: ['0000-MAIN-CONTROL'],
        missed: ['8500-APPLY-WINTER-DISCOUNT'],
      },
      rules: {
        verified: 1,
        exercised: [{ id: 'r1', title: 'Minimum charge', cases: 4 }],
        not_exercised: [],
      },
      mutation: {
        skipped: 'Mutation testing runs only when every case matches the legacy output.',
      },
      artifact: { id: 'a1', version: 1, sha256: 'abc' },
      versions: {},
    },
    ...overrides,
  };
}

export function makeModule(overrides: Partial<ModuleDetail> = {}): ModuleDetail {
  return {
    id: 'm1',
    project_id: 'p1',
    program: 'RATECALC',
    target_service: 'billing-service',
    order_index: 2,
    state: 'BLOCKED',
    state_reason: 'EQUIVALENCE_FAILED',
    facade_mode: 'LEGACY',
    version: 5,
    current_artifact: {
      id: 'a1',
      version: 1,
      kind: 'MIGRATION',
      attempt: 1,
      build_status: 'BUILT',
      sha256: 'abcdef1234567890',
      files: ['src/ModuleEntry.cs'],
      rule_ids: ['r1'],
      notes: 'Translated RATECALC.',
      model_id: 'mock-fixtures-v1',
      prompt_version: 'migrate-v1',
      created_at: '2026-11-08T01:30:00Z',
    },
    latest_run: makeRunSummary(),
    repairs_used: 0,
    repairs_remaining: 3,
    migratable: true,
    active_job: null,
    updated_at: '2026-11-08T02:00:00Z',
    gates: FAILED_GATES,
    thresholds: { coverage: 85, mutation: 70, exceptions: {} },
    verified_rules: 12,
    shadow: { compared: 0, mismatches: 0, sample: 20, ready: false, since: null },
    decision: null,
    approvable: false,
    ...overrides,
  };
}

export function makeSummary(overrides: Partial<ModuleSummary> = {}): ModuleSummary {
  const summary: Partial<ModuleDetail> = { ...makeModule() };
  delete summary.gates;
  delete summary.thresholds;
  delete summary.verified_rules;
  delete summary.shadow;
  delete summary.decision;
  delete summary.approvable;
  return { ...(summary as ModuleSummary), ...overrides };
}

export function makeArtifact(overrides: Partial<ArtifactDetail> = {}): ArtifactDetail {
  return {
    ...makeModule().current_artifact!,
    module_id: 'm1',
    parent_id: null,
    file_contents: [
      { path: 'src/ModuleEntry.cs', content: 'public static class ModuleEntry { }' },
      { path: 'tests/Tests.cs', content: '// tests <script>alert(1)</script>' },
    ],
    build_report: {
      build: { ok: true, errors: 0, warnings: 0, diagnostics: [] },
      tests: { ok: true, total: 8, passed: 8, failed: 0, failed_tests: [] },
    },
    ...overrides,
  };
}

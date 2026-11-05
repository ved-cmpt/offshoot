import { signal } from '@angular/core';

import { Role } from '../../core/auth/auth.service';
import { Graph, Inventory, Job, Rule, SourceDetail } from './workbench.service';

export function authAs(role: Role | null): { user: ReturnType<typeof signal> } {
  return {
    user: signal(role ? { id: 'u1', email: 'x@test.example', display_name: 'Test', role } : null),
  };
}

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 'j1',
    project_id: 'p1',
    kind: 'ANALYZE',
    status: 'QUEUED',
    payload: {},
    attempts: 0,
    created_at: '2026-11-05T01:00:00Z',
    started_at: null,
    ended_at: null,
    error_code: null,
    metrics: {},
    deduplicated: false,
    ...overrides,
  };
}

export function makeRule(overrides: Partial<Rule> = {}): Rule {
  return {
    id: 'r1',
    project_id: 'p1',
    program: 'RATECALC',
    title: 'Minimum charge',
    statement: 'The subtotal is raised to the class minimum.',
    kind: 'DECISION',
    inputs: ['RC-OUT-ENERGY'],
    outputs: ['RC-OUT-SUBTOTAL'],
    conditions: ['RC-OUT-SUBTOTAL < WS-MINIMUM'],
    examples: [{ given: { 'RC-OUT-ENERGY': 1 }, expect: { 'RC-OUT-SUBTOTAL': 8.5 } }],
    spans: [{ file: 'RATECALC.cbl', file_id: 'f1', start_line: 196, end_line: 203, valid: true }],
    flags: [],
    flag_details: [],
    confidence: 0.95,
    state: 'PROPOSED',
    version: 1,
    verifiable: true,
    decided_at: null,
    decided_by_name: null,
    decision_reason: null,
    edited_at: null,
    prompt_version: 'rules-v1',
    model_id: 'mock-fixtures-rules-v1',
    ...overrides,
  };
}

export function makeFlaggedRule(overrides: Partial<Rule> = {}): Rule {
  return makeRule({
    id: 'r2',
    title: 'Senior discount on the energy charge',
    flags: ['SPAN_INVALID', 'NAMES_NOT_FOUND'],
    flag_details: [
      {
        code: 'SPAN_INVALID',
        detail: 'RATECALC.cbl:240-252 is outside the file, which has 232 lines.',
      },
      {
        code: 'NAMES_NOT_FOUND',
        detail: 'Not found in the cited lines or copybooks: RC-OUT-SENIOR-DISCOUNT.',
      },
    ],
    spans: [{ file: 'RATECALC.cbl', file_id: 'f1', start_line: 240, end_line: 252, valid: false }],
    verifiable: false,
    ...overrides,
  });
}

export function makeInventory(overrides: Partial<Inventory> = {}): Inventory {
  return {
    analyzed: true,
    job_id: 'j1',
    analyzer_version: 'analysis-v1',
    summary: {
      programs: 5,
      copybooks: 6,
      lines: 1437,
      working_paragraphs: 69,
      exit_labels: 57,
      performs: 80,
      go_tos: 1,
      calls: 4,
      files: 4,
      records: 20,
      dead_paragraphs: 1,
      obsolete_records: 1,
    },
    programs: [
      {
        id: 'i1',
        name: 'BILLRUN',
        file_id: 'f2',
        start_line: 1,
        end_line: 426,
        is_entry: true,
        calls: ['MTRVAL', 'RATECALC'],
        copybooks: [{ name: 'CUSTREC', line: 59, file_id: 'f3' }],
        metrics: { lines: 426, working_paragraphs: 25, performs: 30, go_tos: 1 },
      },
      {
        id: 'i2',
        name: 'RATECALC',
        file_id: 'f1',
        start_line: 1,
        end_line: 232,
        is_entry: false,
        calls: [],
        copybooks: [{ name: 'RATES', line: 37, file_id: 'f4' }],
        metrics: { lines: 232, working_paragraphs: 15, performs: 12, go_tos: 0 },
      },
    ],
    copybooks: [{ id: 'c1', name: 'RATES', file_id: 'f4', used_by: ['RATECALC'] }],
    files: [
      {
        id: 'x1',
        name: 'CUSTFILE',
        file_id: 'f2',
        start_line: 44,
        program: 'BILLRUN',
        assign: 'CUSTFILE',
        organization: 'LINE SEQUENTIAL',
        record: 'CUSTOMER-RECORD',
        mode: 'INPUT',
        read_in: [{ paragraph: '8100-READ-CUSTOMER', line: 339 }],
        written_in: [],
      },
    ],
    dead_code: {
      paragraphs: [
        {
          id: 'd1',
          name: '8500-APPLY-WINTER-DISCOUNT',
          program: 'RATECALC',
          file_id: 'f1',
          start_line: 216,
          end_line: 232,
        },
      ],
      records: [
        {
          id: 'd2',
          name: 'RT-WINTER-1987-TABLE',
          file_id: 'f4',
          start_line: 52,
          end_line: 55,
          length: 44,
          used_by: ['RATECALC'],
        },
      ],
    },
    diagnostics: [],
    ...overrides,
  };
}

export const OVERVIEW_GRAPH: Graph = {
  program: null,
  nodes: [
    node('a', 'PROGRAM', 'BILLRUN', { is_entry: true }),
    node('b', 'PROGRAM', 'RATECALC'),
    node('c', 'FILE', 'CUSTFILE'),
  ],
  edges: [
    { from: 'a', to: 'b', kind: 'CALLS', lines: [210], thru: false, by_name: false },
    { from: 'a', to: 'c', kind: 'READS', lines: [339], thru: false, by_name: false },
  ],
};

export const PARAGRAPH_GRAPH: Graph = {
  program: 'RATECALC',
  nodes: [
    node('m', 'PARAGRAPH', '0000-MAIN-CONTROL', {
      program: 'RATECALC',
      file_id: 'f1',
      start_line: 56,
      end_line: 66,
    }),
    node('s', 'PARAGRAPH', '3300-SELECT-SEASON', { program: 'RATECALC' }),
    node('e', 'PARAGRAPH', '3400-TARIFF-EXIT', { program: 'RATECALC', is_exit_label: true }),
    node('w', 'PARAGRAPH', '8500-APPLY-WINTER-DISCOUNT', { program: 'RATECALC', dead: true }),
  ],
  edges: [
    { from: 'm', to: 's', kind: 'PERFORMS', lines: [60], thru: true, by_name: false },
    { from: 'm', to: 'e', kind: 'PERFORMS', lines: [60], thru: true, by_name: false },
  ],
};

function node(
  id: string,
  kind: Graph['nodes'][number]['kind'],
  name: string,
  extra: Partial<Graph['nodes'][number]> = {},
) {
  return {
    id,
    kind,
    name,
    file_id: null,
    start_line: null,
    end_line: null,
    program: null,
    dead: false,
    is_exit_label: false,
    is_entry: false,
    ...extra,
  };
}

export function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'f2',
    project_id: 'p1',
    path: 'src/DEMO.cbl',
    name: 'DEMO.cbl',
    kind: 'PROGRAM',
    line_count: 5,
    sha256: 'abc',
    lines: [
      '       IDENTIFICATION DIVISION.',
      '      * <script>alert(1)</script> and {{ not a binding }}',
      '       COPY RATES.',
      '       COPY MISSING.',
      '           GOBACK.',
    ],
    copy_links: [
      { line: 3, name: 'RATES', file_id: 'f4' },
      { line: 4, name: 'MISSING', file_id: null },
    ],
    rule_spans: [
      { rule_id: 'r1', title: 'A rule', state: 'PROPOSED', flags: [], start_line: 3, end_line: 4 },
    ],
    ...overrides,
  };
}

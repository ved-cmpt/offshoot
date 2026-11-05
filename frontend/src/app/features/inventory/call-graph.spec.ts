import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { OVERVIEW_GRAPH, PARAGRAPH_GRAPH } from '../workbench/testing';
import { CallGraph } from './call-graph';
import { NODE_WIDTH, layoutGraph } from './graph-layout';

describe('layoutGraph', () => {
  it('places a callee in a column past its caller', () => {
    const layout = layoutGraph(OVERVIEW_GRAPH.nodes, OVERVIEW_GRAPH.edges);
    const x = Object.fromEntries(layout.nodes.map((item) => [item.node.name, item.x]));
    expect(x['RATECALC']).toBeGreaterThan(x['BILLRUN']);
    expect(x['CUSTFILE']).toBeGreaterThan(x['BILLRUN']);
    expect(layout.width).toBeGreaterThan(NODE_WIDTH);
  });

  it('gives every node its own position', () => {
    const layout = layoutGraph(PARAGRAPH_GRAPH.nodes, PARAGRAPH_GRAPH.edges);
    const spots = layout.nodes.map((item) => `${item.x},${item.y}`);
    expect(new Set(spots).size).toBe(spots.length);
  });

  it('survives a cycle and a self loop', () => {
    const nodes = OVERVIEW_GRAPH.nodes;
    const edges = [
      { from: 'a', to: 'b', kind: 'PERFORMS' as const, lines: [], thru: false, by_name: true },
      { from: 'b', to: 'a', kind: 'GOES_TO' as const, lines: [], thru: false, by_name: false },
      { from: 'c', to: 'c', kind: 'PERFORMS' as const, lines: [], thru: false, by_name: true },
    ];
    const layout = layoutGraph(nodes, edges);
    expect(layout.nodes).toHaveLength(3);
    expect(layout.edges).toHaveLength(3);
    expect(layout.edges.every((edge) => edge.path.startsWith('M'))).toBe(true);
  });

  it('skips an edge to a node that is hidden', () => {
    const layout = layoutGraph(OVERVIEW_GRAPH.nodes.slice(0, 1), OVERVIEW_GRAPH.edges);
    expect(layout.edges).toEqual([]);
  });

  it('is deterministic', () => {
    expect(layoutGraph(PARAGRAPH_GRAPH.nodes, PARAGRAPH_GRAPH.edges)).toEqual(
      layoutGraph(PARAGRAPH_GRAPH.nodes, PARAGRAPH_GRAPH.edges),
    );
  });

  it('handles an empty graph', () => {
    const layout = layoutGraph([], []);
    expect(layout.nodes).toEqual([]);
    expect(layout.height).toBeGreaterThan(0);
  });
});

describe('CallGraph', () => {
  let fixture: ComponentFixture<CallGraph>;
  let http: HttpTestingController;
  let page: HTMLElement;

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function request(url: string): TestRequest {
    return http.expectOne(url);
  }

  beforeEach(async () => {
    TestBed.configureTestingModule({
      imports: [CallGraph],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(CallGraph);
    fixture.componentRef.setInput('projectId', 'p1');
    fixture.componentRef.setInput('programs', ['BILLRUN', 'RATECALC']);
    page = fixture.nativeElement;
    fixture.detectChanges();
    await settle();
  });

  afterEach(() => http.verify());

  async function chooseProgram(name: string): Promise<void> {
    const select = page.querySelector('select')!;
    select.value = name;
    select.dispatchEvent(new Event('change'));
    await settle();
  }

  it('announces loading, then draws the overview', async () => {
    expect(page.querySelector('[role="status"]')?.textContent).toContain('Loading');
    request('/api/v1/projects/p1/graph').flush(OVERVIEW_GRAPH);
    await settle();
    expect(page.querySelectorAll('.node')).toHaveLength(3);
    expect(page.querySelectorAll('.edge')).toHaveLength(2);
    expect(page.querySelector('[aria-label="program, BILLRUN, entry point"]')).not.toBeNull();
  });

  it('switching program loads its paragraphs and hides -EXIT labels by default', async () => {
    request('/api/v1/projects/p1/graph').flush(OVERVIEW_GRAPH);
    await settle();
    await chooseProgram('RATECALC');
    request('/api/v1/projects/p1/graph?program=RATECALC').flush(PARAGRAPH_GRAPH);
    await settle();
    expect(page.textContent).not.toContain('3400-TARIFF-EXIT');
    expect(page.querySelectorAll('.node')).toHaveLength(3);

    const toggle = page.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    toggle.checked = true;
    toggle.dispatchEvent(new Event('change'));
    await settle();
    expect(page.textContent).toContain('3400-TARIFF-EXIT');
  });

  it('marks dead code in words, not only by colour', async () => {
    request('/api/v1/projects/p1/graph').flush(OVERVIEW_GRAPH);
    await settle();
    await chooseProgram('RATECALC');
    request('/api/v1/projects/p1/graph?program=RATECALC').flush(PARAGRAPH_GRAPH);
    await settle();
    const dead = page.querySelector('.node--dead')!;
    expect(dead.textContent).toContain('(dead)');
    expect(dead.getAttribute('aria-label')).toContain('dead code');
  });

  it('selecting by click or keyboard lists links and links to the source', async () => {
    request('/api/v1/projects/p1/graph').flush(OVERVIEW_GRAPH);
    await settle();
    await chooseProgram('RATECALC');
    request('/api/v1/projects/p1/graph?program=RATECALC').flush(PARAGRAPH_GRAPH);
    await settle();

    const main = page.querySelector<SVGGElement>('[aria-label="paragraph, 0000-MAIN-CONTROL"]')!;
    expect(main.getAttribute('role')).toBe('button');
    expect(main.getAttribute('tabindex')).toBe('0');
    main.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
    const details = page.querySelector('.details')!;
    expect(details.textContent).toContain(
      'performs 3300-SELECT-SEASON (reached through a THRU range)',
    );
    expect(details.textContent).toContain('line 60');
    expect(details.querySelector('a')?.getAttribute('href')).toBe(
      '/projects/p1/sources/f1?line=56&end=66',
    );
    expect(main.getAttribute('aria-pressed')).toBe('true');
    expect(page.querySelectorAll('.edge--active').length).toBeGreaterThan(0);

    main.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await settle();
    expect(page.querySelector('.details')).toBeNull();
  });

  it('shows an error with a working retry', async () => {
    request('/api/v1/projects/p1/graph').flush({}, { status: 500, statusText: 'Error' });
    await settle();
    const alert = page.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('could not be loaded');
    alert.querySelector('button')!.click();
    await settle();
    request('/api/v1/projects/p1/graph').flush(OVERVIEW_GRAPH);
    await settle();
    expect(page.querySelector('[role="alert"]')).toBeNull();
  });

  it('has an empty state', async () => {
    request('/api/v1/projects/p1/graph').flush({ program: null, nodes: [], edges: [] });
    await settle();
    expect(page.textContent).toContain('graph is empty');
  });
});

import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { Graph, GraphEdge, GraphNode, WorkbenchService } from '../workbench/workbench.service';
import { NODE_HEIGHT, NODE_WIDTH, layoutGraph } from './graph-layout';

type GraphState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; graph: Graph };

const EDGE_LABELS: Record<GraphEdge['kind'], string> = {
  PERFORMS: 'performs',
  GOES_TO: 'goes to',
  CALLS: 'calls',
  READS: 'reads',
  WRITES: 'writes',
  USES: 'copies',
};

/** Interactive call graph: SVG with real buttons, plus a text list of the selected node's links. */
@Component({
  selector: 'app-call-graph',
  imports: [RouterLink],
  templateUrl: './call-graph.html',
  styleUrl: './call-graph.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CallGraph {
  private readonly workbench = inject(WorkbenchService);
  private readonly destroyRef = inject(DestroyRef);
  private subscription: Subscription | null = null;

  readonly projectId = input.required<string>();
  readonly programs = input.required<string[]>();

  protected readonly program = signal<string | null>(null);
  protected readonly showExitLabels = signal(false);
  protected readonly state = signal<GraphState>({ kind: 'loading' });
  protected readonly selectedId = signal<string | null>(null);
  protected readonly nodeWidth = NODE_WIDTH;
  protected readonly nodeHeight = NODE_HEIGHT;

  private readonly visible = computed(() => {
    const state = this.state();
    if (state.kind !== 'ready') {
      return { nodes: [] as GraphNode[], edges: [] as GraphEdge[] };
    }
    const hidden = this.showExitLabels()
      ? new Set<string>()
      : new Set(state.graph.nodes.filter((node) => node.is_exit_label).map((node) => node.id));
    return {
      nodes: state.graph.nodes.filter((node) => !hidden.has(node.id)),
      edges: state.graph.edges.filter((edge) => !hidden.has(edge.from) && !hidden.has(edge.to)),
    };
  });

  protected readonly layout = computed(() =>
    layoutGraph(this.visible().nodes, this.visible().edges),
  );

  protected readonly selected = computed(() => {
    const id = this.selectedId();
    return this.visible().nodes.find((node) => node.id === id) ?? null;
  });

  protected readonly connections = computed(() => {
    const node = this.selected();
    if (!node) {
      return [];
    }
    const names = new Map(this.visible().nodes.map((item) => [item.id, item]));
    return this.visible()
      .edges.filter((edge) => edge.from === node.id || edge.to === node.id)
      .map((edge) => {
        const outgoing = edge.from === node.id;
        const other = names.get(outgoing ? edge.to : edge.from);
        const verb = EDGE_LABELS[edge.kind];
        const how = edge.thru && !edge.by_name ? ' (reached through a THRU range)' : '';
        return {
          key: `${edge.kind}-${edge.from}-${edge.to}`,
          text: outgoing ? `${verb} ${other?.name}${how}` : `${other?.name} ${verb} this${how}`,
          lines: edge.lines,
        };
      });
  });

  constructor() {
    effect(() => {
      const projectId = this.projectId();
      const program = this.program();
      untracked(() => this.load(projectId, program));
    });
  }

  protected reload(): void {
    this.load(this.projectId(), this.program());
  }

  protected chooseProgram(value: string): void {
    this.program.set(value || null);
  }

  protected toggleExitLabels(checked: boolean): void {
    this.showExitLabels.set(checked);
  }

  protected select(node: GraphNode): void {
    this.selectedId.update((current) => (current === node.id ? null : node.id));
  }

  protected isConnected(edge: GraphEdge): boolean {
    const id = this.selectedId();
    return id !== null && (edge.from === id || edge.to === id);
  }

  protected nodeLabel(node: GraphNode): string {
    const parts = [node.kind.toLowerCase(), node.name];
    if (node.dead) {
      parts.push('dead code');
    }
    if (node.is_entry) {
      parts.push('entry point');
    }
    return parts.join(', ');
  }

  protected displayName(node: GraphNode): string {
    return node.name.length > 26 ? `${node.name.slice(0, 25)}…` : node.name;
  }

  protected sourceQuery(node: GraphNode): Record<string, number> {
    return node.start_line ? { line: node.start_line, end: node.end_line ?? node.start_line } : {};
  }

  private load(projectId: string, program: string | null): void {
    this.subscription?.unsubscribe();
    this.selectedId.set(null);
    this.state.set({ kind: 'loading' });
    this.subscription = this.workbench
      .graph(projectId, program)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (graph) => this.state.set({ kind: 'ready', graph }),
        error: (error: unknown) => this.state.set({ kind: 'error', message: describeError(error) }),
      });
  }
}

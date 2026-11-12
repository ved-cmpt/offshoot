import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { describeError } from '../../core/api/api-error';
import { Graph, GraphEdge, GraphNode, WorkbenchService } from '../workbench/workbench.service';
import { Icon } from '../../shared/icon/icon';
import { Direction, NODE_HEIGHT, NODE_WIDTH, layoutGraph } from './graph-layout';

const MIN_ZOOM = 0.2;
const MAX_ZOOM = 2.5;

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
  imports: [Icon, RouterLink],
  templateUrl: './call-graph.html',
  styleUrl: './call-graph.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CallGraph {
  private readonly workbench = inject(WorkbenchService);
  private readonly destroyRef = inject(DestroyRef);
  private subscription: Subscription | null = null;
  private readonly injector = inject(Injector);
  private readonly viewport = viewChild<ElementRef<HTMLElement>>('viewport');
  private drag: { x: number; y: number; tx: number; ty: number; moved: boolean } | null = null;
  private suppressClick = false;

  readonly projectId = input.required<string>();
  readonly programs = input.required<string[]>();

  protected readonly program = signal<string | null>(null);
  protected readonly showExitLabels = signal(false);
  protected readonly state = signal<GraphState>({ kind: 'loading' });
  protected readonly selectedId = signal<string | null>(null);
  protected readonly nodeWidth = NODE_WIDTH;
  protected readonly nodeHeight = NODE_HEIGHT;
  protected readonly direction = signal<Direction>('LR');
  protected readonly zoom = signal(1);
  protected readonly pan = signal({ x: 0, y: 0 });
  protected readonly transform = computed(
    () => `translate(${this.pan().x},${this.pan().y}) scale(${this.zoom()})`,
  );
  protected readonly zoomText = computed(() => `${Math.round(this.zoom() * 100)}%`);

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
    layoutGraph(this.visible().nodes, this.visible().edges, this.direction()),
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
    // Fit the picture whenever the drawing changes.
    effect(() => {
      this.layout();
      afterNextRender(() => this.fit(), { injector: this.injector });
    });
  }

  protected setDirection(direction: Direction): void {
    this.direction.set(direction);
  }

  /** Scale the whole graph into the viewport, never above 100%. */
  protected fit(): void {
    const box = this.viewport()?.nativeElement.getBoundingClientRect();
    const layout = this.layout();
    if (!box || !box.width || !layout.width) {
      this.zoom.set(1);
      this.pan.set({ x: 0, y: 0 });
      return;
    }
    const zoom = Math.max(MIN_ZOOM, Math.min(1, box.width / layout.width, box.height / layout.height));
    this.zoom.set(zoom);
    this.pan.set({
      x: Math.max(0, (box.width - layout.width * zoom) / 2),
      y: Math.max(0, (box.height - layout.height * zoom) / 2),
    });
  }

  protected zoomBy(factor: number, at?: { x: number; y: number }): void {
    const box = this.viewport()?.nativeElement.getBoundingClientRect();
    const center = at ?? { x: (box?.width ?? 0) / 2, y: (box?.height ?? 0) / 2 };
    const before = this.zoom();
    const after = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, before * factor));
    const pan = this.pan();
    // Keep the point under the cursor (or the centre) where it is.
    this.pan.set({
      x: center.x - ((center.x - pan.x) * after) / before,
      y: center.y - ((center.y - pan.y) * after) / before,
    });
    this.zoom.set(after);
  }

  protected onWheel(event: WheelEvent): void {
    // Ctrl or Cmd with the wheel (and a trackpad pinch) zooms; a plain wheel scrolls the page.
    if (!event.ctrlKey && !event.metaKey) {
      return;
    }
    event.preventDefault();
    const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
    this.zoomBy(event.deltaY < 0 ? 1.15 : 1 / 1.15, { x: event.clientX - box.left, y: event.clientY - box.top });
  }

  protected onPointerDown(event: PointerEvent): void {
    if (event.button !== 0) {
      return;
    }
    const pan = this.pan();
    this.drag = { x: event.clientX, y: event.clientY, tx: pan.x, ty: pan.y, moved: false };
  }

  protected onPointerMove(event: PointerEvent): void {
    if (!this.drag) {
      return;
    }
    const dx = event.clientX - this.drag.x;
    const dy = event.clientY - this.drag.y;
    if (!this.drag.moved && Math.hypot(dx, dy) < 4) {
      return;
    }
    if (!this.drag.moved) {
      this.drag.moved = true;
      (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    }
    this.pan.set({ x: this.drag.tx + dx, y: this.drag.ty + dy });
  }

  protected onPointerUp(): void {
    // A drag that moved must not also select the node it ended on.
    const moved = this.drag?.moved ?? false;
    this.drag = null;
    if (moved) {
      this.suppressClick = true;
      setTimeout(() => (this.suppressClick = false));
    }
  }

  /** Arrow keys pan, + and - zoom, 0 fits, when the graph has focus. */
  protected onKey(event: KeyboardEvent): void {
    if ((event.target as HTMLElement).closest('.node')) {
      return;
    }
    const step = 60;
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [step, 0],
      ArrowRight: [-step, 0],
      ArrowUp: [0, step],
      ArrowDown: [0, -step],
    };
    if (moves[event.key]) {
      event.preventDefault();
      const [dx, dy] = moves[event.key];
      this.pan.update((pan) => ({ x: pan.x + dx, y: pan.y + dy }));
    } else if (event.key === '+' || event.key === '=') {
      this.zoomBy(1.2);
    } else if (event.key === '-') {
      this.zoomBy(1 / 1.2);
    } else if (event.key === '0') {
      this.fit();
    }
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
    if (this.suppressClick) {
      return;
    }
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

import { GraphEdge, GraphNode } from '../workbench/workbench.service';

export const NODE_WIDTH = 230;
export const NODE_HEIGHT = 34;
const COLUMN_GAP = 70;
const ROW_GAP = 14;
const PADDING = 12;

export interface PlacedNode {
  node: GraphNode;
  x: number;
  y: number;
  rank: number;
}

export interface PlacedEdge {
  edge: GraphEdge;
  path: string;
}

export interface GraphLayout {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  width: number;
  height: number;
}

/**
 * A small layered layout, left to right. Deterministic, with no dependency and no inline
 * script, so it stays CSP-safe. Each node sits one column past its furthest caller, and back
 * edges are ignored when ranking, so the loop in a program cannot hang the layout.
 */
function assignRanks(nodes: GraphNode[], edges: GraphEdge[]): Map<string, number> {
  const successors = new Map<string, string[]>(nodes.map((node) => [node.id, []]));
  const incoming = new Set<string>();
  for (const edge of edges) {
    if (edge.from !== edge.to && successors.has(edge.from) && successors.has(edge.to)) {
      successors.get(edge.from)!.push(edge.to);
      incoming.add(edge.to);
    }
  }

  const ranks = new Map<string, number>();
  const onPath = new Set<string>();
  const visit = (id: string, rank: number): void => {
    if (onPath.has(id) || (ranks.get(id) ?? -1) >= rank) {
      return;
    }
    ranks.set(id, rank);
    onPath.add(id);
    for (const next of successors.get(id) ?? []) {
      visit(next, rank + 1);
    }
    onPath.delete(id);
  };
  for (const node of nodes) {
    if (!incoming.has(node.id)) {
      visit(node.id, 0);
    }
  }
  for (const node of nodes) {
    if (!ranks.has(node.id)) {
      visit(node.id, 0);
    }
  }
  return ranks;
}

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]): GraphLayout {
  const ranks = assignRanks(nodes, edges);
  const columns = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const rank = ranks.get(node.id) ?? 0;
    columns.set(rank, [...(columns.get(rank) ?? []), node]);
  }

  // One pass of barycentre ordering: place nodes near the average row of their callers.
  const rowOf = new Map<string, number>();
  const sortedRanks = [...columns.keys()].sort((a, b) => a - b);
  for (const rank of sortedRanks) {
    const scored = columns.get(rank)!.map((node, index) => {
      const rows = edges
        .filter((edge) => edge.to === node.id && rowOf.has(edge.from))
        .map((edge) => rowOf.get(edge.from)!);
      const score = rows.length ? rows.reduce((sum, row) => sum + row, 0) / rows.length : index;
      return { node, score, index };
    });
    scored.sort((a, b) => a.score - b.score || a.index - b.index);
    scored.forEach((entry, row) => rowOf.set(entry.node.id, row));
    columns.set(
      rank,
      scored.map((entry) => entry.node),
    );
  }

  const placed = new Map<string, PlacedNode>();
  let height = 0;
  sortedRanks.forEach((rank, column) => {
    columns.get(rank)!.forEach((node, row) => {
      const y = PADDING + row * (NODE_HEIGHT + ROW_GAP);
      placed.set(node.id, { node, x: PADDING + column * (NODE_WIDTH + COLUMN_GAP), y, rank });
      height = Math.max(height, y + NODE_HEIGHT + PADDING);
    });
  });

  const placedEdges: PlacedEdge[] = [];
  for (const edge of edges) {
    const source = placed.get(edge.from);
    const target = placed.get(edge.to);
    if (source && target) {
      placedEdges.push({ edge, path: edgePath(source, target) });
    }
  }
  return {
    nodes: [...placed.values()],
    edges: placedEdges,
    width: PADDING * 2 + Math.max(sortedRanks.length, 1) * (NODE_WIDTH + COLUMN_GAP) - COLUMN_GAP,
    height: Math.max(height, NODE_HEIGHT + PADDING * 2),
  };
}

function edgePath(source: PlacedNode, target: PlacedNode): string {
  const fromY = source.y + NODE_HEIGHT / 2;
  const toY = target.y + NODE_HEIGHT / 2;
  if (target.x > source.x) {
    const fromX = source.x + NODE_WIDTH;
    const bend = (target.x - fromX) / 2;
    return `M${fromX},${fromY} C${fromX + bend},${fromY} ${target.x - bend},${toY} ${target.x},${toY}`;
  }
  // A back edge or one within a column: loop out to the right of both nodes.
  const fromX = source.x + NODE_WIDTH;
  const toX = target.x + NODE_WIDTH;
  const out = Math.max(fromX, toX) + COLUMN_GAP / 2;
  return `M${fromX},${fromY} C${out},${fromY} ${out},${toY} ${toX},${toY}`;
}

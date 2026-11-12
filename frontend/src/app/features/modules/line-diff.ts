/**
 * Which lines of `after` are new or changed compared with `before`: the lines outside a longest
 * common subsequence. Used to show what a repair changed in the generated C#.
 */
export function changedLines(before: readonly string[], after: readonly string[]): boolean[] {
  const n = before.length;
  const m = after.length;
  // The table is (n + 1) x (m + 1); generated files are a few hundred lines at most.
  const table: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      table[i][j] =
        before[i] === after[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const changed = new Array<boolean>(m).fill(true);
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (before[i] === after[j]) {
      changed[j] = false;
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      i++;
    } else {
      j++;
    }
  }
  return changed;
}

/** How many lines were removed: those of `before` outside the common subsequence. */
export function removedCount(before: readonly string[], after: readonly string[]): number {
  const kept = changedLines(before, after).filter((value) => !value).length;
  return before.length - kept;
}

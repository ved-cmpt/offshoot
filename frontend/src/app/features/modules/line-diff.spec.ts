import { describe, expect, it } from 'vitest';

import { changedLines, removedCount } from './line-diff';

describe('line diff', () => {
  it('marks only the lines a repair changed', () => {
    const before = ['a', 'b => Math.Round(x, 2);', 'c'];
    const after = ['a', '/// half up', 'b => Math.Round(x, 2, MidpointRounding.AwayFromZero);', 'c'];
    expect(changedLines(before, after)).toEqual([false, true, true, false]);
    expect(removedCount(before, after)).toBe(1);
  });

  it('handles identical, empty and fully new files', () => {
    expect(changedLines(['x', 'y'], ['x', 'y'])).toEqual([false, false]);
    expect(changedLines([], ['x'])).toEqual([true]);
    expect(removedCount(['x', 'y'], [])).toBe(2);
  });
});

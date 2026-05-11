import { describe, it, expect } from 'vitest';
import { COLUMNS } from './types.js';

describe('COLUMNS', () => {
  it('contains ready_for_merge entry', () => {
    const keys = COLUMNS.map((c) => c.key);
    expect(keys).toContain('ready_for_merge');
  });

  it('contains in_merge entry', () => {
    const keys = COLUMNS.map((c) => c.key);
    expect(keys).toContain('in_merge');
  });

  it('does not contain ready_to_merge', () => {
    const keys = COLUMNS.map((c) => c.key);
    expect(keys).not.toContain('ready_to_merge');
  });

  it('ready_for_merge has correct label', () => {
    const col = COLUMNS.find((c) => c.key === 'ready_for_merge');
    expect(col?.label).toBe('Ready for Merge');
  });

  it('in_merge has correct label', () => {
    const col = COLUMNS.find((c) => c.key === 'in_merge');
    expect(col?.label).toBe('In Merge');
  });

  it('in_merge appears before done', () => {
    const keys = COLUMNS.map((c) => c.key);
    const inMergeIdx = keys.indexOf('in_merge');
    const doneIdx = keys.indexOf('done');
    expect(inMergeIdx).toBeGreaterThanOrEqual(0);
    expect(inMergeIdx).toBeLessThan(doneIdx);
  });
});

import { describe, expect, test } from 'vitest';

import { childLevels, kindLabel, levelOf, placeLabel } from './tree';
import type { ScopeNode, Template } from './types';

const franchise = {
  terms: { location: 'Store' },
  levels: [
    { key: 'region', label: 'Region', plural: 'Regions' },
    { key: 'franchisee', label: 'Franchisee', plural: 'Franchisees' },
  ],
} as unknown as Template;

const node = (kind: ScopeNode['kind'], level = '', name = 'X') => ({ kind, level, name }) as ScopeNode;

describe('tree levels', () => {
  test('names each node by its template level', () => {
    expect(kindLabel(franchise, node('org'))).toBe('Business');
    expect(kindLabel(franchise, node('region', 'franchisee'))).toBe('Franchisee');
    expect(kindLabel(franchise, node('location'))).toBe('Store');
    expect(placeLabel(franchise, node('region', 'region', 'North'))).toBe('Region · North');
  });

  test('offers only deeper levels under a group', () => {
    expect(childLevels(franchise, node('org')).map((l) => l.key)).toEqual(['region', 'franchisee']);
    expect(childLevels(franchise, node('region', 'region')).map((l) => l.key)).toEqual(['franchisee']);
    expect(childLevels(franchise, node('region', 'franchisee'))).toEqual([]);
    expect(childLevels(franchise, node('location'))).toEqual([]);
  });

  test('falls back to one "Area" level and to the last level for unknown keys', () => {
    const plain = { terms: { location: 'Club' }, levels: [] } as unknown as Template;
    expect(kindLabel(plain, node('region', 'area'))).toBe('Area');
    expect(levelOf(franchise, node('region', 'gone'))?.key).toBe('franchisee');
  });
});

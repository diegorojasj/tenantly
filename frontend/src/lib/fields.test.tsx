import { describe, expect, test } from 'vitest';

import { fieldsOf, readFields, showValue } from './fields';
import type { FieldDef, Template } from './types';

const defs: Array<FieldDef> = [
  { key: 'species', label: 'Species', type: 'choice', options: ['Dog', 'Cat'], required: true },
  { key: 'weight', label: 'Weight', type: 'number' },
  { key: 'neutered', label: 'Neutered', type: 'bool' },
  { key: 'rabies', label: 'Rabies until', type: 'date', expires: true },
  { key: 'notes', label: 'Notes', type: 'text', pii: true },
];

describe('typed fields', () => {
  test('a form reads into typed values, leaving blanks out', () => {
    const data = new FormData();
    data.set('s-species', 'Dog');
    data.set('s-weight', '12.5');
    data.set('s-rabies', '2027-01-31');
    data.set('s-notes', '   ');
    expect(readFields(defs, data, 's-')).toEqual({ species: 'Dog', weight: 12.5, neutered: false, rabies: '2027-01-31' });
    data.set('s-neutered', 'on');
    expect(readFields(defs, data, 's-').neutered).toBe(true);
  });

  test('values read back in words, and missing entities have no fields', () => {
    expect([showValue(true), showValue(false), showValue(3), showValue(undefined), showValue('')]).toEqual(['yes', 'no', '3', '—', '—']);
    const t = { fields: { customer: defs } } as unknown as Template;
    expect(fieldsOf(t, 'customer')).toHaveLength(5);
    expect(fieldsOf(t, 'booking')).toEqual([]);
  });
});

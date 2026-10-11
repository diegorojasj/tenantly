import { describe, expect, test } from 'vitest';

import { matching, ruleText } from './fulfilment';
import type { Offering, Resource, Template } from './types';

const template = {
  presets: [
    { key: 'checkup', label: 'Check-up', plural: 'Check-ups', capacity: 1, time: 'slot', units: ['session'], place: 'on_site', requires: [] },
    { key: 'plan', label: 'Plan', plural: 'Plans', capacity: null, time: 'none', units: ['month'], place: 'on_site', requires: [] },
  ],
  resourceTypes: [
    { key: 'staff', label: 'Dentist', plural: 'Dentists', people: true },
    { key: 'chair', label: 'Chair', plural: 'Chairs', people: false },
  ],
} as unknown as Template;

const resource = (id: string, type: string, role: string, attributes: Resource['attributes'] = {}): Resource => ({
  id,
  locationId: 'l',
  type,
  name: id,
  role,
  attributes,
  parentId: null,
  status: 'available',
});

describe('fulfilment rules', () => {
  test('describes an offering by its rules, naming requirements in the template’s words', () => {
    const checkup = {
      kind: 'checkup',
      minutes: 30,
      unit: 'session',
      capacity: 1,
      time: 'slot',
      place: 'at_customer',
      requires: [
        { type: 'staff', quantity: 1, pick: true, role: 'Dentist' },
        { type: 'chair', quantity: 2, pick: false },
      ],
    } as unknown as Offering;
    expect(ruleText(checkup, template)).toBe('30 min · at the customer · 1 dentist + 2 chair (assigned)');
    expect(ruleText({ ...checkup, capacity: 6, place: 'on_site', requires: [] }, template)).toBe('6 spots · 30 min');
  });

  test('matches resources on type, category and attributes', () => {
    const pool = [resource('a', 'chair', 'Dental', { xray: true }), resource('b', 'chair', 'dental'), resource('c', 'staff', 'Dental')];
    expect(matching(pool, { type: 'chair', quantity: 1 }).map((r) => r.id)).toEqual(['a', 'b']);
    expect(matching(pool, { type: 'chair', quantity: 1, role: 'DENTAL', where: { xray: true } }).map((r) => r.id)).toEqual(['a']);
  });
});

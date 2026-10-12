import { describe, expect, test } from 'vitest';

import { siteClock } from './sites';
import type { ScopeNode } from './types';

const template = { open: 8 * 60, close: 20 * 60 };
const site = (over: Partial<ScopeNode> = {}) => ({ kind: 'location', status: 'active', tz: 'UTC', hours: null, ...over }) as ScopeNode;
// 14:30 UTC: 10:30 in New York (EDT), 23:30 in Tokyo.
const now = new Date('2026-10-12T14:30:00Z');

describe('site clock', () => {
  test('reads open or closed on the location’s own clock and hours', () => {
    expect(siteClock(site(), template, now)).toEqual({ state: 'open', local: '14:30', hours: [480, 1200], next: 1200 });
    expect(siteClock(site({ tz: 'Asia/Tokyo' }), template, now)).toMatchObject({ state: 'closed', local: '23:30', next: 480 });
    expect(siteClock(site({ tz: 'America/New_York', hours: [11 * 60, 19 * 60] }), template, now)).toMatchObject({
      state: 'closed',
      local: '10:30',
      next: 660,
    });
  });

  test('a paused location is paused whatever the time', () => {
    expect(siteClock(site({ status: 'paused' }), template, now).state).toBe('paused');
  });
});

import { describe, expect, test } from 'vitest';

import { clockOf, fmtMoney, fmtStamp, fmtUntil, fromCents, sumMoney, timesMoney, toCents, wallNow, zoneName } from './format';

describe('location time', () => {
  const instant = new Date('2026-01-15T14:30:00Z');

  test('reads now on a location’s wall clock, falling back to UTC for unknown zones', () => {
    expect(wallNow('America/New_York', instant)).toBe('2026-01-15T09:30');
    expect(wallNow('UTC', instant)).toBe('2026-01-15T14:30');
    expect(wallNow('Mars/Olympus', instant)).toBe('2026-01-15T14:30');
  });

  test('names the zone instead of always saying UTC', () => {
    expect(zoneName('America/New_York')).toBe('New York');
    expect(fmtStamp(instant.toISOString(), 'Europe/Lisbon')).toMatch(/14:30 Lisbon$/);
    expect(fmtStamp(instant.toISOString())).toMatch(/14:30 UTC$/);
  });

  test('shows the end day only when a booking spans days', () => {
    expect(fmtUntil('2026-01-15T09:00', '2026-01-15T10:00')).toBe('10:00');
    expect(fmtUntil('2026-01-15T15:00', '2026-01-18T15:00')).toBe('Jan 18 15:00');
    expect(clockOf(540, 1020)).toBe('09:00–17:00');
  });
});

describe('money', () => {
  test('adds and multiplies decimal strings on cents, never through floats', () => {
    expect(sumMoney(['0.10', '0.20'])).toBe('0.30');
    expect(timesMoney('12.10', 3)).toBe('36.30');
    expect(toCents('-4.5')).toBe(-450);
    expect(fromCents(-5)).toBe('-0.05');
    expect(toCents(19.99)).toBe(1999);
  });

  test('formats in the business’s currency', () => {
    expect(fmtMoney('1234.50')).toBe('$1,234.50');
    expect(fmtMoney('9.90', 'EUR')).toBe('€9.90');
    expect(fmtMoney('9.90', 'nope')).toBe('$9.90');
  });
});

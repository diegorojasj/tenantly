import { afterEach, describe, expect, test } from 'vitest';

import { fmtMoney } from './format';
import { negotiate, t } from './i18n';

describe('language', () => {
  afterEach(() => {
    document.documentElement.lang = '';
  });

  test('prefers the cookie, then Accept-Language, then English', () => {
    expect(negotiate('session=x; lang=es', 'en-US,en;q=0.9')).toBe('es');
    expect(negotiate(null, 'es-MX,es;q=0.9,en;q=0.8')).toBe('es');
    expect(negotiate('lang=fr', 'de-DE,fr;q=0.9')).toBe('en');
    expect(negotiate(null, null)).toBe('en');
  });

  test('reads the page language and fills placeholders and plurals', () => {
    expect(t('common.ruleSpots', { count: 1 })).toBe('1 spot');
    document.documentElement.lang = 'es';
    expect(t('common.wholeBusiness')).toBe('Todo el negocio');
    expect(t('common.ruleSpots', { count: 3 })).toBe('3 plazas');
    expect(t('common.movedCancelled', { who: 'Ana' })).toMatch(/^Ana: cancelada/);
  });

  test('formats numbers in the page language', () => {
    document.documentElement.lang = 'es';
    expect(fmtMoney('1234.50', 'EUR')).toMatch(/1234,50|1\.234,50/);
  });
});

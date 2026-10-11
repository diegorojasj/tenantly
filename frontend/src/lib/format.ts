// Pure formatting helpers shared by every view, in the viewer's language
// (src/lib/i18n.ts). Intl formatters are built once per (language, options) —
// constructing them per call is the hidden cost in big tables.
import { locale, t } from './i18n';

const cache = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat | Intl.RelativeTimeFormat>();
function memo<F>(key: string, build: () => F): F {
  let fmt = cache.get(key) as F | undefined;
  if (!fmt) cache.set(key, (fmt = build()) as never);
  return fmt;
}

const compact = () =>
  memo(`compact ${locale()}`, () => new Intl.NumberFormat(locale(), { notation: 'compact', maximumFractionDigits: 1 }));
const whole = () => memo(`whole ${locale()}`, () => new Intl.NumberFormat(locale()));
function currencyFmt(code: string) {
  return memo(`currency ${locale()} ${code}`, () => {
    try {
      return new Intl.NumberFormat(locale(), { style: 'currency', currency: code });
    } catch {
      return new Intl.NumberFormat(locale(), { style: 'currency', currency: 'USD' });
    }
  });
}
/** One formatter per (kind, zone), built on first use. Unknown zones fall back to UTC. */
function inZone(kind: 'stamp' | 'wall', tz: string) {
  // `wall` is a machine format (parsed back into keys), so it never follows the viewer's language.
  const [lang, options] =
    kind === 'stamp'
      ? ([locale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }] as const)
      : (['en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }] as const);
  return memo(`${kind} ${lang} ${tz}`, () => {
    try {
      return new Intl.DateTimeFormat(lang, { ...options, timeZone: tz });
    } catch {
      return new Intl.DateTimeFormat(lang, { ...options, timeZone: 'UTC' });
    }
  });
}
const relative = () =>
  memo(`relative ${locale()}`, () => new Intl.RelativeTimeFormat(locale(), { numeric: 'auto', style: 'short' }));

export const fmtCompact = (n: number) => compact().format(n);
export const fmtNumber = (n: number) => whole().format(n);

// Money arrives as decimal strings ("12.50"). Arithmetic happens on integer
// cents, so 0.10 + 0.20 is 0.30 here too; formatting hands Intl the exact
// decimal string (Intl.NumberFormat v3 formats strings without a float trip).
/** `"12.50"` → 1250. Accepts numbers for literals typed in forms. */
export function toCents(amount: string | number): number {
  const text = typeof amount === 'number' ? amount.toFixed(2) : amount.trim();
  const match = /^(-)?(\d*)(?:\.(\d{0,2})\d*)?$/.exec(text);
  if (!match) return 0;
  const cents = Number(match[2] || '0') * 100 + Number((match[3] ?? '').padEnd(2, '0'));
  return match[1] ? -cents : cents;
}
/** 1250 → `"12.50"`. */
export function fromCents(cents: number): string {
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(Math.round(cents));
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`;
}
export const sumMoney = (amounts: Array<string>) => fromCents(amounts.reduce((s, a) => s + toCents(a), 0));
/** An amount times a whole count (hours, nights, seats). */
export const timesMoney = (amount: string, count: number) => fromCents(toCents(amount) * count);
/** For chart heights and comparisons only — never for sums. */
export const moneyValue = (amount: string) => toCents(amount) / 100;
/** `$12.50`, `€12.50`: in the business's currency (USD when not given). */
export const fmtMoney = (amount: string | number, currency = 'USD') =>
  currencyFmt(currency).format(fromCents(toCents(amount)) as unknown as number);
/** An instant in a location's zone (UTC by default), named, so server and client render the same string. */
export const fmtStamp = (iso: string, tz = 'UTC') => `${inZone('stamp', tz).format(new Date(iso))} ${zoneName(tz)}`;

/** `New York` for `America/New_York`; `UTC` stays `UTC`. */
export const zoneName = (tz: string) => (tz.split('/').at(-1) ?? tz).replaceAll('_', ' ');

/** Now as a wall-clock `YYYY-MM-DDTHH:MM` in `tz`, comparable with booking times. */
export function wallNow(tz = 'UTC', now = new Date()) {
  const parts = Object.fromEntries(inZone('wall', tz).formatToParts(now).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

const pad2 = (n: number) => String(n).padStart(2, '0');
/** `09:00` for minute 540; with a second minute, `09:00–17:00`. */
export const clockOf = (from: number, to?: number): string =>
  to === undefined ? `${pad2(Math.floor(from / 60))}:${pad2(from % 60)}` : `${clockOf(from)}–${clockOf(to)}`;

/** What one unit of a priced offering is called: `/h`, `/night`… */
export const perUnit = (unit: string) =>
  ({ hour: t('common.perHour'), day: t('common.perDay'), night: t('common.perNight'), month: t('common.perMonth') })[unit] ?? '';

export function fmtAgo(iso: string, now = Date.now()) {
  const seconds = (Date.parse(iso) - now) / 1000;
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['day', 86_400],
    ['hour', 3_600],
    ['minute', 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return relative().format(Math.round(seconds / size), unit);
  }
  return t('common.justNow');
}

export const pct = (used: number, limit: number) =>
  Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));

const pad = (n: number) => String(n).padStart(2, '0');
const dayFmt = () =>
  memo(`day ${locale()}`, () => new Intl.DateTimeFormat(locale(), { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'UTC' }));

/** `09:30–11:00` from a wall-clock start and a duration. */
export function fmtSpan(start: string, minutes: number) {
  const from = Number(start.slice(11, 13)) * 60 + Number(start.slice(14, 16));
  const to = from + minutes;
  return `${start.slice(11, 16)}–${pad(Math.floor(to / 60))}:${pad(to % 60)}`;
}

/** `Saturday, Oct 10` for a `YYYY-MM-DD` key. */
export const fmtDay = (day: string) => dayFmt().format(new Date(`${day}T12:00:00Z`));

/** A booking's end beside its start: `11:00`, or `Oct 13 11:00` when it ends on a later day. */
export const fmtUntil = (start: string, end: string) =>
  end.slice(0, 10) === start.slice(0, 10) ? end.slice(11) : `${shortDay().format(new Date(`${end.slice(0, 10)}T12:00:00Z`))} ${end.slice(11)}`;
const shortDay = () =>
  memo(`short ${locale()}`, () => new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric', timeZone: 'UTC' }));

/** Shift a `YYYY-MM-DD` key by whole days. */
export function shiftDay(day: string, by: number) {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + by);
  return d.toISOString().slice(0, 10);
}

export const fmtDuration = (minutes: number) =>
  minutes < 60
    ? t('common.minutes', { n: minutes })
    : `${Math.floor(minutes / 60)}h${minutes % 60 ? ` ${minutes % 60}m` : ''}`;

/** Drops `undefined` fields: server-function arguments must be plain JSON. */
export const defined = <T extends object>(input: T) =>
  Object.fromEntries(Object.entries(input).filter(([, v]) => v !== undefined)) as T;

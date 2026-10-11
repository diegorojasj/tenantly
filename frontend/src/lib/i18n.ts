// Interface language: English or Spanish. The choice lives in a `lang` cookie
// (falling back to the browser's Accept-Language), so the server renders the
// page in the viewer's language and the client hydrates the same strings —
// it reads the language back off <html lang>, which Document writes. Changing
// it rewrites the cookie and reloads, so every string, formatter and cached
// server message turns over at once; nothing here has to be reactive.
//
// Messages live per area under src/locales and are addressed as
// `area.key` — t('billing.title'). Tenant data (template terms, names,
// statuses the business words itself) is the business's own and is never
// translated here.
import { getRequestEvent, isServer } from '@solidjs/web';

import { messages } from '../locales';
import type { Message, MessageKey } from '../locales';

export const locales = ['en', 'es'] as const;
export type Locale = (typeof locales)[number];

export const localeNames: Record<Locale, string> = { en: 'English', es: 'Español' };

const COOKIE = 'lang';
const isLocale = (v: unknown): v is Locale => locales.includes(v as Locale);

/** `lang` cookie first, then the first supported Accept-Language entry, else English. */
export function negotiate(cookie: string | null, acceptLanguage: string | null): Locale {
  const chosen = cookie?.match(/(?:^|;\s*)lang=([^;]*)/)?.[1];
  if (isLocale(chosen)) return chosen;
  for (const part of (acceptLanguage ?? '').split(',')) {
    const base = part.trim().split(';')[0].split('-')[0].toLowerCase();
    if (isLocale(base)) return base;
  }
  return 'en';
}

const perRequest = new WeakMap<Request, Locale>();

/** The current viewer's language: per request on the server, per page load in the browser. */
export function locale(): Locale {
  if (isServer) {
    const request = getRequestEvent()?.request;
    if (!request) return 'en';
    let found = perRequest.get(request);
    if (!found) {
      found = negotiate(request.headers.get('cookie'), request.headers.get('accept-language'));
      perRequest.set(request, found);
    }
    return found;
  }
  const lang = document.documentElement.lang;
  return isLocale(lang) ? lang : 'en';
}

/** Remember the choice for a year and re-render everything in it. */
export function setLocale(next: Locale) {
  document.cookie = `${COOKIE}=${next}; path=/; max-age=${60 * 60 * 24 * 365}; samesite=lax`;
  location.reload();
}

const plurals = new Map<Locale, Intl.PluralRules>();
const pluralOf = (l: Locale) => {
  let rules = plurals.get(l);
  if (!rules) plurals.set(l, (rules = new Intl.PluralRules(l)));
  return rules;
};

export type Params = Record<string, string | number>;

function pick(message: Message, l: Locale, params?: Params): string {
  if (typeof message === 'string') return message;
  const count = Number(params?.count ?? 0);
  return count === 0 && message.zero !== undefined
    ? message.zero
    : pluralOf(l).select(count) === 'one'
      ? message.one
      : message.other;
}

/**
 * The message for `key` in the viewer's language, with `{name}` placeholders
 * filled from `params`. Plural messages pick their form from `params.count`.
 */
export function t(key: MessageKey, params?: Params): string {
  const l = locale();
  const text = pick(messages[l][key] ?? messages.en[key], l, params);
  return params ? text.replace(/\{(\w+)\}/g, (all, name: string) => (name in params ? String(params[name]) : all)) : text;
}

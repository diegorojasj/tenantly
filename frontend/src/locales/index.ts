// Every area's messages, flattened to `area.key` per language (see src/lib/i18n.ts).
import common from './common';
import gateway from './gateway';
import shell from './shell';
import today from './today';
import calendar from './calendar';
import bookings from './bookings';
import booking from './booking';
import customers from './customers';
import catalog from './catalog';
import resources from './resources';
import payments from './payments';
import insights from './insights';
import billing from './billing';
import audit from './audit';
import structure from './structure';
import access from './access';
import config from './config';
import settings from './settings';
import type { Message } from './define';

export type { Message, Plural } from './define';

const areas = {
  common,
  gateway,
  shell,
  today,
  calendar,
  bookings,
  booking,
  customers,
  catalog,
  resources,
  payments,
  insights,
  billing,
  audit,
  structure,
  access,
  config,
  settings,
};

type Areas = typeof areas;
export type MessageKey = {
  [A in keyof Areas & string]: `${A}.${keyof Areas[A]['en'] & string}`;
}[keyof Areas & string];

function flatten(lang: 'en' | 'es') {
  const out: Record<string, Message> = {};
  for (const [area, bundle] of Object.entries(areas)) {
    for (const [key, message] of Object.entries(bundle[lang] as Record<string, Message>)) out[`${area}.${key}`] = message;
  }
  return out as Record<MessageKey, Message>;
}

export const messages = { en: flatten('en'), es: flatten('es') };

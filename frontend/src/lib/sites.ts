// A location's live state for the Locations page and its map: paused, open
// now, or closed — read on the location's own wall clock against its own
// hours (or the template's). Pure, so the server render and the browser agree.
import { wallNow } from './format';
import type { ScopeNode, Template } from './types';

export type SiteState = 'open' | 'closed' | 'paused';

export interface SiteClock {
  state: SiteState;
  /** `HH:MM` on the location's clock. */
  local: string;
  hours: [number, number];
  /** Minute of the day the state next flips (closing when open, opening when closed). */
  next: number;
}

/** Where a location stands right now, on its own clock. */
export function siteClock(node: ScopeNode, template: Pick<Template, 'open' | 'close'>, now = new Date()): SiteClock {
  const hours = node.hours ?? [template.open, template.close];
  const local = wallNow(node.tz ?? 'UTC', now).slice(11, 16);
  const minute = Number(local.slice(0, 2)) * 60 + Number(local.slice(3, 5));
  const open = minute >= hours[0] && minute < hours[1];
  if (node.status === 'paused') return { state: 'paused', local, hours, next: hours[0] };
  return { state: open ? 'open' : 'closed', local, hours, next: open ? hours[1] : hours[0] };
}

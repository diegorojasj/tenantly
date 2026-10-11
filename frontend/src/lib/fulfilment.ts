// Fulfilment rules and resource types (docs/PLATFORM.md gaps 3-4): the
// template defines both; offerings carry their own copy of the rules.
import { fmtDuration } from './format';
import { t as tr } from './i18n';
import type { Offering, Preset, Requirement, Resource, ResourceType, Template } from './types';

/** The template's definition of a resource type; a plain one named after the key if it has none. */
export function resourceType(t: Template, key: string): ResourceType {
  return t.resourceTypes.find((r) => r.key === key) ?? { key, label: key[0].toUpperCase() + key.slice(1), plural: key, people: false };
}

export const presetOf = (t: Template, key: string): Preset | undefined => t.presets.find((p) => p.key === key);

/** Booked as a session several customers join. */
export const isShared = (o: Pick<Offering, 'capacity'>) => (o.capacity ?? 1) > 1;

/** A preset's label for an offering kind (falls back to the key). */
export const kindLabel = (t: Template, kind: string) => presetOf(t, kind)?.label ?? kind[0].toUpperCase() + kind.slice(1);

/** What one requirement names: its category, else its type's label. */
export const requirementName = (t: Template, r: Requirement) => (r.role || resourceType(t, r.type).label).toLowerCase();

/** Resources at hand that could fill a requirement. */
export const matching = (resources: Array<Resource>, r: Requirement) =>
  resources.filter(
    (x) =>
      x.type === r.type &&
      (!r.role || x.role.toLowerCase() === r.role.toLowerCase()) &&
      Object.entries(r.where ?? {}).every(([k, v]) => x.attributes[k] === v),
  );

/** The offering's rules, in the tenant's words. */
export function ruleText(o: Offering, t: Template) {
  if (o.time === 'none') return o.unit === 'pack' ? tr('common.ruleCredits', { count: o.credits ?? 0 }) : tr('common.ruleMonthly');
  const parts: Array<string> = [];
  if (isShared(o)) parts.push(tr('common.ruleSpots', { count: o.capacity ?? 1 }));
  if (o.time === 'slot') parts.push(fmtDuration(o.minutes));
  if (o.time === 'window') parts.push(tr('common.ruleWindow', { duration: fmtDuration(o.minutes) }));
  if (o.time === 'span') parts.push(tr(`common.ruleSpan_${o.unit as 'day' | 'night' | 'month'}`));
  if (o.place === 'at_customer') parts.push(tr('common.ruleAtCustomer'));
  const needs = o.requires.map((r) => `${r.quantity} ${requirementName(t, r)}${r.pick ? '' : ` ${tr('common.ruleAssigned')}`}`);
  if (needs.length) parts.push(needs.join(' + '));
  return parts.join(' · ');
}

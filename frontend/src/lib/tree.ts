// The location tree's vocabulary (docs/PLATFORM.md gap 8). Templates name the
// group levels between the business and its locations (area; region →
// franchisee…), so the UI never hard-codes "area". Pure helpers, safe on both
// sides of the server-function boundary.
import { t as tr } from './i18n';
import type { ScopeNode, Template, TreeLevel } from './types';

/** The template's group levels; one "Area" level for templates that list none. */
export const levelsOf = (t: Template): Array<TreeLevel> =>
  t.levels?.length ? t.levels : [{ key: 'area', label: tr('common.area'), plural: tr('common.areas') }];

/** A group's level; a level the template no longer lists reads as its last one. */
export function levelOf(t: Template, node: Pick<ScopeNode, 'kind' | 'level'>): TreeLevel | null {
  if (node.kind !== 'region') return null;
  const levels = levelsOf(t);
  return levels.find((l) => l.key === node.level) ?? levels.at(-1)!;
}

/** `Business`, the level's label (`Franchisee`), or the template's word for a location (`Club`). */
export function kindLabel(t: Template, node: Pick<ScopeNode, 'kind' | 'level'>): string {
  if (node.kind === 'org') return tr('common.business');
  if (node.kind === 'location') return t.terms.location;
  return levelOf(t, node)!.label;
}

/** How a place reads in a picker: `Whole business`, `Area · Manhattan`, `Union Square`. */
export function placeLabel(t: Template, node: ScopeNode): string {
  if (node.kind === 'org') return tr('common.wholeBusiness');
  if (node.kind === 'location') return node.name;
  return `${kindLabel(t, node)} · ${node.name}`;
}

/** Levels a new group directly under `parent` may take: any deeper than the parent's own. */
export function childLevels(t: Template, parent: Pick<ScopeNode, 'kind' | 'level'>): Array<TreeLevel> {
  const levels = levelsOf(t);
  if (parent.kind === 'location') return [];
  if (parent.kind === 'org') return levels;
  const at = levels.findIndex((l) => l.key === levelOf(t, parent)!.key);
  return levels.slice(at + 1);
}

// Typed custom fields and documents (docs/PLATFORM.md gap 6). The template
// defines them; the services validate them. These helpers read a form into
// a typed map and show stored values back.
import { t } from './i18n';
import type { AttributeValue, FieldDef, FieldEntity, Template } from './types';

/** The template's fields for one entity (customer, account, offering, booking). */
export const fieldsOf = (t: Template, entity: FieldEntity): Array<FieldDef> => t.fields?.[entity] ?? [];

/** Read `prefix + key` inputs into a typed map; blank values are left out (booleans are always sent). */
export function readFields(defs: Array<FieldDef>, data: FormData, prefix: string): Record<string, AttributeValue> {
  const out: Record<string, AttributeValue> = {};
  for (const d of defs) {
    const raw = data.get(`${prefix}${d.key}`);
    if (d.type === 'bool') out[d.key] = raw !== null;
    else if (raw !== null && String(raw).trim() !== '') out[d.key] = d.type === 'number' ? Number(raw) : String(raw);
  }
  return out;
}

export const showValue = (v: AttributeValue | undefined) =>
  v === undefined || v === '' ? '—' : v === true ? t('common.yes') : v === false ? t('common.no') : String(v);

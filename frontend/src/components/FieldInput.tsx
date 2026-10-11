import { For, Show } from 'solid-js';

import { t } from '../lib/i18n';
import type { FieldDef } from '../lib/types';

/** One input per typed field, named `prefix + key` (read back with lib/fields.ts `readFields`). */
export default function FieldInput(props: { def: FieldDef; prefix: string }) {
  const name = () => `${props.prefix}${props.def.key}`;
  return (
    <label>
      <span class="form-label">
        {props.def.label}
        {props.def.required ? '' : ` ${t('common.optional')}`}
      </span>
      <Show when={props.def.type === 'choice'}>
        <select name={name()} required={props.def.required}>
          <Show when={!props.def.required}>
            <option value="">—</option>
          </Show>
          <For each={props.def.options ?? []}>{(o) => <option value={o}>{o}</option>}</For>
        </select>
      </Show>
      <Show when={props.def.type === 'bool'}>
        <input type="checkbox" name={name()} />
      </Show>
      <Show when={props.def.type === 'date'}>
        <input type="date" name={name()} required={props.def.required} />
      </Show>
      <Show when={props.def.type === 'number' || props.def.type === 'text'}>
        <input type={props.def.type === 'number' ? 'number' : 'text'} name={name()} step="any" required={props.def.required} />
      </Show>
    </label>
  );
}

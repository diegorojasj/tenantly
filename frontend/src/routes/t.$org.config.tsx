import { useMutation, useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createMemo, For, Match, Show, Switch } from 'solid-js';

import Icon from '../components/Icon';
import { KindGlyph, PageHead, Panel } from '../components/ui';
import { configQuery, prefetch, tenantQuery } from '../lib/queries';
import { t } from '../lib/i18n';
import { useTenantScope } from '../lib/scope';
import { kindLabel } from '../lib/tree';
import { notify } from '../lib/toast';
import { overrideSetting } from '../lib/tenancy';
import type { ResolvedSetting, SettingDef, SettingValue } from '../lib/types';

// Per-tenant configuration without custom code: every setting resolves down
// the cascade platform → organization → region → location, and the deepest
// explicit value wins. The cascade strip on each row shows exactly where the
// effective value comes from — and what it shadows.
export const Route = createFileRoute('/t/$org/config')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, configQuery(params.org, deps.scope));
  },
  head: () => ({ meta: [{ title: t('config.pageTitle') }] }),
  component: ConfigPage,
});

function ConfigPage() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const config = useQuery(() => configQuery(org(), scope()));

  const groups = createMemo(() => {
    const map = new Map<string, Array<ResolvedSetting>>();
    for (const s of config.data) map.set(s.def.group, [...(map.get(s.def.group) ?? []), s]);
    return [...map];
  });
  const localCount = () => config.data.filter((s) => s.source === s.trail.length - 1 && s.trail.length > 1).length;

  const save = useMutation(() => ({
    mutationFn: (input: { key: string; value: SettingValue | null }) =>
      overrideSetting({ org: org(), scope: ctx.data.scopeId, ...input }),
    onSuccess: (_r, input) => {
      const label = config.data.find((x) => x.def.key === input.key)?.def.label ?? input.key;
      notify(
        input.value === null
          ? t('config.toastReset', { label })
          : t('config.toastSaved', { label, place: ctx.data.path.at(-1)!.name }),
      );
    },
  }));
  const busy = (key: string) => save.isPending && save.variables?.key === key;

  return (
    <div class="page">
      <PageHead
        eyebrow={t('config.eyebrow', { level: kindLabel(ctx.data.tenant.template, ctx.data.path.at(-1)!).toLowerCase() })}
        title={t('config.title')}
        lede={t('config.lede', { place: ctx.data.path.at(-1)!.name })}
      >
        <div class="posture">
          <span>
            <strong>{localCount()}</strong> {t('config.setLocally')}
          </span>
          <span>
            <strong>{config.data.length - localCount()}</strong> {t('config.inherited')}
          </span>
        </div>
      </PageHead>

      <Show when={save.error}>{(error) => <p role="alert" class="error banner">{error()?.message}</p>}</Show>

      <For each={groups()}>
        {([group, settings]) => (
          <Panel title={group} icon="config">
            <ul class="settings">
              <For each={settings}>
                {(s) => (
                  <li class={['setting', { busy: busy(s.def.key) }]}>
                    <div class="setting-main">
                      <strong>{s.def.label}</strong>
                      <span class="muted">{s.def.hint}</span>
                      <code class="setting-key">{s.def.key}</code>
                    </div>
                    <Cascade setting={s} />
                    <div class="setting-edit">
                      <Editor
                        setting={s}
                        disabled={!s.editable || busy(s.def.key)}
                        onCommit={(value) => save.mutate({ key: s.def.key, value })}
                      />
                      <Show when={s.editable && s.trail.at(-1)!.value !== undefined && s.trail.length > 1}>
                        <button
                          type="button"
                          class="icon-btn"
                          title={t('config.resetTitle')}
                          aria-label={t('config.resetLabel', { label: s.def.label })}
                          disabled={busy(s.def.key)}
                          onClick={() => save.mutate({ key: s.def.key, value: null })}
                        >
                          <Icon name="reset" size={16} />
                        </button>
                      </Show>
                      <Show when={!s.editable}>
                        <span class="muted" title={t('config.requires', { guard: s.def.guard })}>
                          <Icon name="lock" size={14} />
                        </span>
                      </Show>
                    </div>
                  </li>
                )}
              </For>
            </ul>
          </Panel>
        )}
      </For>
    </div>
  );
}

const show = (def: SettingDef, v: SettingValue | undefined) =>
  v === undefined
    ? '—'
    : typeof v === 'boolean'
      ? v
        ? t('config.on')
        : t('config.off')
      : (def.optionLabels?.[String(v)] ?? String(v));

/** Platform → … → focus, with the winning layer lit and shadowed ones struck. */
function Cascade(props: { setting: ResolvedSetting }) {
  return (
    <ol class="cascade" aria-label={t('config.cascadeLabel')}>
      <For each={props.setting.trail}>
        {(step, i) => (
          <li
            class={{
              set: step.value !== undefined,
              wins: i() === props.setting.source,
              shadowed: step.value !== undefined && i() < props.setting.source,
            }}
            title={`${step.label}: ${show(props.setting.def, step.value)}`}
          >
            <KindGlyph kind={step.kind} />
            <span class="cascade-label">{step.label}</span>
            <span class="cascade-value">{show(props.setting.def, step.value)}</span>
          </li>
        )}
      </For>
    </ol>
  );
}

function Editor(props: {
  setting: ResolvedSetting;
  disabled: boolean;
  onCommit: (value: SettingValue) => void;
}) {
  const def = () => props.setting.def;
  return (
    <Switch>
      <Match when={def().type === 'bool'}>
        <button
          type="button"
          role="switch"
          class="toggle"
          aria-checked={props.setting.value === true ? 'true' : 'false'}
          aria-label={def().label}
          disabled={props.disabled}
          onClick={() => props.onCommit(!props.setting.value)}
        >
          <span />
        </button>
      </Match>
      <Match when={def().type === 'enum'}>
        <select
          aria-label={def().label}
          value={String(props.setting.value)}
          disabled={props.disabled}
          onChange={(event) => props.onCommit(event.currentTarget.value)}
        >
          <For each={def().options}>{(o) => <option value={o}>{def().optionLabels?.[o] ?? o}</option>}</For>
        </select>
      </Match>
      <Match when={def().type === 'number'}>
        <label class="unit-input">
          <input
            type="number"
            aria-label={def().label}
            value={String(props.setting.value)}
            disabled={props.disabled}
            onChange={(event) => {
              const n = event.currentTarget.valueAsNumber;
              if (Number.isFinite(n)) props.onCommit(n);
            }}
          />
          <span>{def().unit}</span>
        </label>
      </Match>
      <Match when={def().type === 'text'}>
        <input
          type="text"
          aria-label={def().label}
          value={String(props.setting.value)}
          disabled={props.disabled}
          maxlength={12}
          onChange={(event) => {
            const v = event.currentTarget.value.trim();
            if (v) props.onCommit(v);
          }}
        />
      </Match>
    </Switch>
  );
}

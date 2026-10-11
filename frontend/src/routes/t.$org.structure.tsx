import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { createSignal, For, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import Icon from '../components/Icon';
import { PageHead, Panel } from '../components/ui';
import { tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { addLocation, updateLocation } from '../lib/tenancy';
import { clockOf, zoneName } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { notify } from '../lib/toast';
import { childLevels, levelOf, levelsOf } from '../lib/tree';
import type { ScopeNode, TreeLevel } from '../lib/types';

// Locations: the tree that scopes every other page — the business, groups on
// the template's named levels (an area; or region → franchisee, any depth),
// and locations. Owners and admins grow it here; everyone else uses it to
// focus. It reads the shell's tenant query, so the route needs no loader.
export const Route = createFileRoute('/t/$org/structure')({
  head: () => ({ meta: [{ title: tr('structure.pageTitle') }] }),
  component: StructurePage,
});

function StructurePage() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const template = () => ctx.data.tenant.template;
  const t = () => template().terms;
  const levels = () => levelsOf(template());
  const nodes = () => ctx.data.nodes;
  const root = () => nodes().find((n) => n.kind === 'org')!;
  const childrenOf = (id: string) => nodes().filter((n) => n.parentId === id);
  const groups = () => nodes().filter((n) => n.kind === 'region');
  const canEdit = () => ctx.data.role.permissions.some((p) => p === 'tenant.manage' || p === 'roles.assign');
  const onPath = (id: string) => ctx.data.path.some((n) => n.id === id);
  /** What is being added: a location, or a group on `level`, under `parentId`. */
  const [adding, setAdding] = createSignal<null | { kind: 'region' | 'location'; parentId: string; level?: string }>(
    null,
    { name: 'addingNode' },
  );

  const add = useMutation(() => ({
    mutationFn: (input: { parentId: string; kind: 'region' | 'location'; name: string; level?: string }) =>
      addLocation({ org: org(), ...input }),
    onSuccess: (_r, input) => {
      notify(tr('structure.toastAdded', { name: input.name }));
      setAdding(null);
    },
  }));
  const update = useMutation(() => ({
    mutationFn: ({ label: _label, ...input }: Omit<Parameters<typeof updateLocation>[0], 'org'> & { label: string }) =>
      updateLocation({ org: org(), ...input }),
    onSuccess: (_r, input) => notify(input.label),
  }));

  const Tile = (p: { node: ScopeNode }) => (
    <div class={['tile', { focused: onPath(p.node.id), locked: !p.node.reachable }]} data-status={p.node.status}>
      <span class="tile-code">{p.node.code}</span>
      <Show when={p.node.reachable} fallback={<span class="tile-name">{p.node.name}</span>}>
        <Link to="." search={{ scope: p.node.id }} class="tile-name">
          {p.node.name}
        </Link>
      </Show>
      <span class="tile-foot">
        <span class={['status', `status-${p.node.status}`]} /> {p.node.status === 'paused' ? tr('structure.paused') : tr('structure.open')}
        <span class="muted">
          {' '}· {clockOf(...(p.node.hours ?? [ctx.data.tenant.template.open, ctx.data.tenant.template.close]))}
          {p.node.tz && p.node.tz !== 'UTC' ? ` ${zoneName(p.node.tz)}` : ' UTC'}
        </span>
      </span>
      <Show when={canEdit() && p.node.reachable}>
        <span class="tile-actions">
          <Rename node={p.node} onSave={(name) => update.mutate({ nodeId: p.node.id, name, label: tr('structure.toastRenamed', { name }) })} />
          <Show when={p.node.kind === 'location'}>
            <Hours
              node={p.node}
              onSave={(tz, hours) => update.mutate({ nodeId: p.node.id, tz, hours, label: tr('structure.toastHoursSaved', { name: p.node.name }) })}
            />
          </Show>
          <Show
            when={p.node.status !== 'paused'}
            fallback={
              <button
                type="button"
                class="btn small ghost"
                onClick={() => update.mutate({ nodeId: p.node.id, status: 'active', label: tr('structure.toastReopened', { name: p.node.name }) })}
              >
                {tr('structure.reopen')}
              </button>
            }
          >
            <ConfirmButton
              class="small ghost"
              label={tr('structure.pause')}
              confirm={tr('structure.pauseConfirm')}
              onConfirm={() =>
                update.mutate({ nodeId: p.node.id, status: 'paused', label: tr('structure.toastPaused', { name: p.node.name }) })
              }
            />
          </Show>
        </span>
      </Show>
    </div>
  );

  // Where a new group on `level` may go: the business or a group on a higher level, inside the viewer's reach.
  const parentsFor = (level: TreeLevel) =>
    [root(), ...groups()].filter((n) => n.reachable && childLevels(template(), n).some((l) => l.key === level.key));
  const placeName = (n: ScopeNode) => (n.kind === 'org' ? tr('structure.notInGroup') : tr('structure.inGroup', { name: n.name, level: levelOf(template(), n)!.label }));

  /** A group's frame: its locations as tiles, then its own groups, nested as deep as the levels go. */
  const Group = (p: { node: ScopeNode }) => {
    const level = () => levelOf(template(), p.node)!;
    const below = () => childLevels(template(), p.node);
    return (
      <section class={['region-frame', { focused: onPath(p.node.id), locked: !p.node.reachable }]}>
        <div class="frame-label">
          <span class="muted">{level().label} · </span>
          <Show when={p.node.reachable} fallback={<span>{p.node.name}</span>}>
            <Link to="." search={{ scope: p.node.id }}>
              {p.node.name}
            </Link>
          </Show>
          <span class="muted mono"> {p.node.code}</span>
        </div>
        <div class="tiles">
          <For
            each={childrenOf(p.node.id).filter((n) => n.kind === 'location')}
            fallback={
              <Show when={!childrenOf(p.node.id).length}>
                <p class="muted hint">{tr('structure.emptyGroup', { level: level().label.toLowerCase() })}</p>
              </Show>
            }
          >
            {(loc) => <Tile node={loc} />}
          </For>
        </div>
        <Show when={childrenOf(p.node.id).some((n) => n.kind === 'region')}>
          <div class="regions nested">
            <For each={childrenOf(p.node.id).filter((n) => n.kind === 'region')}>{(g) => <Group node={g} />}</For>
          </div>
        </Show>
        <Show when={canEdit() && p.node.reachable}>
          <div class="tree-actions">
            <button type="button" class="btn small ghost" onClick={() => setAdding({ kind: 'location', parentId: p.node.id })}>
              <Icon name="plus" size={14} /> {tr('structure.addHere', { name: t().location })}
            </button>
            <Show when={below()[0]}>
              {(next) => (
                <button
                  type="button"
                  class="btn small ghost"
                  onClick={() => setAdding({ kind: 'region', parentId: p.node.id, level: next().key })}
                >
                  <Icon name="plus" size={14} /> {tr('structure.addHere', { name: next().label })}
                </button>
              )}
            </Show>
          </div>
        </Show>
      </section>
    );
  };

  const loose = () => childrenOf(root().id).filter((n) => n.kind === 'location');
  const topGroups = () => childrenOf(root().id).filter((n) => n.kind === 'region');

  return (
    <div class="page">
      <PageHead
        eyebrow={[tr('structure.business'), ...levels().map((l) => l.label), t().location].join(' → ')}
        title={t().locations}
        lede={tr('structure.lede', {
          locations: t().locations.toLowerCase(),
          levels: levels()
            .map((l) => l.plural.toLowerCase())
            .join(tr('structure.and')),
        })}
      >
        <Show when={canEdit()}>
          <button
            type="button"
            class="btn ghost"
            onClick={() => setAdding({ kind: 'region', parentId: root().id, level: levels()[0].key })}
          >
            <Icon name="plus" size={16} /> {tr('structure.addButton', { name: levels()[0].label.toLowerCase() })}
          </button>
          <button type="button" class="btn" onClick={() => setAdding({ kind: 'location', parentId: root().id })}>
            <Icon name="plus" size={16} /> {tr('structure.addButton', { name: t().location.toLowerCase() })}
          </button>
        </Show>
      </PageHead>

      <Show when={adding()}>
        {(target) => {
          const level = () => levels().find((l) => l.key === target().level) ?? levels()[0];
          const parents = () =>
            target().kind === 'region'
              ? parentsFor(level())
              : [root(), ...groups()].filter((n) => n.reachable);
          return (
            <Panel
              title={tr('structure.newTitle', { name: (target().kind === 'region' ? level().label : t().location).toLowerCase() })}
              icon="structure"
            >
              <form
                class="inline-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const d = new FormData(event.currentTarget);
                  add.mutate({
                    kind: target().kind,
                    parentId: String(d.get('parent')),
                    name: String(d.get('name')),
                    ...(target().kind === 'region' ? { level: level().key } : {}),
                  });
                }}
              >
                <input type="text" name="name" required minlength="2" placeholder={tr('structure.namePlaceholder')} />
                <Show when={target().kind === 'region' && levels().length > 1}>
                  <select
                    aria-label={tr('structure.levelLabel')}
                    value={level().key}
                    onChange={(event) => setAdding({ ...target(), level: event.currentTarget.value })}
                  >
                    <For each={levels()}>{(l) => <option value={l.key}>{l.label}</option>}</For>
                  </select>
                </Show>
                <Show
                  when={parents().length > 1}
                  fallback={<input type="hidden" name="parent" value={parents()[0]?.id ?? target().parentId} />}
                >
                  <select name="parent" aria-label={tr('structure.whereLabel')} value={parents().some((n) => n.id === target().parentId) ? target().parentId : parents()[0]?.id}>
                    <For each={parents()}>{(n) => <option value={n.id}>{placeName(n)}</option>}</For>
                  </select>
                </Show>
                <button type="submit" class="btn" disabled={add.isPending || !parents().length}>
                  {tr('structure.add')}
                </button>
                <button type="button" class="btn ghost" onClick={() => setAdding(null)}>
                  {tr('structure.cancel')}
                </button>
              </form>
              <Show when={add.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
            </Panel>
          );
        }}
      </Show>
      <Show when={update.error}>{(error) => <p role="alert" class="error banner">{error()?.message}</p>}</Show>

      <Panel class="containment">
        <div class={['org-frame', { focused: ctx.data.scopeId === root().id }]}>
          <div class="frame-label">
            <span class="mono">{root().code}</span> {root().name}
            <span class="muted">
              {' '}·{' '}
              {levels()
                .map((l) => {
                  const n = groups().filter((g) => levelOf(template(), g)!.key === l.key).length;
                  return `${n} ${(n === 1 ? l.label : l.plural).toLowerCase()}`;
                })
                .join(' · ')}{' '}
              · {nodes().filter((n) => n.kind === 'location').length} {t().locations.toLowerCase()}
            </span>
          </div>
          <div class="regions">
            <For each={topGroups()}>{(g) => <Group node={g} />}</For>
            <Show when={loose().length}>
              <section class="region-frame loose">
                <div class="frame-label muted">{topGroups().length ? tr('structure.notInGroup') : t().locations}</div>
                <div class="tiles">
                  <For each={loose()}>{(loc) => <Tile node={loc} />}</For>
                </div>
              </section>
            </Show>
          </div>
        </div>
      </Panel>
    </div>
  );
}

/** Inline rename: a small button that turns into a one-field form. */
function Rename(props: { node: ScopeNode; onSave: (name: string) => void }) {
  const [editing, setEditing] = createSignal(false, { name: 'renaming' });
  return (
    <Show
      when={editing()}
      fallback={
        <button type="button" class="btn small ghost" onClick={() => setEditing(true)}>
          {tr('structure.rename')}
        </button>
      }
    >
      <form
        class="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          const name = String(new FormData(event.currentTarget).get('name')).trim();
          if (name && name !== props.node.name) props.onSave(name);
          setEditing(false);
        }}
      >
        <input type="text" name="name" value={props.node.name} required minlength="2" />
        <button type="submit" class="btn small">
          {tr('structure.save')}
        </button>
      </form>
    </Show>
  );
}

const toMinutes = (value: string) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3, 5));
const zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];

/** A location's time zone and its own opening hours; empty hours fall back to the template's. */
function Hours(props: { node: ScopeNode; onSave: (tz: string, hours: [number, number] | null) => void }) {
  const [editing, setEditing] = createSignal(false, { name: 'editingHours' });
  return (
    <Show
      when={editing()}
      fallback={
        <button type="button" class="btn small ghost" onClick={() => setEditing(true)}>
          {tr('structure.hours')}
        </button>
      }
    >
      <form
        class="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          const [open, close] = [String(d.get('open') ?? ''), String(d.get('close') ?? '')];
          props.onSave(String(d.get('tz')).trim() || 'UTC', open && close ? [toMinutes(open), toMinutes(close)] : null);
          setEditing(false);
        }}
      >
        <input type="text" name="tz" value={props.node.tz ?? 'UTC'} list="time-zones" required aria-label={tr('structure.timeZone')} />
        <datalist id="time-zones">
          <For each={zones}>{(z) => <option value={z} />}</For>
        </datalist>
        <input type="time" name="open" step="1800" value={props.node.hours ? clockOf(props.node.hours[0]) : ''} aria-label={tr('structure.opens')} />
        <input type="time" name="close" step="1800" value={props.node.hours ? clockOf(props.node.hours[1]) : ''} aria-label={tr('structure.closes')} />
        <button type="submit" class="btn small">
          {tr('structure.save')}
        </button>
        <span class="muted hint">{tr('structure.hoursHint')}</span>
      </form>
    </Show>
  );
}

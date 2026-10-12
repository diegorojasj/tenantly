import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { createMemo, createSignal, For, onSettled, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import Icon from '../components/Icon';
import SiteMap, { type MapSite } from '../components/SiteMap';
import { PageHead, Panel, Stat } from '../components/ui';
import { tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { addLocation, updateLocation } from '../lib/tenancy';
import { clockOf, zoneName } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { notify } from '../lib/toast';
import { siteClock, type SiteClock } from '../lib/sites';
import { childLevels, levelOf, levelsOf } from '../lib/tree';
import type { ScopeNode, TreeLevel } from '../lib/types';

// Locations: the tree that scopes every other page — the business, groups on
// the template's named levels (an area; or region → franchisee, any depth),
// and locations — shown as a map beside a grouped directory. Each location
// reads its live state on its own clock. Owners and admins grow the tree and
// place locations here; everyone else uses it to focus. It reads the shell's
// tenant query, so the route needs no loader.
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
  const locations = () => nodes().filter((n) => n.kind === 'location');
  const canEdit = () => ctx.data.role.permissions.some((p) => p === 'tenant.manage' || p === 'roles.assign');
  const onPath = (id: string) => ctx.data.path.some((n) => n.id === id);
  /** What is being added: a location, or a group on `level`, under `parentId`. */
  const [adding, setAdding] = createSignal<null | { kind: 'region' | 'location'; parentId: string; level?: string }>(
    null,
    { name: 'addingNode' },
  );
  const [selectedId, setSelectedId] = createSignal<string | null>(null, { name: 'selectedSite' });
  /** The location whose pin the next map click drops. */
  const [placingId, setPlacingId] = createSignal<string | null>(null, { name: 'placingSite' });
  const [query, setQuery] = createSignal('', { name: 'siteQuery' });

  // Open/closed is read on each location's clock; re-read every minute.
  const [now, setNow] = createSignal(new Date(), { name: 'sitesNow' });
  onSettled(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  });
  const clocks = createMemo(
    () => new Map(locations().map((n) => [n.id, siteClock(n, template(), now())] as const)),
    { name: 'siteClocks' },
  );
  const clockOfSite = (id: string): SiteClock => clocks().get(id)!;

  const matches = (n: ScopeNode) => {
    const q = query().trim().toLowerCase();
    return !q || [n.name, n.code, n.address ?? ''].some((v) => v.toLowerCase().includes(q));
  };
  /** Whether a group holds a location matching the search, at any depth. */
  const groupMatches = (id: string): boolean =>
    childrenOf(id).some((n) => (n.kind === 'location' ? matches(n) : groupMatches(n.id)));

  const mapSites = (): Array<MapSite> =>
    locations()
      .filter((n) => n.pin && matches(n))
      .map((n) => ({ id: n.id, name: n.name, code: n.code, pin: n.pin!, state: clockOfSite(n.id).state }));
  const nameOf = (id: string | null) => nodes().find((n) => n.id === id)?.name ?? null;
  const select = (id: string) => {
    setSelectedId((current) => (current === id ? null : id));
    setPlacingId(null);
  };
  const pickOnMap = (id: string) => {
    setSelectedId(id);
    setPlacingId(null);
    document.getElementById(`site-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  };

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
  const place = (id: string, pin: [number, number] | null) => {
    const name = nameOf(id) ?? '';
    setPlacingId(null);
    update.mutate({
      nodeId: id,
      pin,
      label: pin ? tr('structure.toastPlaced', { name }) : tr('structure.toastUnplaced', { name }),
    });
  };

  const StateLine = (p: { id: string }) => {
    const c = () => clockOfSite(p.id);
    return (
      <span class={['site-state', `is-${c().state}`]}>
        <span class={['status', { 'status-paused': c().state !== 'open' }]} />
        {c().state === 'paused'
          ? tr('structure.paused')
          : c().state === 'open'
            ? tr('structure.openUntil', { time: clockOf(c().next) })
            : tr('structure.closedOpens', { time: clockOf(c().next) })}
      </span>
    );
  };

  /** A location in the directory: a summary row that opens into its details and actions. */
  const Site = (p: { node: ScopeNode }) => {
    const selected = () => selectedId() === p.node.id;
    const c = () => clockOfSite(p.node.id);
    const editable = () => canEdit() && !!p.node.reachable;
    return (
      <article
        id={`site-${p.node.id}`}
        class={['site', { selected: selected(), focused: onPath(p.node.id), locked: !p.node.reachable }]}
        data-status={p.node.status}
      >
        <button type="button" class="site-row" aria-expanded={selected() ? "true" : "false"} onClick={() => select(p.node.id)}>
          <span class="site-main">
            <span class="site-name">
              {p.node.name} <span class="site-code mono">{p.node.code}</span>
            </span>
            <span class="site-sub">
              <Show when={p.node.address} fallback={<span class="muted">{tr('structure.noAddress')}</span>}>
                {p.node.address}
              </Show>
              <Show when={!p.node.pin}>
                <span class="site-flag">{tr('structure.notPlaced')}</span>
              </Show>
            </span>
          </span>
          <span class="site-side">
            <StateLine id={p.node.id} />
            <span class="muted site-local">
              <Show when={p.node.reachable} fallback={<><Icon name="lock" size={12} /> {tr('structure.locked')}</>}>
                {tr('structure.localTime', { time: c().local })} · {zoneName(p.node.tz ?? 'UTC')}
              </Show>
            </span>
          </span>
          <Icon name="chevron" size={14} />
        </button>
        <Show when={selected()}>
          <div class="site-detail">
            <dl class="site-facts">
              <div>
                <dt>{tr('structure.address')}</dt>
                <dd>{p.node.address || <span class="muted">{tr('structure.noAddress')}</span>}</dd>
              </div>
              <div>
                <dt>{tr('structure.hoursLabel')}</dt>
                <dd>
                  {clockOf(c().hours[0], c().hours[1])}
                  <Show when={!p.node.hours}>
                    <span class="muted"> ({tr('structure.templateHours')})</span>
                  </Show>
                </dd>
              </div>
              <div>
                <dt>{tr('structure.timeZone')}</dt>
                <dd>{p.node.tz ?? 'UTC'}</dd>
              </div>
              <div>
                <dt>{tr('structure.position')}</dt>
                <dd class="mono">
                  {p.node.pin ? `${p.node.pin[0].toFixed(4)}, ${p.node.pin[1].toFixed(4)}` : <span class="muted">{tr('structure.notPlaced')}</span>}
                </dd>
              </div>
            </dl>
            <div class="site-actions">
              <Show when={p.node.reachable}>
                <Link to="." search={{ scope: p.node.id }} class="btn small">
                  {tr('structure.focusHere')}
                </Link>
              </Show>
              <Show when={editable()}>
                <Show
                  when={placingId() === p.node.id}
                  fallback={
                    <button type="button" class="btn small ghost" onClick={() => setPlacingId(p.node.id)}>
                      <Icon name="pin" size={14} /> {p.node.pin ? tr('structure.movePin') : tr('structure.placeOnMap')}
                    </button>
                  }
                >
                  <button type="button" class="btn small ghost" onClick={() => setPlacingId(null)}>
                    {tr('structure.cancel')}
                  </button>
                </Show>
                <Show when={p.node.pin}>
                  <ConfirmButton
                    class="small ghost"
                    label={tr('structure.removePin')}
                    confirm={tr('structure.removePinConfirm')}
                    onConfirm={() => place(p.node.id, null)}
                  />
                </Show>
              </Show>
            </div>
            <Show when={editable()}>
              <div class="site-actions">
                <Address
                  node={p.node}
                  onSave={(address) => update.mutate({ nodeId: p.node.id, address, label: tr('structure.toastAddress', { name: p.node.name }) })}
                />
                <Rename node={p.node} onSave={(name) => update.mutate({ nodeId: p.node.id, name, label: tr('structure.toastRenamed', { name }) })} />
                <Hours
                  node={p.node}
                  onSave={(tz, hours) => update.mutate({ nodeId: p.node.id, tz, hours, label: tr('structure.toastHoursSaved', { name: p.node.name }) })}
                />
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
              </div>
              <Show when={placingId() === p.node.id && p.node.pin}>
                <p class="muted hint">{tr('structure.dragHint')}</p>
              </Show>
            </Show>
          </div>
        </Show>
      </article>
    );
  };

  // Where a new group on `level` may go: the business or a group on a higher level, inside the viewer's reach.
  const parentsFor = (level: TreeLevel) =>
    [root(), ...groups()].filter((n) => n.reachable && childLevels(template(), n).some((l) => l.key === level.key));
  const placeName = (n: ScopeNode) => (n.kind === 'org' ? tr('structure.notInGroup') : tr('structure.inGroup', { name: n.name, level: levelOf(template(), n)!.label }));
  /** Locations under a node, at any depth. */
  const countUnder = (id: string): number =>
    childrenOf(id).reduce((sum, n) => sum + (n.kind === 'location' ? 1 : countUnder(n.id)), 0);

  /** A group: its header, its locations, then its own groups, nested as deep as the levels go. */
  const Group = (p: { node: ScopeNode }) => {
    const level = () => levelOf(template(), p.node)!;
    const below = () => childLevels(template(), p.node);
    const sites = () => childrenOf(p.node.id).filter((n) => n.kind === 'location' && matches(n));
    const subgroups = () => childrenOf(p.node.id).filter((n) => n.kind === 'region' && (!query() || groupMatches(n.id)));
    return (
      <section class={['site-group', { focused: onPath(p.node.id), locked: !p.node.reachable }]}>
        <header class="site-group-head">
          <span class="site-group-level">{level().label}</span>
          <Show when={p.node.reachable} fallback={<span class="site-group-name">{p.node.name}</span>}>
            <Link to="." search={{ scope: p.node.id }} class="site-group-name">
              {p.node.name}
            </Link>
          </Show>
          <span class="muted mono">{p.node.code}</span>
          <span class="site-group-count">{countUnder(p.node.id)}</span>
        </header>
        <For
          each={sites()}
          fallback={
            <Show when={!childrenOf(p.node.id).length}>
              <p class="muted hint site-empty">{tr('structure.emptyGroup', { level: level().label.toLowerCase() })}</p>
            </Show>
          }
        >
          {(loc) => <Site node={loc} />}
        </For>
        <Show when={subgroups().length}>
          <div class="site-groups nested">
            <For each={subgroups()}>{(g) => <Group node={g} />}</For>
          </div>
        </Show>
        <Show when={canEdit() && p.node.reachable && !query()}>
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

  const loose = () => childrenOf(root().id).filter((n) => n.kind === 'location' && matches(n));
  const topGroups = () => childrenOf(root().id).filter((n) => n.kind === 'region' && (!query() || groupMatches(n.id)));
  const counts = () => {
    const all = [...clocks().values()];
    return {
      open: all.filter((c) => c.state === 'open').length,
      paused: all.filter((c) => c.state === 'paused').length,
      placed: locations().filter((n) => n.pin).length,
    };
  };

  return (
    <div class="page wide">
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

      <div class="stats">
        <Stat
          label={t().locations}
          value={locations().length}
          foot={levels()
            .map((l) => {
              const n = groups().filter((g) => levelOf(template(), g)!.key === l.key).length;
              return `${n} ${(n === 1 ? l.label : l.plural).toLowerCase()}`;
            })
            .join(' · ')}
        />
        <Stat label={tr('structure.statOpen')} value={counts().open} foot={tr('structure.statOpenFoot')} />
        <Stat label={tr('structure.statPaused')} value={counts().paused} foot={tr('structure.statPausedFoot')} />
        <Stat
          label={tr('structure.statMapped')}
          value={`${counts().placed} / ${locations().length}`}
          foot={
            counts().placed === locations().length
              ? tr('structure.statMappedAll')
              : tr('structure.statMappedLeft', { count: locations().length - counts().placed })
          }
        />
      </div>

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

      <div class="sites">
        <Panel class="sites-map" title={tr('structure.mapTitle')} icon="pin">
          <SiteMap
            sites={mapSites()}
            selectedId={selectedId()}
            editable={canEdit() && !!nodes().find((n) => n.id === selectedId())?.reachable}
            placing={nameOf(placingId())}
            onSelect={pickOnMap}
            onPlace={(pin) => {
              const id = placingId() ?? selectedId();
              if (id) place(id, pin);
            }}
          />
          <Show when={!counts().placed}>
            <p class="muted hint sites-map-empty">{tr('structure.mapEmpty')}</p>
          </Show>
        </Panel>

        <Panel
          class="sites-list"
          title={root().name}
          icon="structure"
          aside={
            <label class="filter">
              <Icon name="search" size={14} />
              <input
                type="search"
                value={query()}
                onInput={(event) => setQuery(event.currentTarget.value)}
                placeholder={tr('structure.searchPlaceholder')}
                aria-label={tr('structure.searchPlaceholder')}
              />
            </label>
          }
        >
          <div class={['site-groups', { focused: ctx.data.scopeId === root().id }]}>
            <Show when={loose().length}>
              <section class="site-group loose">
                <Show when={topGroups().length}>
                  <header class="site-group-head">
                    <span class="site-group-level">{tr('structure.notInGroup')}</span>
                    <span class="site-group-count">{loose().length}</span>
                  </header>
                </Show>
                <For each={loose()}>{(loc) => <Site node={loc} />}</For>
              </section>
            </Show>
            <For each={topGroups()}>{(g) => <Group node={g} />}</For>
            <Show when={query() && !loose().length && !topGroups().length}>
              <p class="muted site-empty">{tr('structure.noMatch', { query: query() })}</p>
            </Show>
          </div>
        </Panel>
      </div>
    </div>
  );
}

/** Inline address edit: a small button that turns into a one-field form. */
function Address(props: { node: ScopeNode; onSave: (address: string) => void }) {
  const [editing, setEditing] = createSignal(false, { name: 'editingAddress' });
  return (
    <Show
      when={editing()}
      fallback={
        <button type="button" class="btn small ghost" onClick={() => setEditing(true)}>
          {tr('structure.address')}
        </button>
      }
    >
      <form
        class="inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          const address = String(new FormData(event.currentTarget).get('address')).trim();
          if (address !== (props.node.address ?? '')) props.onSave(address);
          setEditing(false);
        }}
      >
        <input
          type="text"
          name="address"
          value={props.node.address ?? ''}
          maxlength="200"
          placeholder={tr('structure.addressPlaceholder')}
          aria-label={tr('structure.address')}
        />
        <button type="submit" class="btn small">
          {tr('structure.save')}
        </button>
      </form>
    </Show>
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

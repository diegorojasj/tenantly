import { useMutation, useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import Downtimes from '../components/Downtimes';
import FieldInput from '../components/FieldInput';
import Icon from '../components/Icon';
import { PageHead, Panel } from '../components/ui';
import { readFields, showValue } from '../lib/fields';
import { fmtDay } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { resourceType } from '../lib/fulfilment';
import { createResource, setResourceStatus } from '../lib/ops';
import { downtimesQuery, prefetch, resourcesQuery, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { notify } from '../lib/toast';
import type { Resource, ScopeNode, Template } from '../lib/types';

// Resources — one job: define what delivers the work and see how busy it
// is. The template names the resource types (team members, rooms, units…);
// to the calendar they are all the same thing: rows that hold bookings.
// Utilization is booked time over open hours, last 7 days. Below them, the
// unavailability list: repairs, absences and closures that stop booking for a while.
export const Route = createFileRoute('/t/$org/resources')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, resourcesQuery(params.org, deps.scope));
    prefetch(context.queryClient, downtimesQuery(params.org, deps.scope));
  },
  head: () => ({ meta: [{ title: tr('resources.pageTitle') }] }),
  component: ResourcesPage,
});

function ResourcesPage() {
  const { org, scope } = useTenantScope();
  const search = Route.useSearch();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const data = useQuery(() => resourcesQuery(org(), scope()));
  const t = () => ctx.data.tenant.template;
  // View state, not navigation: same-route search navigations that swap a
  // query key never settled their transition on the current router RC.
  const types = () => t().resourceTypes;
  const [tab, setTab] = createSignal<string>(
    () => (search().tab === 'assets' ? (types().find((r) => !r.people) ?? types()[0])?.key : types()[0]?.key) ?? 'staff',
    { name: 'resourcesTab' },
  );
  const kind = () => resourceType(t(), tab());
  const nameOf = (id: string | null) => data.data.resources.find((r) => r.resource.id === id)?.resource.name;
  const [adding, setAdding] = createSignal(false, { name: 'resourceAdding' });

  const rows = createMemo(() => data.data.resources.filter((r) => r.resource.type === tab()));
  const avg = createMemo(() => Math.round(rows().reduce((s, r) => s + r.utilization, 0) / Math.max(rows().length, 1)));
  const status = useMutation(() => ({
    mutationFn: (input: { resourceId: string; status: Resource['status'] }) => setResourceStatus({ org: org(), ...input }),
    onSuccess: (_r, input) => {
      const r = data.data.resources.find((x) => x.resource.id === input.resourceId)?.resource;
      notify(input.status === 'available' ? tr('resources.toastBack', { name: r?.name ?? '' }) : tr('resources.toastOut', { name: r?.name ?? '' }));
    },
  }));
  const multiSite = () => data.data.locations.length > 1;

  return (
    <div class="page">
      <PageHead
        eyebrow={ctx.data.path.at(-1)!.name}
        title={tr('resources.title')}
        lede={tr('resources.lede')}
      >
        <div class="segmented" role="tablist">
          <For each={types()}>
            {(r) => (
              <button type="button" role="tab" aria-selected={tab() === r.key ? 'true' : 'false'} onClick={() => setTab(r.key)}>
                {r.plural}
              </button>
            )}
          </For>
        </div>
        <Show when={data.data.canEdit}>
          <button type="button" class="btn" onClick={() => setAdding(true)}>
            <Icon name="plus" size={16} /> {tr('resources.addThing', { what: kind().label.toLowerCase() })}
          </button>
        </Show>
      </PageHead>

      <Panel
        title={`${rows().length} ${kind().plural.toLowerCase()}`}
        icon={kind().people ? 'users' : 'integrations'}
        aside={<span class="muted">{tr('resources.avgUtilization', { pct: avg() })}</span>}
      >
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{tr('resources.name')}</th>
                <th>{kind().roleLabel ?? tr('resources.typeFallback')}</th>
                <th>{tr('resources.details')}</th>
                <Show when={multiSite()}>
                  <th>{t().terms.location}</th>
                </Show>
                <th>{tr('resources.utilization')}</th>
                <th>{tr('resources.nextBooked')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <For each={rows()} fallback={<tr><td colspan="7" class="muted empty">{tr('resources.empty')}</td></tr>}>
                {(r) => (
                  <tr class={{ dim: r.resource.status === 'out_of_service' }}>
                    <td>
                      <strong>{r.resource.name}</strong>
                      <Show when={r.resource.status === 'out_of_service'}>
                        <span class="pill warn">{tr('resources.outOfService')}</span>
                      </Show>
                      <Show when={r.downtime}>
                        {(reason) => <span class="pill bad">{tr(`downtime.reason_${reason()}`)}</span>}
                      </Show>
                    </td>
                    <td class="muted">{r.resource.role}</td>
                    <td class="muted">
                      {[
                        ...(kind().attributes ?? [])
                          .filter((a) => r.resource.attributes[a.key] !== undefined)
                          .map((a) => `${a.label}: ${showValue(r.resource.attributes[a.key])}`),
                        ...(r.resource.parentId ? [tr('resources.inside', { name: nameOf(r.resource.parentId) ?? '—' })] : []),
                      ].join(' · ') || '—'}
                    </td>
                    <Show when={multiSite()}>
                      <td class="muted">{r.locationName}</td>
                    </Show>
                    <td>
                      <span class="util">
                        <span class={['util-bar', { low: r.utilization < 25, high: r.utilization > 85 }]} style={{ '--w': `${r.utilization}%` }} />
                        <span class="mono">{r.utilization}%</span>
                      </span>
                    </td>
                    <td class="muted mono">{r.next ? `${fmtDay(r.next.slice(0, 10)).split(',')[0].slice(0, 3)} ${r.next.slice(11)}` : '—'}</td>
                    <td class="row-actions">
                      <Show when={data.data.canEdit && !kind().people}>
                        <Show
                          when={r.resource.status === 'available'}
                          fallback={
                            <button
                              type="button"
                              class="btn small ghost"
                              disabled={status.isPending && status.variables?.resourceId === r.resource.id}
                              onClick={() => status.mutate({ resourceId: r.resource.id, status: 'available' })}
                            >
                              {tr('resources.backInService')}
                            </button>
                          }
                        >
                          <ConfirmButton
                            class="small ghost"
                            label={tr('resources.takeOut')}
                            confirm={tr('resources.takeOutConfirm')}
                            disabled={status.isPending && status.variables?.resourceId === r.resource.id}
                            onConfirm={() => status.mutate({ resourceId: r.resource.id, status: 'out_of_service' })}
                          />
                        </Show>
                      </Show>
                    </td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
        <Show when={status.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      </Panel>

      <Downtimes org={org()} scope={scope()} template={t()} sites={data.data.locations} />

      <Show when={adding()}>
        <AddResource
          org={org()}
          template={t()}
          type={tab()}
          sites={data.data.locations}
          resources={data.data.resources.map((r) => r.resource)}
          onClose={() => setAdding(false)}
        />
      </Show>
    </div>
  );
}

function AddResource(props: {
  org: string;
  template: Template;
  type: Resource['type'];
  sites: Array<ScopeNode>;
  resources: Array<Resource>;
  onClose: () => void;
}) {
  const add = useMutation(() => ({
    mutationFn: (input: Parameters<typeof createResource>[0]) => createResource(input),
    onSuccess: (_r, input) => {
      notify(tr('resources.toastAdded', { name: input.name.trim() }));
      props.onClose();
    },
  }));
  const kind = () => resourceType(props.template, props.type);
  const noun = () => kind().label.toLowerCase();
  const [site, setSite] = createSignal(() => props.sites[0]?.id ?? '', { name: 'resourceSite' });
  const roles = () => [...new Set(props.resources.filter((r) => r.type === props.type).map((r) => r.role))];
  const parents = () => props.resources.filter((r) => r.locationId === site());
  return (
    <aside class="drawer" aria-label={tr('resources.addThing', { what: noun() })}>
      <header class="drawer-head">
        <h2>{tr('resources.addThing', { what: noun() })}</h2>
        <button type="button" class="icon-btn" aria-label={tr('resources.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          const attributes = readFields(kind().attributes ?? [], d, 'attr-');
          add.mutate({
            org: props.org,
            locationId: site(),
            type: props.type,
            name: String(d.get('name')),
            role: String(d.get('role')),
            attributes,
            parentId: String(d.get('parent') ?? '') || undefined,
          });
        }}
      >
        <label>
          <span class="form-label">{props.template.terms.location}</span>
          <select value={site()} onChange={(event) => setSite(event.currentTarget.value)}>
            <For each={props.sites}>{(s) => <option value={s.id}>{s.name}</option>}</For>
          </select>
        </label>
        <label>
          <span class="form-label">{tr('resources.name')}</span>
          <input type="text" name="name" required minlength="2" />
        </label>
        <label>
          <span class="form-label">{kind().roleLabel ?? tr('resources.typeFallback')}</span>
          <input type="text" name="role" list="resource-roles" required placeholder={kind().people ? tr('resources.rolePlaceholderPeople') : tr('resources.rolePlaceholderThings')} />
          <datalist id="resource-roles">
            <For each={roles()}>{(a) => <option value={a} />}</For>
          </datalist>
          <span class="muted hint">{tr('resources.roleHint', { noun: noun(), role: (kind().roleLabel ?? tr('resources.typeFallback')).toLowerCase() })}</span>
        </label>
        <For each={kind().attributes ?? []}>{(a) => <FieldInput def={a} prefix="attr-" />}</For>
        <Show when={parents().length}>
          <label>
            <span class="form-label">{tr('resources.insideLabel')}</span>
            <select name="parent">
              <option value="">{tr('resources.nothingOption')}</option>
              <For each={parents()}>{(r) => <option value={r.id}>{r.name}</option>}</For>
            </select>
            <span class="muted hint">{tr('resources.insideHint')}</span>
          </label>
        </Show>
        <Show when={add.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={add.isPending}>
          {tr('resources.addThing', { what: noun() })}
        </button>
      </form>
    </aside>
  );
}

import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { createSignal, For, Show } from 'solid-js';

import BookingPanel from '../components/BookingPanel';
import Icon from '../components/Icon';
import NewBooking from '../components/NewBooking';
import { Panel, PageHead, Stat, StatusPill } from '../components/ui';
import { fmtDay, fmtMoney, fmtUntil, wallNow } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { actionVerb, movedMessage } from '../lib/lifecycle';
import { notify } from '../lib/toast';
import { setBookingStatus } from '../lib/ops';
import { prefetch, tenantQuery, todayQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import type { Alert, Booking, BookingStatus, Template, Today } from '../lib/types';

// Today — the front desk. One job: run the day. Who's arriving, what's in
// progress, and what needs a human before it becomes a problem.
export const Route = createFileRoute('/t/$org/')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, todayQuery(params.org, deps.scope));
  },
  component: TodayPage,
});

const alertRoute: Record<Alert['to'], string> = {
  bookings: '/t/$org/bookings',
  customers: '/t/$org/customers',
  payments: '/t/$org/payments',
  calendar: '/t/$org/calendar',
  resources: '/t/$org/resources',
};

function TodayPage() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const today = useQuery(() => todayQuery(org(), scope()));
  const t = () => ctx.data.tenant.template;
  const k = () => today.data.kpis;
  const canManage = () => ctx.data.role.permissions.includes('bookings.manage');
  const search = () => (scope() ? { scope: scope() } : {});
  const sites = () => ctx.data.nodes.filter((n) => n.kind === 'location' && n.reachable);
  const focusSite = () => (ctx.data.path.at(-1)!.kind === 'location' ? ctx.data.scopeId : '');

  const [openId, setOpenId] = createSignal<string | null>(null, { name: 'todayOpen' });
  const [booking, setBooking] = createSignal(false, { name: 'todayNewBooking' });
  const open = () => [...today.data.arrivals, ...today.data.inProgress].find((b) => b.id === openId());

  const move = useMutation(() => ({
    mutationFn: (input: { bookingId: string; status: BookingStatus }) => setBookingStatus({ org: org(), ...input }),
    onSuccess: (_r, input) => {
      const b = [...today.data.arrivals, ...today.data.inProgress].find((x) => x.id === input.bookingId);
      notify(movedMessage(b ? (b.customerId ? b.customerName : b.offeringName) : t().terms.booking, t().status, input.status));
    },
  }));
  const busy = (id: string) => move.isPending && move.variables?.bookingId === id;

  const Row = (p: { b: Booking; action: BookingStatus; late?: boolean }) => (
    <li class={['desk-row', { late: p.late }]}>
      <button type="button" class="desk-main" onClick={() => setOpenId(p.b.id)}>
        <span class="desk-time mono">{p.action === 'completed' ? tr('today.until', { time: fmtUntil(p.b.start, p.b.end) }) : p.b.start.slice(11)}</span>
        <span class="desk-who">
          <strong>{p.b.customerId ? p.b.customerName : p.b.offeringName}</strong>
          <span class="muted block">
            {p.b.customerId
              ? `${p.b.offeringName} · ${p.b.resourceNames.join(' · ')}`
              : `${tr('today.seatsBooked', { taken: p.b.attendees.length, capacity: p.b.capacity })} · ${p.b.resourceNames.join(' · ')}`}
            {ctx.data.path.at(-1)!.kind !== 'location' ? ` · ${p.b.locationName}` : ''}
          </span>
        </span>
        <StatusPill status={p.b.status} labels={t().status} />
      </button>
      <Show when={canManage() && (p.b.status !== 'requested' || p.action === 'confirmed')}>
        <button type="button" class="btn small" disabled={busy(p.b.id)} onClick={() => move.mutate({ bookingId: p.b.id, status: p.action })}>
          {actionVerb(p.action)}
        </button>
      </Show>
    </li>
  );

  return (
    <div class="page">
      <PageHead
        eyebrow={`${fmtDay(today.data.day)} · ${ctx.data.path.at(-1)!.name}`}
        title={tr('today.title')}
        lede={tr('today.lede', {
          expected: k().expected,
          customers: t().terms.customers.toLowerCase(),
          count: k().bookings,
          bookings: t().terms.bookings.toLowerCase(),
          checkedIn: k().checkedIn,
          checkedInLabel: t().status.checked_in.toLowerCase(),
          completedLabel: t().status.completed.toLowerCase(),
        })}
      >
        <Show when={canManage()}>
          <button type="button" class="btn" onClick={() => setBooking(true)}>
            <Icon name="plus" size={16} /> {tr('today.newBooking', { booking: t().terms.booking.toLowerCase() })}
          </button>
        </Show>
      </PageHead>

      <Show when={!today.data.setup.done && ctx.data.role.permissions.some((p) => p === 'pricing.write' || p === 'config.write')}>
        <SetupChecklist org={org()} search={search()} steps={today.data.setup.steps} terms={t().terms} />
      </Show>

      <div class="stats">
        <Stat label={tr('today.statBookings', { bookings: t().terms.bookings })} value={k().bookings} foot={`${k().expected} ${t().terms.customers.toLowerCase()}`} />
        <Stat
          label={t().status.checked_in}
          value={`${k().checkedIn}/${k().expected}`}
          foot={tr('today.statArrived', { pct: Math.round((k().checkedIn / Math.max(k().expected, 1)) * 100) })}
        />
        <Stat label={tr('today.statRevenue')} value={fmtMoney(k().revenue, ctx.data.tenant.currency)} foot={tr('today.statRevenueFoot')} />
        <Stat
          label={tr('today.statUtilization', { staff: t().terms.staff })}
          value={`${k().utilization}%`}
          foot={<span class={{ warn: k().utilization < 40 }}>{tr('today.statUtilizationFoot')}</span>}
        />
      </div>

      <div class="grid two">
        <Panel title={tr('today.arrivingTitle')} icon="clock" aside={<span class="muted">{today.data.arrivals.length}</span>}>
          <ul class="desk">
            <For each={today.data.arrivals} fallback={<li class="muted empty">{tr('today.arrivingEmpty')}</li>}>
              {(b) => <Row b={b} action={b.status === 'requested' ? 'confirmed' : 'checked_in'} />}
            </For>
          </ul>
        </Panel>

        <div class="stack">
          <Panel title={tr('today.alertsTitle')} icon="alert" aside={<span class="muted">{today.data.alerts.length}</span>}>
            <ul class="alerts">
              <For each={today.data.alerts} fallback={<li class="muted empty">{tr('today.alertsEmpty')}</li>}>
                {(a) => (
                  <li>
                    <Link to={alertRoute[a.to] as '/t/$org'} params={{ org: org() }} search={search()} class="alert" data-tone={a.tone}>
                      <span class="alert-dot" />
                      <span>
                        <strong>{a.title}</strong>
                        <span class="muted block">{a.detail}</span>
                      </span>
                      <Icon name="chevron" size={15} />
                    </Link>
                  </li>
                )}
              </For>
            </ul>
          </Panel>

          <Panel title={tr('today.inProgressTitle')} icon="pipeline" aside={<span class="muted">{today.data.inProgress.length}</span>}>
            <ul class="desk">
              <For each={today.data.inProgress} fallback={<li class="muted empty">{tr('today.inProgressEmpty')}</li>}>
                {(b) => <Row b={b} action="completed" late={b.end < wallNow(b.tz)} />}
              </For>
            </ul>
          </Panel>
        </div>
      </div>
      <Show when={move.error}>{(error) => <p role="alert" class="error banner">{error()?.message}</p>}</Show>

      <Show when={open()}>
        {(b) => <BookingPanel org={org()} booking={b()} template={t()} canManage={canManage()} onClose={() => setOpenId(null)} />}
      </Show>
      <Show when={booking()}>
        <NewBooking org={org()} template={t()} sites={sites()} siteId={focusSite()} day={today.data.day} onClose={() => setBooking(false)} />
      </Show>
    </div>
  );
}

/** First run (docs/USAGE.md §6): what a new business still needs before its first booking. */
function SetupChecklist(props: {
  org: string;
  search: { scope?: string };
  steps: Today['setup']['steps'];
  terms: Template['terms'];
}) {
  const items = () => [
    { done: props.steps.catalog, to: '/t/$org/catalog', title: tr('today.setupCatalogTitle'), detail: tr('today.setupCatalogDetail') },
    { done: props.steps.team, to: '/t/$org/resources', title: tr('today.setupTeamTitle', { staff: props.terms.staffPlural.toLowerCase() }), detail: tr('today.setupTeamDetail', { assets: props.terms.assets.toLowerCase() }) },
    { done: props.steps.customers, to: '/t/$org/customers', title: tr('today.setupCustomersTitle', { customer: props.terms.customer.toLowerCase() }), detail: tr('today.setupCustomersDetail') },
    { done: props.steps.policies, to: '/t/$org/config', title: tr('today.setupPoliciesTitle'), detail: tr('today.setupPoliciesDetail') },
    { done: props.steps.bookings, to: '/t/$org/calendar', title: tr('today.setupBookingsTitle', { booking: props.terms.booking.toLowerCase() }), detail: tr('today.setupBookingsDetail') },
  ];
  const done = () => items().filter((i) => i.done).length;
  return (
    <section class="setup" aria-label={tr('today.setupTitle')}>
      <header>
        <strong>{tr('today.setupTitle')}</strong>
        <span class="muted">
          {tr('today.setupProgress', { done: done(), total: items().length })}
        </span>
        <span class="setup-bar" style={{ '--w': `${(done() / items().length) * 100}%` }} />
      </header>
      <ol>
        <For each={items()}>
          {(item) => (
            <li class={{ done: item.done }}>
              <span class="setup-tick">
                <Show when={item.done} fallback={<span class="dot" />}>
                  <Icon name="check" size={14} />
                </Show>
              </span>
              <Link to={item.to as '/t/$org'} params={{ org: props.org }} search={props.search}>
                <strong>{item.title}</strong>
                <span class="muted block">{item.detail}</span>
              </Link>
            </li>
          )}
        </For>
      </ol>
    </section>
  );
}

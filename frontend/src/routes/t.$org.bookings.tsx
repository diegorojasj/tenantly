import { useMutation, useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Show } from 'solid-js';

import BookingPanel from '../components/BookingPanel';
import Icon from '../components/Icon';
import NewBooking from '../components/NewBooking';
import { KindBadge, Lifecycle, PageHead, Panel, StatusPill } from '../components/ui';
import { fmtDay, fmtMoney, fmtUntil } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { actionVerb, movedMessage, nextStatuses } from '../lib/lifecycle';
import { notify } from '../lib/toast';
import { setBookingStatus } from '../lib/ops';
import { bookingsQuery, prefetch, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import type { BookingRange, BookingStatus, OfferingKind } from '../lib/types';

// Bookings — one job: handle every reservation through its lifecycle,
// including the ones that aren't today (requests to confirm, no-shows to
// mark, cancellations to process).
const ranges = (): Array<[BookingRange, string]> => [
  ['today', tr('bookings.rangeToday')],
  ['upcoming', tr('bookings.rangeUpcoming')],
  ['past', tr('bookings.rangePast')],
];

export const Route = createFileRoute('/t/$org/bookings')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '', range: (search.range ?? 'today') as BookingRange }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, bookingsQuery(params.org, deps.scope, deps.range));
  },
  head: () => ({ meta: [{ title: `${tr('bookings.title')} · Tenantly` }] }),
  component: BookingsPage,
});

const statuses: Array<BookingStatus> = ['requested', 'confirmed', 'checked_in', 'completed', 'no_show', 'cancelled'];
const LIMIT = 250;

function BookingsPage() {
  const { org, scope } = useTenantScope();
  const search = Route.useSearch();
  // Local state, not a navigation: the range is a view filter. (A search-
  // param navigation here swapped the query under a router transition that,
  // on the current router RC, never settled — holding every later write.)
  const [range, setRange] = createSignal<BookingRange>(() => search().range ?? 'today', { name: 'bookingRange' });
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const list = useQuery(() => bookingsQuery(org(), scope(), range()));
  const t = () => ctx.data.tenant.template;

  const [status, setStatus] = createSignal<BookingStatus | 'all'>('all', { name: 'bookingStatus' });
  const [kind, setKind] = createSignal<OfferingKind | 'all'>('all', { name: 'bookingKind' });
  const [text, setText] = createSignal('', { name: 'bookingText' });
  const [openId, setOpenId] = createSignal<string | null>(null, { name: 'bookingsOpen' });
  const [booking, setBooking] = createSignal(false, { name: 'bookingsNew' });

  const counts = createMemo(() => {
    const map = new Map<BookingStatus, number>();
    for (const b of list.data.bookings) map.set(b.status, (map.get(b.status) ?? 0) + 1);
    return map;
  });
  const rows = createMemo(() => {
    const q = text().trim().toLowerCase();
    return list.data.bookings.filter(
      (b) =>
        (status() === 'all' || b.status === status()) &&
        (kind() === 'all' || b.kind === kind()) &&
        (!q || `${b.customerName} ${b.offeringName} ${b.resourceNames.join(' ')} ${b.attendees.map((a) => a.name).join(' ')}`.toLowerCase().includes(q)),
    );
  });
  const open = () => list.data.bookings.find((b) => b.id === openId());

  const move = useMutation(() => ({
    mutationFn: (input: { bookingId: string; status: BookingStatus }) => setBookingStatus({ org: org(), ...input }),
    onSuccess: (_r, input) => {
      const b = list.data.bookings.find((x) => x.id === input.bookingId);
      notify(movedMessage(b ? (b.customerId ? b.customerName : b.offeringName) : t().terms.booking, t().status, input.status));
    },
  }));
  const busy = (id: string) => move.isPending && move.variables?.bookingId === id;
  const kinds = () => t().presets.filter((p) => p.time !== 'none');

  return (
    <div class="page">
      <PageHead
        eyebrow={`${ctx.data.path.at(-1)!.name} · ${list.data.from === list.data.to ? fmtDay(list.data.from) : `${list.data.from} → ${list.data.to}`}`}
        title={t().terms.bookings}
        lede={tr('bookings.lede')}
      >
        <div class="segmented" role="tablist">
          <For each={ranges()}>
            {([value, label]) => (
              <button type="button" role="tab" aria-selected={range() === value ? 'true' : 'false'} onClick={() => setRange(value)}>
                {label}
              </button>
            )}
          </For>
        </div>
        <Show when={list.data.canManage}>
          <button type="button" class="btn" onClick={() => setBooking(true)}>
            <Icon name="plus" size={16} /> {tr('bookings.newBooking', { booking: t().terms.booking.toLowerCase() })}
          </button>
        </Show>
      </PageHead>

      <Lifecycle labels={t().status} />

      <Panel>
        <div class="toolbar">
          <div class="chips" role="group" aria-label={tr('bookings.status')}>
            <button type="button" class={['chip-toggle', { on: status() === 'all' }]} onClick={() => setStatus('all')}>
              {tr('bookings.all')} <span class="mono muted">{list.data.bookings.length}</span>
            </button>
            <For each={statuses.filter((s) => counts().has(s))}>
              {(s) => (
                <button type="button" class={['chip-toggle', { on: status() === s }]} onClick={() => setStatus(s)}>
                  {t().status[s]} <span class="mono muted">{counts().get(s)}</span>
                </button>
              )}
            </For>
          </div>
          <Show when={kinds().length > 1}>
            <select aria-label={tr('bookings.kind')} value={kind()} onChange={(event) => setKind(event.currentTarget.value as OfferingKind | 'all')}>
              <option value="all">{tr('bookings.allKinds')}</option>
              <For each={kinds()}>{(p) => <option value={p.key}>{p.plural}</option>}</For>
            </select>
          </Show>
          <label class="filter">
            <Icon name="search" size={15} />
            <input type="search" placeholder={tr('bookings.searchPlaceholder')} value={text()} onInput={(event) => setText(event.currentTarget.value)} />
          </label>
        </div>

        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{tr('bookings.colWhen')}</th>
                <th>{tr('bookings.colWho')}</th>
                <th>{tr('bookings.colWhat')}</th>
                <th>{tr('bookings.colAssigned')}</th>
                <th>{tr('bookings.colStatus')}</th>
                <th class="num">{tr('bookings.colPrice')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <For each={rows().slice(0, LIMIT)} fallback={<tr><td colspan="7" class="muted empty">{tr('bookings.noMatch')}</td></tr>}>
                {(b) => (
                  <tr class={['clickable', { dim: b.status === 'cancelled' }]} onClick={() => setOpenId(b.id)}>
                    <td class="mono nowrap">
                      <Show when={range() !== 'today'}>{fmtDay(b.start.slice(0, 10)).split(',')[0].slice(0, 3)} </Show>
                      {b.start.slice(11)}–{fmtUntil(b.start, b.end)}
                    </td>
                    <td>
                      <strong>{b.customerId ? b.customerName : tr('bookings.seatsBooked', { taken: b.attendees.length, capacity: b.capacity })}</strong>
                      <Show when={b.subjectName}>
                        <span class="muted"> · {b.subjectName}</span>
                      </Show>
                      <Show when={ctx.data.path.at(-1)!.kind !== 'location'}>
                        <span class="muted block">{b.locationName}</span>
                      </Show>
                    </td>
                    <td>
                      <KindBadge kind={b.kind} /> {b.offeringName}
                    </td>
                    <td class="muted">{b.resourceNames.join(' · ')}</td>
                    <td>
                      <StatusPill status={b.status} labels={t().status} />
                      <Show when={b.downtime}>
                        {(d) => (
                          <span class="pill bad" title={tr('downtime.flagged', { what: d().what, reason: tr(`downtime.reason_${d().reason}`).toLowerCase() })}>
                            {tr('downtime.flaggedShort')}
                          </span>
                        )}
                      </Show>
                    </td>
                    <td class="num mono">
                      {fmtMoney(b.price, b.currency)}
                      <Show when={b.customerId && b.status === 'completed' && !b.paid}>
                        <span class="pill warn">{tr('bookings.unpaid')}</span>
                      </Show>
                    </td>
                    <td class="row-actions" onClick={(event) => event.stopPropagation()}>
                      <Show when={list.data.canManage}>
                        <For each={nextStatuses(t(), b.status).filter((s) => s !== 'cancelled' && s !== 'no_show')}>
                          {(next) => (
                            <button type="button" class="btn small" disabled={busy(b.id)} onClick={() => move.mutate({ bookingId: b.id, status: next })}>
                              {actionVerb(next)}
                            </button>
                          )}
                        </For>
                      </Show>
                    </td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
        <Show when={rows().length > LIMIT}>
          <p class="muted empty">{tr('bookings.truncated', { limit: LIMIT, total: rows().length })}</p>
        </Show>
      </Panel>
      <Show when={move.error}>{(error) => <p role="alert" class="error banner">{error()?.message}</p>}</Show>

      <Show when={open()}>
        {(b) => <BookingPanel org={org()} booking={b()} template={t()} canManage={list.data.canManage} onClose={() => setOpenId(null)} />}
      </Show>
      <Show when={booking()}>
        <NewBooking
          org={org()}
          template={t()}
          sites={ctx.data.nodes.filter((n) => n.kind === 'location' && n.reachable && (n.id === ctx.data.scopeId || n.parentId === ctx.data.scopeId || ctx.data.path.at(-1)!.kind === 'org'))}
          siteId={ctx.data.path.at(-1)!.kind === 'location' ? ctx.data.scopeId : ''}
          day={list.data.from}
          onClose={() => setBooking(false)}
        />
      </Show>
    </div>
  );
}

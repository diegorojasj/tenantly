import { useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { createSignal, For, onSettled, Show } from 'solid-js';

import BookingPanel from '../components/BookingPanel';
import Icon from '../components/Icon';
import NewBooking from '../components/NewBooking';
import { PageHead, Panel } from '../components/ui';
import { fmtDay, fmtUntil, shiftDay, wallNow, zoneName } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { calendarQuery, prefetch, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import type { Booking, Resource } from '../lib/types';

// Calendar — one job: plan and change time-based capacity. Rows are the
// resources that deliver the work (team and assets), columns are the day.
// The same timeline shows class fill, rental windows and visit routes.
export const Route = createFileRoute('/t/$org/calendar')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '', day: search.day ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, calendarQuery(params.org, deps.scope, deps.day));
  },
  head: () => ({ meta: [{ title: `${tr('calendar.title')} · Tenantly` }] }),
  component: CalendarPage,
});

function CalendarPage() {
  const { org, scope } = useTenantScope();
  const search = Route.useSearch();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  // View state, not navigation: same-route search navigations that swap a
  // query key never settled their transition on the current router RC.
  const [day, setDay] = createSignal(() => search().day ?? '', { name: 'calendarDay' });
  const cal = useQuery(() => calendarQuery(org(), scope(), day()));
  const t = () => ctx.data.tenant.template;
  const canManage = () => ctx.data.role.permissions.includes('bookings.manage');

  const [openId, setOpenId] = createSignal<string | null>(null, { name: 'calendarOpen' });
  const [booking, setBooking] = createSignal(false, { name: 'calendarNewBooking' });
  const open = () => cal.data.board?.bookings.find((b) => b.id === openId());

  const span = () => cal.data.close - cal.data.open;
  // Bookings that began on an earlier day or end on a later one run off the edge of today's track.
  const pos = (at: string) => {
    const date = at.slice(0, 10);
    if (date !== cal.data.date) return date < cal.data.date ? 0 : 100;
    const minute = Number(at.slice(11, 13)) * 60 + Number(at.slice(14, 16));
    return (Math.min(Math.max(minute - cal.data.open, 0), span()) / span()) * 100;
  };
  const hours = () => Array.from({ length: Math.floor(span() / 60) + 1 }, (_, i) => cal.data.open / 60 + i);

  const Track = (p: { resource: Resource }) => (
    <div class={['tl-row', { down: p.resource.status === 'out_of_service' }]}>
      <div class="tl-label">
        <strong>{p.resource.name}</strong>
        <span class="muted">{p.resource.status === 'out_of_service' ? tr('calendar.outOfService') : p.resource.role}</span>
      </div>
      <div class="tl-track">
        {/* Its own downtime, or the whole location's; offering downtimes flag their bookings instead. */}
        <For each={cal.data.board!.downtimes.filter((d) => d.resourceId === p.resource.id || (!d.resourceId && !d.offeringId))}>
          {(d) => (
            <span
              class="tl-down"
              style={{ left: `${pos(d.start)}%`, width: `${pos(d.end) - pos(d.start)}%` }}
              title={`${tr(`downtime.reason_${d.reason}`)}${d.note ? ` · ${d.note}` : ''}`}
            />
          )}
        </For>
        <For each={cal.data.board!.bookings.filter((b) => b.resourceIds.includes(p.resource.id))}>
          {(b) => <Bar b={b} />}
        </For>
      </div>
    </div>
  );

  const Bar = (p: { b: Booking }) => (
    <button
      type="button"
      class={['tl-bar', `s-${p.b.status}`, { picked: openId() === p.b.id, group: !p.b.customerId, clash: !!p.b.downtime }]}
      style={{ left: `${pos(p.b.start)}%`, width: `${pos(p.b.end) - pos(p.b.start)}%` }}
      title={`${p.b.start.slice(11)}–${fmtUntil(p.b.start, p.b.end)} · ${p.b.offeringName} · ${t().status[p.b.status]}`}
      onClick={() => setOpenId(p.b.id)}
    >
      <Show when={!p.b.customerId} fallback={<strong>{p.b.customerName}</strong>}>
        <strong>{p.b.offeringName}</strong>
        <span class="tl-fill" style={{ '--fill': `${(p.b.attendees.length / p.b.capacity) * 100}%` }}>
          {p.b.attendees.length}/{p.b.capacity}
        </span>
      </Show>
      <span class="tl-sub">{p.b.customerId ? p.b.offeringName : ''}</span>
    </button>
  );

  return (
    <div class="page wide">
      <PageHead
        eyebrow={ctx.data.path.at(-1)!.name}
        title={fmtDay(cal.data.date)}
        lede={
          cal.data.board
            ? cal.data.tz === 'UTC'
              ? tr('calendar.lede', { count: cal.data.board.resources.length, n: cal.data.board.bookings.length, bookings: t().terms.bookings.toLowerCase() })
              : tr('calendar.ledeZone', { count: cal.data.board.resources.length, n: cal.data.board.bookings.length, bookings: t().terms.bookings.toLowerCase(), zone: zoneName(cal.data.tz) })
            : tr('calendar.pickLocation', { location: t().terms.location.toLowerCase() })
        }
      >
        <div class="day-nav">
          <button type="button" class="icon-btn" aria-label={tr('calendar.previousDay')} onClick={() => setDay(shiftDay(cal.data.date, -1))}>
            <Icon name="arrowLeft" />
          </button>
          <button type="button" class="btn ghost" onClick={() => setDay(cal.data.today)}>
            {tr('calendar.today')}
          </button>
          <button type="button" class="icon-btn" aria-label={tr('calendar.nextDay')} onClick={() => setDay(shiftDay(cal.data.date, 1))}>
            <Icon name="chevron" />
          </button>
        </div>
        <Show when={cal.data.board && canManage()}>
          <button type="button" class="btn" onClick={() => setBooking(true)}>
            <Icon name="plus" size={16} /> {tr('calendar.newBooking', { booking: t().terms.booking.toLowerCase() })}
          </button>
        </Show>
      </PageHead>

      <Show
        when={cal.data.board}
        fallback={
          <div class="site-grid">
            <For each={cal.data.sites}>
              {(site) => (
                <Link to="." search={{ scope: site.node.id, ...(day() ? { day: day() } : {}) }} class="site-card">
                  <span class="site-head">
                    <span class={['status', `status-${site.node.status}`]} />
                    <strong>{site.node.name}</strong>
                    <span class="mono muted">{site.node.code}</span>
                  </span>
                  <span class="site-num">{site.bookings}</span>
                  <span class="muted">
                    {tr('calendar.siteStats', { bookings: t().terms.bookings.toLowerCase(), pct: site.utilization, staff: t().terms.staff.toLowerCase() })}
                  </span>
                </Link>
              )}
            </For>
          </div>
        }
      >
        {(board) => (
          <Panel class="timeline-panel">
            <div class="timeline" style={{ '--hours': String(span() / 60) }}>
              <div class="tl-row tl-head">
                <div class="tl-label" />
                <div class="tl-track">
                  <For each={hours()}>
                    {(h) => (
                      <span class="tl-hour mono" style={{ left: `${((h * 60 - cal.data.open) / span()) * 100}%` }}>
                        {String(h).padStart(2, '0')}
                      </span>
                    )}
                  </For>
                </div>
              </div>
              {/* One group per resource type the template defines; the first (the team) always shows. */}
              <For each={t().resourceTypes}>
                {(type, i) => (
                  <Show when={i() === 0 || board().resources.some((r) => r.type === type.key)}>
                    <p class="tl-group">{type.plural}</p>
                    <For each={board().resources.filter((r) => r.type === type.key)}>{(r) => <Track resource={r} />}</For>
                  </Show>
                )}
              </For>
              <Show when={cal.data.date === cal.data.today}>
                <NowMarker open={cal.data.open} close={cal.data.close} tz={cal.data.tz} />
              </Show>
            </div>
          </Panel>
        )}
      </Show>

      <Show when={open()}>
        {(b) => <BookingPanel org={org()} booking={b()} template={t()} canManage={canManage()} onClose={() => setOpenId(null)} />}
      </Show>
      <Show when={booking()}>
        <NewBooking
          org={org()}
          template={t()}
          sites={ctx.data.nodes.filter((n) => n.id === ctx.data.scopeId)}
          siteId={ctx.data.scopeId}
          day={cal.data.date}
          onClose={() => setBooking(false)}
        />
      </Show>
    </div>
  );
}

/** The current time as a vertical line across every track; ticks each minute. */
function NowMarker(props: { open: number; close: number; tz: string }) {
  const read = () => {
    const now = wallNow(props.tz);
    return Number(now.slice(11, 13)) * 60 + Number(now.slice(14, 16));
  };
  const [minute, setMinute] = createSignal(read(), { name: 'nowMinute' });
  onSettled(() => {
    const id = setInterval(() => setMinute(read()), 60_000);
    return () => clearInterval(id);
  });
  return (
    <Show when={minute() >= props.open && minute() <= props.close}>
      <div
        class="tl-now"
        style={{ left: `calc(var(--label-w) + (100% - var(--label-w)) * ${(minute() - props.open) / (props.close - props.open)})` }}
      />
    </Show>
  );
}

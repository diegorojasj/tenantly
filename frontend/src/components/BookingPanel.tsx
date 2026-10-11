// The booking side panel shared by Today, Calendar and Bookings: what was
// booked, who and what delivers it, where it stands, and the lifecycle moves
// the server will accept from here.
import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link } from '@tanstack/solid-router';
import { createSignal, For, Loading, Show } from 'solid-js';

import { fmtDay, fmtMoney, fmtUntil, zoneName } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { actionVerb, confirmText, movedMessage, needsConfirm, nextStatuses } from '../lib/lifecycle';
import { notify } from '../lib/toast';
import ConfirmButton from './ConfirmButton';
import { setBookingStatus, joinSession } from '../lib/ops';
import { customersQuery } from '../lib/queries';
import type { Booking, BookingStatus, Template } from '../lib/types';
import Icon from './Icon';
import { KindBadge, Skeleton, StatusPill } from './ui';

export default function BookingPanel(props: {
  org: string;
  booking: Booking;
  template: Template;
  canManage: boolean;
  onClose: () => void;
}) {
  const t = () => props.template;
  // The parent <Show> can hand us a null booking for a tick while the panel
  // is closing (or the booking left the list); keep showing the last one.
  let last = props.booking;
  const booking = () => (last = props.booking ?? last);
  const isClass = () => !booking().customerId;
  const move = useMutation(() => ({
    mutationFn: (status: BookingStatus) => setBookingStatus({ org: props.org, bookingId: booking().id, status }),
    onSuccess: (_r, status) =>
      notify(movedMessage(isClass() ? booking().offeringName : booking().customerName, t().status, status)),
  }));

  return (
    <aside class="drawer" aria-label={tr('booking.panelLabel', { booking: t().terms.booking })}>
      <header class="drawer-head">
        <div>
          <p class="eyebrow">
            <KindBadge kind={booking().kind} /> {t().terms.booking}
          </p>
          <h2>{isClass() ? booking().offeringName : booking().customerName}</h2>
          <p class="muted">
            {isClass() ? tr('booking.seatsBooked', { taken: booking().attendees.length, capacity: booking().capacity }) : booking().offeringName} ·{' '}
            {fmtDay(booking().start.slice(0, 10))} {booking().start.slice(11)}–{fmtUntil(booking().start, booking().end)}
            {booking().tz && booking().tz !== 'UTC' ? ` ${tr('booking.zoneTime', { zone: zoneName(booking().tz) })}` : ''}
          </p>
        </div>
        <button type="button" class="icon-btn" aria-label={tr('booking.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>

      <div class="row start">
        <StatusPill status={booking().status} labels={t().status} />
        <Show when={!isClass()}>
          <span class={['pill', booking().paid ? 'ok' : 'neutral']}>{booking().paid ? tr('booking.paid') : tr('booking.notPaid')}</span>
        </Show>
      </div>

      <Show when={props.canManage && nextStatuses(t(), booking().status).length}>
        <div class="row start">
          <For each={nextStatuses(t(), booking().status)}>
            {(next) => (
              <Show
                when={needsConfirm(next)}
                fallback={
                  <button type="button" class="btn" disabled={move.isPending} onClick={() => move.mutate(next)}>
                    {next === 'checked_in' || next === 'completed' ? tr('booking.markStatus', { status: t().status[next] }) : actionVerb(next)}
                  </button>
                }
              >
                <ConfirmButton class="ghost" label={actionVerb(next)} confirm={confirmText(next as 'cancelled' | 'no_show')} disabled={move.isPending} onConfirm={() => move.mutate(next)} />
              </Show>
            )}
          </For>
        </div>
      </Show>
      <Show when={move.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>

      <dl class="facts">
        <dt>{t().terms.location}</dt>
        <dd>{booking().locationName}</dd>
        <dt>{tr('booking.assigned')}</dt>
        <dd>{booking().resourceNames.join(' · ') || '—'}</dd>
        <dt>{tr('booking.price')}</dt>
        <dd>
          {fmtMoney(booking().price, booking().currency)}
          {isClass() ? ` ${tr('booking.perSpot')}` : ''}
        </dd>
        <Show when={!isClass()}>
          <dt>{t().terms.customer}</dt>
          <dd>
            <Link
              to="/t/$org/customers"
              params={{ org: props.org }}
              search={{ scope: booking().locationId, customer: booking().customerId! }}
              class="link"
            >
              {booking().customerName} →
            </Link>
          </dd>
        </Show>
        <Show when={booking().subjectName}>
          {(name) => (
            <>
              <dt>{tr('booking.forLabel')}</dt>
              <dd>{name()}</dd>
            </>
          )}
        </Show>
      </dl>

      <Show when={isClass()}>
        <Attendees org={props.org} booking={booking()} template={t()} canManage={props.canManage} />
      </Show>
    </aside>
  );
}

function Attendees(props: { org: string; booking: Booking; template: Template; canManage: boolean }) {
  const [adding, setAdding] = createSignal(false, { name: 'addingAttendee' });
  const join = useMutation(() => ({
    mutationFn: (customerId: string) => joinSession({ org: props.org, bookingId: props.booking.id, customerId }),
    onSuccess: () => {
      setAdding(false);
      notify(tr('booking.addedTo', { offering: props.booking.offeringName, time: props.booking.start.slice(11) }));
    },
  }));
  const full = () => props.booking.attendees.length >= props.booking.capacity;

  return (
    <section class="intake">
      <h3>
        {props.template.terms.customers}{' '}
        <span class="muted mono">
          {props.booking.attendees.length}/{props.booking.capacity}
        </span>
      </h3>
      <div class="seat-bar" style={{ '--fill': `${Math.min(100, (props.booking.attendees.length / props.booking.capacity) * 100)}%` }} />
      <ul class="attendees">
        <For each={props.booking.attendees} fallback={<li class="muted">{tr('booking.nobodyBooked')}</li>}>
          {(a) => <li>{a.name}</li>}
        </For>
      </ul>
      <Show when={props.canManage && props.booking.status === 'confirmed' && !full()}>
        <Show
          when={adding()}
          fallback={
            <button type="button" class="btn ghost" onClick={() => setAdding(true)}>
              <Icon name="plus" size={15} /> {tr('booking.addCustomer', { customer: props.template.terms.customer.toLowerCase() })}
            </button>
          }
        >
          <Loading fallback={<Skeleton rows={1} height={36} />}>
            <AddAttendee
              org={props.org}
              booking={props.booking}
              pending={join.isPending}
              onPick={(id) => join.mutate(id)}
            />
          </Loading>
        </Show>
      </Show>
      <Show when={join.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
    </section>
  );
}

function AddAttendee(props: { org: string; booking: Booking; pending: boolean; onPick: (id: string) => void }) {
  const customers = useQuery(() => customersQuery(props.org, props.booking.locationId));
  const taken = () => new Set(props.booking.attendees.map((a) => a.id));
  return (
    <form
      class="row start"
      onSubmit={(event) => {
        event.preventDefault();
        props.onPick(String(new FormData(event.currentTarget).get('customer')));
      }}
    >
      <select name="customer" required>
        <For each={customers.data.filter((c) => !taken().has(c.id))}>
          {(c) => (
            <option value={c.id}>
              {c.name}
              {c.subscriptions.length ? ` · ${c.subscriptions.map((p) => p.name).join(', ')}` : ` · ${tr('booking.dropIn')}`}
            </option>
          )}
        </For>
      </select>
      <button type="submit" class="btn" disabled={props.pending}>
        {tr('booking.add')}
      </button>
    </form>
  );
}

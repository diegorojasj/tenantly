// The booking side panel shared by Today, Calendar and Bookings: what was
// booked, who and what delivers it, where it stands, the lifecycle moves
// the server will accept from here, and what it's owed — so finishing a
// booking and taking its payment happen in one place.
import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link } from '@tanstack/solid-router';
import { createSignal, Errored, For, Loading, Show } from 'solid-js';

import { fmtDay, fmtMoney, fmtUntil, sumMoney, toCents, zoneName } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { actionVerb, confirmText, movedMessage, needsConfirm, nextStatuses } from '../lib/lifecycle';
import { notify } from '../lib/toast';
import ConfirmButton from './ConfirmButton';
import { issueInvoice, joinSession, setBookingStatus, settleCharge } from '../lib/ops';
import { bookingChargesQuery, customersQuery } from '../lib/queries';
import type { Booking, BookingStatus, Charge, Template } from '../lib/types';
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
    onSuccess: (_r, status) => {
      const who = isClass() ? booking().offeringName : booking().customerName;
      // Finishing a booking that's charged on completion: say what's now owed, right here.
      const owes = status === 'completed' && !isClass() && !booking().paid && toCents(booking().price) > 0;
      notify(
        owes
          ? tr('booking.completedCollect', { who, status: t().status.completed.toLowerCase(), amount: fmtMoney(booking().price, booking().currency) })
          : movedMessage(who, t().status, status),
      );
    },
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

      {/* Money is billing's: if it can't answer, the booking itself still works. */}
      <Errored fallback={() => null}>
        <Loading fallback={<Skeleton rows={2} height={28} />}>
          <Payment org={props.org} booking={booking()} template={t()} />
        </Loading>
      </Errored>

      <Show when={isClass()}>
        <Attendees org={props.org} booking={booking()} template={t()} canManage={props.canManage} />
      </Show>
    </aside>
  );
}

/** What the booking raised and the moves on it: collect, invoice, refund — without leaving the panel. */
function Payment(props: { org: string; booking: Booking; template: Template }) {
  const q = useQuery(() => bookingChargesQuery(props.org, props.booking.id));
  const settle = useMutation(() => ({
    mutationFn: (input: { charge: Charge; action: 'collect' | 'refund' }) =>
      settleCharge({ org: props.org, chargeId: input.charge.id, action: input.action }),
    onSuccess: (_r, { charge, action }) => {
      const params = { amount: fmtMoney(charge.amount, charge.currency), name: charge.customerName };
      notify(action === 'collect' ? tr('payments.toastCollected', params) : tr('payments.toastRefunded', params));
    },
  }));
  const invoice = useMutation(() => ({
    mutationFn: (charge: Charge) => issueInvoice({ org: props.org, customerId: charge.customerId }),
    onSuccess: (_r, charge) => notify(tr('payments.toastInvoiceIssued', { name: charge.customerName })),
  }));
  const b = () => props.booking;
  const isOpen = (c: Charge) => c.status === 'due' || c.status === 'overdue';
  const owed = () => sumMoney(q.data.charges.filter(isOpen).map((c) => c.amount));
  const currency = () => q.data.charges[0]?.currency ?? b().currency;
  const priced = () => toCents(b().price) > 0;
  // Nothing raised yet: say when it will be, so nobody wonders whether to take money now.
  const before = () => {
    if (!b().customerId) return priced() ? tr('booking.paymentSeats', { customer: props.template.terms.customer.toLowerCase() }) : '';
    if (b().paid) return tr('booking.paymentPrepaid');
    if (!priced() || b().status === 'cancelled' || b().status === 'no_show') return '';
    if (b().status === 'completed') return tr('booking.paymentPending');
    return tr('booking.paymentOnComplete', { amount: fmtMoney(b().price, b().currency), status: props.template.status.completed });
  };
  const busy = () => settle.isPending || invoice.isPending;

  return (
    <Show when={q.data.canSee && (q.data.charges.length || before())}>
      <section class="pay-box" aria-label={tr('booking.paymentTitle')}>
        <h3>
          {tr('booking.paymentTitle')}
          <Show
            when={toCents(owed()) > 0}
            fallback={
              <Show when={q.data.charges.some((c) => c.status === 'paid')}>
                <span class="pill ok">{tr('booking.paymentSettled')}</span>
              </Show>
            }
          >
            <span class="pill warn">{tr('booking.paymentToCollect', { amount: fmtMoney(owed(), currency()) })}</span>
          </Show>
        </h3>
        <Show when={!q.data.charges.length}>
          <p class="muted">{before()}</p>
        </Show>
        <ul class="pay-list">
          <For each={q.data.charges}>
            {(c) => (
              <li class={{ dim: c.status === 'refunded' }}>
                <span>
                  {b().customerId ? c.description : c.customerName}
                  <span class="muted block">
                    {c.date} · {tr(`payments.chargeStatus_${c.status}`)}
                  </span>
                </span>
                <strong class="mono">{fmtMoney(c.amount, c.currency)}</strong>
                <span class="row-actions">
                  <Show when={q.data.canCollect}>
                    <Show when={isOpen(c) && !c.invoiceId}>
                      <button type="button" class="btn small" disabled={busy()} onClick={() => settle.mutate({ charge: c, action: 'collect' })}>
                        {tr('booking.collectNow', { amount: fmtMoney(c.amount, c.currency) })}
                      </button>
                      <button type="button" class="btn small ghost" title={tr('payments.invoiceButtonTitle')} disabled={busy()} onClick={() => invoice.mutate(c)}>
                        {tr('payments.invoiceButton')}
                      </button>
                    </Show>
                    <Show when={isOpen(c) && c.invoiceId}>
                      {(id) => (
                        <Link to="/t/$org/invoices/$id" params={{ org: props.org, id: id() }} class="pill neutral">
                          {tr('payments.onInvoice')} →
                        </Link>
                      )}
                    </Show>
                    <Show when={c.status === 'paid'}>
                      <ConfirmButton
                        class="small ghost"
                        label={tr('payments.refundButton')}
                        confirm={tr('payments.refundConfirm', { amount: fmtMoney(c.amount, c.currency) })}
                        disabled={busy()}
                        onConfirm={() => settle.mutate({ charge: c, action: 'refund' })}
                      />
                    </Show>
                  </Show>
                </span>
              </li>
            )}
          </For>
        </ul>
        <Show when={!q.data.canCollect && toCents(owed()) > 0}>
          <p class="muted">{tr('booking.paymentAskDesk')}</p>
        </Show>
        <Show when={q.data.canCollect && q.data.charges.length}>
          <Link to="/t/$org/payments" params={{ org: props.org }} search={{ scope: b().locationId }} class="link">
            {tr('booking.paymentAll')}
          </Link>
        </Show>
        <Show when={settle.error ?? invoice.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      </section>
    </Show>
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

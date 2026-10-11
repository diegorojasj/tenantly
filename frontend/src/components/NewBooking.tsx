// "New booking": one drawer for every offering. Offerings for one customer
// book a slot: the desk picks the resources the offering's `pick` requirements
// ask for (a coach, a dentist) and the server assigns the rest (a free kayak,
// a chair). Shared offerings (classes, tours) are scheduled as sessions, then
// joined seat by seat.
import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Loading, Show } from 'solid-js';

import { readFields } from '../lib/fields';
import { defined, fmtDay, fmtDuration, fmtMoney, perUnit, shiftDay, timesMoney, zoneName } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { useCurrency } from '../lib/scope';
import { matching, requirementName, resourceType } from '../lib/fulfilment';
import { createBooking, joinSession, scheduleSession } from '../lib/ops';
import { availabilityQuery, bookingOptionsQuery } from '../lib/queries';
import { notify } from '../lib/toast';
import type { Offering, Resource, ScopeNode, Template } from '../lib/types';
import FieldInput from './FieldInput';
import Icon from './Icon';
import { Skeleton } from './ui';

/** Says what's missing and where to add it, instead of an empty form. */
function Missing(props: { what: string; where: string }) {
  return (
    <p class="slots-empty">
      {tr('booking.missingBefore', { what: props.what })} <strong>{props.where}</strong> {tr('booking.missingAfter')}
    </p>
  );
}


/** One select per picked resource: requirement × quantity, each offering the resources that match it. */
interface PickSlot {
  key: string;
  label: string;
  pool: Array<Resource>;
  id: string | undefined;
}

/** Resolves the desk's choices against what's here: each slot keeps its choice if still valid, else the first free match. */
function pickSlots(t: Template, o: Offering | undefined, resources: Array<Resource>, chosen: Record<string, string>): Array<PickSlot> {
  const taken: Array<string> = [];
  const slots: Array<PickSlot> = [];
  (o?.requires ?? []).forEach((r, i) => {
    if (!r.pick) return;
    const pool = matching(resources, r);
    for (let n = 0; n < r.quantity; n++) {
      const free = pool.filter((x) => !taken.includes(x.id));
      const id = (free.find((x) => x.id === chosen[`${i}:${n}`]) ?? free[0])?.id;
      if (id) taken.push(id);
      slots.push({ key: `${i}:${n}`, label: r.role || resourceType(t, r.type).label, pool, id });
    }
  });
  return slots;
}

/** What's missing before an offering can be booked here: the first picked requirement nobody here can fill. */
function missingPick(t: Template, o: Offering | undefined, resources: Array<Resource>) {
  const r = o?.requires.find((q) => q.pick && matching(resources, q).length < q.quantity);
  return r ? { what: r.role ? `${r.role.toLowerCase()}s` : resourceType(t, r.type).plural.toLowerCase(), where: tr('booking.whereResources') } : null;
}

/** Requirements the server fills itself, for the hint under the form. */
const assignedText = (t: Template, o: Offering | undefined) =>
  (o?.requires ?? [])
    .filter((r) => !r.pick)
    .map((r) => tr('booking.assignedFree', { count: r.quantity, name: requirementName(t, r) }))
    .join(tr('booking.assignedJoin'));

function Picks(props: { slots: Array<PickSlot>; step?: string; onPick: (key: string, id: string) => void }) {
  return (
    <For each={props.slots}>
      {(slot) => (
        <label>
          <span class="form-label">
            {props.step ?? ''}
            {tr('booking.pickWith', { label: slot.label })}
          </span>
          <select value={slot.id} onChange={(event) => props.onPick(slot.key, event.currentTarget.value)}>
            <For each={slot.pool}>
              {(s) => (
                <option value={s.id}>
                  {s.name} · {s.role}
                </option>
              )}
            </For>
          </select>
        </label>
      )}
    </For>
  );
}

/** Offerings priced by the day, night or month book a span of days; how many of each one booking may take. */
const SPANS: Record<string, Array<number>> = {
  day: [1, 2, 3, 4, 5, 6, 7, 14, 30],
  night: [1, 2, 3, 4, 5, 6, 7, 14, 30],
  month: [1, 2, 3, 6, 12],
};

export default function NewBooking(props: {
  org: string;
  template: Template;
  sites: Array<ScopeNode>;
  siteId: string;
  day: string;
  onClose: () => void;
}) {
  const [site, setSite] = createSignal(() => props.siteId || props.sites[0]?.id || '', { name: 'bookingSite' });

  return (
    <aside class="drawer" aria-label={tr('booking.newTitle', { booking: props.template.terms.booking.toLowerCase() })}>
      <header class="drawer-head">
        <div>
          <p class="eyebrow">{fmtDay(props.day)}</p>
          <h2>{tr('booking.newTitle', { booking: props.template.terms.booking.toLowerCase() })}</h2>
        </div>
        <button type="button" class="icon-btn" aria-label={tr('booking.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>

      <Show when={props.sites.length > 1}>
        <label class="form">
          <span class="form-label">{props.template.terms.location}</span>
          <select value={site()} onChange={(event) => setSite(event.currentTarget.value)}>
            <For each={props.sites}>{(s) => <option value={s.id}>{s.name}</option>}</For>
          </select>
        </label>
      </Show>

      <Show when={site()} fallback={<p class="muted">{tr('booking.pickLocationFirst', { location: props.template.terms.location.toLowerCase() })}</p>}>
        <Loading fallback={<Skeleton rows={4} height={44} />}>
          <BookingModes org={props.org} template={props.template} siteId={site()} day={props.day} onDone={props.onClose} />
        </Loading>
      </Show>
    </aside>
  );
}

/**
 * What can be booked here decides the tabs: one-customer offerings get "Book a slot",
 * shared ones "Join / Schedule a class". A business that sells only one kind never sees
 * the other's tabs, and one that sells nothing yet is pointed to its catalog.
 */
function BookingModes(props: { org: string; template: Template; siteId: string; day: string; onDone: () => void }) {
  const options = useQuery(() => bookingOptionsQuery(props.org, props.siteId));
  const singles = () => options.data.offerings.length > 0;
  const classes = () => options.data.classes.length > 0;
  const [mode, setMode] = createSignal<'single' | 'session' | 'schedule'>(() => (singles() || !classes() ? 'single' : 'session'), {
    name: 'bookingMode',
  });

  return (
    <Show
      when={singles() || classes()}
      fallback={
        <p class="muted">
          {tr('booking.noOfferingsBefore')}{' '}
          <Link to="/t/$org/catalog" params={{ org: props.org }}>
            {tr('booking.whereCatalog')}
          </Link>{' '}
          {tr('booking.noOfferingsAfter')}
        </p>
      }
    >
      <Show when={classes()}>
        <div class="segmented" role="tablist">
          <Show when={singles()}>
            <button type="button" role="tab" aria-selected={mode() === 'single' ? 'true' : 'false'} onClick={() => setMode('single')}>
              {tr('booking.modeSlot')}
            </button>
          </Show>
          <button type="button" role="tab" aria-selected={mode() === 'session' ? 'true' : 'false'} onClick={() => setMode('session')}>
            {tr('booking.modeJoin')}
          </button>
          <button type="button" role="tab" aria-selected={mode() === 'schedule' ? 'true' : 'false'} onClick={() => setMode('schedule')}>
            {tr('booking.modeSchedule')}
          </button>
        </div>
      </Show>
      <Show when={mode() === 'single'}>
        <SlotForm org={props.org} template={props.template} siteId={props.siteId} day={props.day} onDone={props.onDone} />
      </Show>
      <Show when={mode() === 'session'}>
        <JoinForm org={props.org} template={props.template} siteId={props.siteId} onDone={props.onDone} onSchedule={() => setMode('schedule')} />
      </Show>
      <Show when={mode() === 'schedule'}>
        <ScheduleForm org={props.org} template={props.template} siteId={props.siteId} day={props.day} onDone={props.onDone} />
      </Show>
    </Show>
  );
}

function CustomerPicker(props: {
  template: Template;
  customers: Array<{ id: string; name: string; detail: string }>;
  step?: string;
  onPick?: (id: string) => void;
}) {
  const [query, setQuery] = createSignal('', { name: 'customerQuery' });
  const matches = createMemo(() => {
    const q = query().trim().toLowerCase();
    return props.customers.filter((c) => !q || `${c.name} ${c.detail}`.toLowerCase().includes(q)).slice(0, 80);
  });
  return (
    <label>
      <span class="form-label">
        {props.step ?? ''}
        {props.template.terms.customer}
      </span>
      <input
        type="search"
        placeholder={tr('booking.searchCustomers', { customers: props.template.terms.customers.toLowerCase() })}
        value={query()}
        onInput={(event) => setQuery(event.currentTarget.value)}
      />
      <select name="customer" required size={5} onChange={(event) => props.onPick?.(event.currentTarget.value)}>
        <For each={matches()}>
          {(c) => (
            <option value={c.id}>
              {c.name} — {c.detail}
            </option>
          )}
        </For>
      </select>
    </label>
  );
}

function SlotForm(props: { org: string; template: Template; siteId: string; day: string; onDone: () => void }) {
  const options = useQuery(() => bookingOptionsQuery(props.org, props.siteId));
  const currency = useCurrency();
  const [offeringId, setOfferingId] = createSignal('', { name: 'bookingOffering' });
  const offering = () => options.data.offerings.find((o) => o.id === offeringId()) ?? options.data.offerings[0];
  const [chosen, setChosen] = createSignal<Record<string, string>>({}, { name: 'bookingPicks' });
  const slots = () => pickSlots(props.template, offering(), options.data.resources, chosen());
  const picks = () => slots().flatMap((s) => (s.id ? [s.id] : []));
  const assigned = () => assignedText(props.template, offering());
  const [day, setDay] = createSignal(() => props.day, { name: 'bookingDay' });
  const [hours, setHours] = createSignal(0, { name: 'bookingHours' });
  const minutes = () => (offering()?.unit === 'hour' ? (hours() || offering()!.minutes / 60) * 60 : (offering()?.minutes ?? 0));
  const spans = () => SPANS[offering()?.unit ?? ''];
  const [count, setCount] = createSignal(1, { name: 'bookingSpan' });
  const units = () => (spans()?.includes(count()) ? count() : 1);
  // Only times the server will accept. The previous answer stays on screen
  // while a changed choice is re-checked, so the form never blanks out.
  const free = useQuery(() => ({
    ...availabilityQuery(props.org, props.siteId, offering()?.id ?? '', picks().join(','), day(), minutes(), units()),
    placeholderData: (previous: { slots: Array<string>; reason: string } | undefined) => previous,
  }));
  const canBook = () => !free.isPlaceholderData && free.data.slots.length > 0;
  // Offerings that serve a subject (a pet, a vehicle) book one of the chosen customer's.
  const [customerId, setCustomerId] = createSignal('', { name: 'bookingCustomer' });
  const subjectType = () => options.data.subjectTypes.find((t) => t.key === offering()?.subjectType);
  const subjects = () =>
    options.data.customers.find((c) => c.id === customerId())?.subjects.filter((x) => x.type === offering()?.subjectType) ?? [];

  const book = useMutation(() => ({
    mutationFn: (input: Parameters<typeof createBooking>[0]) => createBooking(defined(input)),
    onSuccess: (_result, input) => {
      const who = options.data.customers.find((c) => c.id === input.customerId)?.name ?? props.template.terms.customer;
      notify(
        options.data.approval
          ? tr('booking.toastRequested', { who, bookings: props.template.terms.bookings })
          : tr('booking.toastBooked', { offering: offering()?.name ?? '', who, day: fmtDay(input.start.slice(0, 10)).split(',')[0], time: input.start.slice(11) }),
      );
      props.onDone();
    },
  }));

  const missing = () =>
    !options.data.offerings.length
      ? { what: tr('booking.whatSomething'), where: tr('booking.whereCatalog') }
      : missingPick(props.template, offering(), options.data.resources)
        ? missingPick(props.template, offering(), options.data.resources)
        : !options.data.customers.length
          ? { what: props.template.terms.customers.toLowerCase(), where: props.template.terms.customers }
          : null;

  return (
    <Show when={!missing()} fallback={<Missing what={missing()!.what} where={missing()!.where} />}>
    <form
      class="form"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        book.mutate({
          org: props.org,
          locationId: props.siteId,
          offeringId: offering()!.id,
          customerId: String(data.get('customer')),
          start: `${day()}T${String(data.get('time'))}`,
          minutes: offering()?.unit === 'hour' ? minutes() : undefined,
          units: spans() ? units() : undefined,
          resourceIds: picks(),
          subjectId: subjectType() ? String(data.get('subject') ?? '') : undefined,
          fields: options.data.bookingFields.length ? readFields(options.data.bookingFields, data, 'bf-') : undefined,
        });
      }}
    >
      <Show when={options.data.approval}>
        <p class="muted hint">{tr('booking.approvalHint', { bookings: props.template.terms.bookings.toLowerCase() })}</p>
      </Show>

      <label>
        <span class="form-label">{tr('booking.stepWhat')}</span>
        <select value={offering()?.id} onChange={(event) => setOfferingId(event.currentTarget.value)}>
          <For each={options.data.offerings}>
            {(o) => (
              <option value={o.id}>
                {o.name} · {perUnit(o.unit) ? `${fmtMoney(o.price, currency())}${perUnit(o.unit)}` : `${fmtDuration(o.minutes)} · ${fmtMoney(o.price, currency())}`}
              </option>
            )}
          </For>
        </select>
      </label>

      <Picks slots={slots()} step="2 · " onPick={(key, id) => setChosen((c) => ({ ...c, [key]: id }))} />
      <Show when={offering()?.unit === 'hour'}>
        <label>
          <span class="form-label">{tr('booking.stepHowLong')}</span>
          <select value={String(minutes() / 60)} onChange={(event) => setHours(Number(event.currentTarget.value))}>
            <For each={[1, 2, 3, 4, 6, 8]}>
              {(h) => (
                <option value={h}>
                  {h} h · {fmtMoney(timesMoney(offering()!.price, h), currency())}
                </option>
              )}
            </For>
          </select>
          <Show when={assigned()}>
            <span class="muted hint">{tr('booking.assignedAuto', { what: assigned()[0].toUpperCase() + assigned().slice(1) })}</span>
          </Show>
        </label>
      </Show>
      <Show when={spans()}>
        {(choices) => (
          <label>
            <span class="form-label">{tr('booking.stepHowLong')}</span>
            <select value={String(units())} onChange={(event) => setCount(Number(event.currentTarget.value))}>
              <For each={choices()}>
                {(n) => (
                  <option value={n}>
                    {tr(`booking.span_${offering()!.unit as 'day' | 'night' | 'month'}`, { count: n })} · {fmtMoney(timesMoney(offering()!.price, n), currency())}
                  </option>
                )}
              </For>
            </select>
            <span class="muted hint">
              <Show when={offering()!.unit !== 'month'} fallback={`${tr('booking.returnMonth')} `}>
                {tr('booking.returnOn', { day: fmtDay(shiftDay(day(), units())) })}{' '}
              </Show>
              {assigned() ? tr('booking.assignedAuto', { what: assigned()[0].toUpperCase() + assigned().slice(1) }) : ''}
            </span>
          </label>
        )}
      </Show>

      <div class="form-row">
        <label>
          <span class="form-label">{tr('booking.stepDay')}</span>
          <input type="date" value={day()} required onChange={(event) => setDay(event.currentTarget.value)} />
        </label>
        <label>
          <span class="form-label">{tr('booking.freeTimes')}{options.data.tz === 'UTC' ? '' : ` · ${zoneName(options.data.tz)}`}</span>
          <Show when={free.data.slots.length} fallback={<span class="slots-empty">{free.data.reason}</span>}>
            <select name="time" required disabled={free.isPlaceholderData}>
              <For each={free.data.slots}>{(slot) => <option value={slot}>{slot}</option>}</For>
            </select>
          </Show>
        </label>
      </div>

      <CustomerPicker template={props.template} customers={options.data.customers} step="4 · " onPick={setCustomerId} />
      <Show when={subjectType()}>
        {(kind) => (
          <label>
            <span class="form-label">{kind().label}</span>
            <Show
              when={subjects().length}
              fallback={<span class="slots-empty">{customerId() ? tr('booking.noSubjects', { subjects: kind().plural.toLowerCase() }) : tr('booking.pickCustomerFirst', { customer: props.template.terms.customer.toLowerCase() })}</span>}
            >
              <select name="subject" required>
                <For each={subjects()}>{(x) => <option value={x.id}>{x.name}</option>}</For>
              </select>
            </Show>
          </label>
        )}
      </Show>
      <For each={options.data.bookingFields}>{(f) => <FieldInput def={f} prefix="bf-" />}</For>

      <Show when={book.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      <button type="submit" class="btn" disabled={book.isPending || !offering() || !canBook()}>
        {options.data.approval ? tr('booking.sendRequest') : tr('booking.bookButton', { booking: props.template.terms.booking.toLowerCase() })}
      </button>
    </form>
    </Show>
  );
}

function JoinForm(props: { org: string; template: Template; siteId: string; onDone: () => void; onSchedule: () => void }) {
  const options = useQuery(() => bookingOptionsQuery(props.org, props.siteId));
  const join = useMutation(() => ({
    mutationFn: (input: { bookingId: string; customerId: string }) => joinSession({ org: props.org, ...input }),
    onSuccess: (_result, input) => {
      const session = options.data.sessions.find((x) => x.id === input.bookingId);
      const who = options.data.customers.find((c) => c.id === input.customerId)?.name ?? props.template.terms.customer;
      notify(tr('booking.toastJoined', { who, session: session?.offeringName ?? tr('booking.theSession'), time: session?.start.slice(11) ?? '' }).trim());
      props.onDone();
    },
  }));
  return (
    <Show
      when={options.data.sessions.length && options.data.customers.length}
      fallback={
        <Show
          when={options.data.sessions.length}
          fallback={
            <div class="form">
              <p class="slots-empty">{tr('booking.noClasses')}</p>
              <button type="button" class="btn" onClick={() => props.onSchedule()}>
                {tr('booking.modeSchedule')}
              </button>
            </div>
          }
        >
          <Missing what={props.template.terms.customers.toLowerCase()} where={props.template.terms.customers} />
        </Show>
      }
    >
    <form
      class="form"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        join.mutate({ bookingId: String(data.get('session')), customerId: String(data.get('customer')) });
      }}
    >
      <label>
        <span class="form-label">{tr('booking.sessionLabel')}</span>
        <select name="session" required>
          <For each={options.data.sessions}>
            {(s) => (
              <option value={s.id} disabled={s.attendees.length >= s.capacity}>
                {fmtDay(s.start.slice(0, 10)).split(',')[0].slice(0, 3)} {s.start.slice(11)} · {s.offeringName} ·{' '}
                {s.attendees.length >= s.capacity ? tr('booking.sessionFull') : tr('booking.sessionLeft', { count: s.capacity - s.attendees.length })}
              </option>
            )}
          </For>
        </select>
      </label>
      <CustomerPicker template={props.template} customers={options.data.customers} />
      <Show when={join.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      <button type="submit" class="btn" disabled={join.isPending}>
        {tr('booking.addToSession')}
      </button>
    </form>
    </Show>
  );
}

/** Put a class or tour on the calendar, optionally every week. */
function ScheduleForm(props: { org: string; template: Template; siteId: string; day: string; onDone: () => void }) {
  const options = useQuery(() => bookingOptionsQuery(props.org, props.siteId));
  const [classId, setClassId] = createSignal('', { name: 'scheduleClass' });
  const offering = () => options.data.classes.find((c) => c.id === classId()) ?? options.data.classes[0];
  const [chosen, setChosen] = createSignal<Record<string, string>>({}, { name: 'schedulePicks' });
  const pickList = () => pickSlots(props.template, offering(), options.data.resources, chosen());
  const lacking = () => missingPick(props.template, offering(), options.data.resources);
  const slots = () => {
    const list: Array<string> = [];
    for (let m = props.template.open; m < props.template.close; m += 15) {
      list.push(`${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`);
    }
    return list;
  };
  const schedule = useMutation(() => ({
    mutationFn: (input: Omit<Parameters<typeof scheduleSession>[0], 'org'>) =>
      scheduleSession({ org: props.org, ...input }),
    onSuccess: (_r, input) => {
      const name = options.data.classes.find((c) => c.id === input.offeringId)?.name ?? tr('booking.classLabel');
      notify(input.repeatWeeks > 1 ? tr('booking.toastScheduledWeekly', { name, count: input.repeatWeeks }) : tr('booking.toastScheduled', { name }));
      props.onDone();
    },
  }));
  return (
    <Show
      when={options.data.classes.length && !lacking()}
      fallback={<Missing what={lacking()?.what ?? tr('booking.whatClass')} where={lacking()?.where ?? tr('booking.whereCatalog')} />}
    >
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          schedule.mutate({
            locationId: props.siteId,
            offeringId: offering()!.id,
            resourceIds: pickList().flatMap((s) => (s.id ? [s.id] : [])),
            start: `${String(d.get('date'))}T${String(d.get('time'))}`,
            repeatWeeks: Number(d.get('repeat')),
          });
        }}
      >
        <label>
          <span class="form-label">{tr('booking.classLabel')}</span>
          <select value={offering()?.id} onChange={(event) => setClassId(event.currentTarget.value)} required>
            <For each={options.data.classes}>
              {(c) => (
                <option value={c.id}>
                  {c.name} · {fmtDuration(c.minutes)} · {tr('booking.spots', { count: c.capacity ?? 0 })}
                </option>
              )}
            </For>
          </select>
        </label>
        <Picks slots={pickList()} onPick={(key, id) => setChosen((c) => ({ ...c, [key]: id }))} />
        <div class="form-row">
          <label>
            <span class="form-label">{tr('booking.firstDate')}</span>
            <input type="date" name="date" value={props.day} required />
          </label>
          <label>
            <span class="form-label">{tr('booking.starts')}</span>
            <select name="time" required>
              <For each={slots()}>{(slot) => <option value={slot}>{slot}</option>}</For>
            </select>
          </label>
        </div>
        <label>
          <span class="form-label">{tr('booking.repeat')}</span>
          <select name="repeat">
            <option value="1">{tr('booking.justOnce')}</option>
            <For each={[4, 8, 12]}>{(w) => <option value={w}>{tr('booking.everyWeek', { count: w })}</option>}</For>
          </select>
        </label>
        <Show when={schedule.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={schedule.isPending}>
          {tr('booking.scheduleButton')}
        </button>
      </form>
    </Show>
  );
}

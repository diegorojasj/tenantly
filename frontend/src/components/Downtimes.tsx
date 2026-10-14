import { useMutation, useQuery } from '@tanstack/solid-query';
import { createSignal, For, Show } from 'solid-js';

import ConfirmButton from './ConfirmButton';
import Icon from './Icon';
import { Panel } from './ui';
import { fmtMoney, toCents } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { createDowntime, endDowntime, recordDowntimeMoney } from '../lib/ops';
import { bookingOptionsQuery, downtimesQuery } from '../lib/queries';
import { notify } from '../lib/toast';
import type { Downtime, DowntimeReason, DowntimeTarget, ScopeNode, Template } from '../lib/types';

const REASONS: Array<DowntimeReason> = ['maintenance', 'repair', 'unfit', 'absence', 'closure', 'other'];

/** "2026-10-14 09:00 → 18:00", or "→ until further notice". */
function span(d: Pick<Downtime, 'start' | 'end'>) {
  const start = d.start.replace('T', ' ');
  if (!d.end) return `${start} → ${tr('downtime.untilFurtherNotice')}`;
  const end = d.end.slice(0, 10) === d.start.slice(0, 10) ? d.end.slice(11) : d.end.replace('T', ' ');
  return `${start} → ${end}`;
}

/**
 * Unavailability — repairs, maintenance, absences, closures. One list for the
 * scope: what is (or will be) down, the bookings it puts in doubt, and what it
 * cost or earned. Opened from Resources, where the things that go down live.
 */
export default function Downtimes(props: { org: string; scope: string; template: Template; sites: Array<ScopeNode> }) {
  const data = useQuery(() => downtimesQuery(props.org, props.scope));
  const [adding, setAdding] = createSignal(false, { name: 'downtimeAdding' });
  const [money, setMoney] = createSignal<Downtime | null>(null, { name: 'downtimeMoney' });
  const end = useMutation(() => ({
    mutationFn: (d: Downtime) => endDowntime({ org: props.org, downtimeId: d.id }),
    onSuccess: (_r, d) => notify(d.state === 'upcoming' ? tr('downtime.toastWithdrawn') : tr('downtime.toastEnded', { what: d.what })),
  }));
  const multiSite = () => props.sites.length > 1;
  const currency = () => data.data.currency;

  return (
    <Panel
      title={tr('downtime.title')}
      icon="alert"
      aside={
        <Show when={data.data.canEdit}>
          <button type="button" class="btn small" onClick={() => setAdding(true)}>
            <Icon name="plus" size={14} /> {tr('downtime.add')}
          </button>
        </Show>
      }
    >
      <p class="muted">{tr('downtime.lede')}</p>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>{tr('downtime.colWhat')}</th>
              <th>{tr('downtime.colReason')}</th>
              <th>{tr('downtime.colWhen')}</th>
              <th class="num">{tr('downtime.colMoney')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <For each={data.data.downtimes} fallback={<tr><td colspan="5" class="muted empty">{tr('downtime.empty')}</td></tr>}>
              {(d) => (
                <tr class={{ dim: d.state === 'over' }}>
                  <td>
                    <strong>{d.what}</strong>
                    <Show when={multiSite() && d.target !== 'location'}>
                      <span class="muted"> · {d.locationName}</span>
                    </Show>
                    <Show when={d.note}>
                      <div class="muted">{d.note}</div>
                    </Show>
                    <Show when={d.clashes.length}>
                      <div class="bad" title={d.clashes.map((c) => `${c.start.replace('T', ' ')} ${c.customerName} · ${c.offeringName}`).join('\n')}>
                        <Icon name="alert" size={13} /> {tr('downtime.clashes', { count: d.clashes.length })}
                      </div>
                    </Show>
                  </td>
                  <td>
                    <span class={['pill', d.state === 'now' ? 'bad' : d.state === 'upcoming' ? 'warn' : 'neutral']}>{tr(`downtime.state_${d.state}`)}</span>{' '}
                    {tr(`downtime.reason_${d.reason}`)}
                  </td>
                  <td class="mono muted">{span(d)}</td>
                  <td class="num mono">
                    <Show when={toCents(d.money.expense) > 0 || toCents(d.money.income) > 0} fallback={tr('downtime.moneyNone')}>
                      <Show when={toCents(d.money.expense) > 0}>
                        <div class="bad">{tr('downtime.moneySpent', { amount: fmtMoney(d.money.expense, currency()) })}</div>
                      </Show>
                      <Show when={toCents(d.money.income) > 0}>
                        <div class="good">{tr('downtime.moneyEarned', { amount: fmtMoney(d.money.income, currency()) })}</div>
                      </Show>
                    </Show>
                  </td>
                  <td class="row-actions">
                    <Show when={data.data.canRecordMoney}>
                      <button type="button" class="btn small ghost" onClick={() => setMoney(d)}>
                        {tr('downtime.recordMoney')}
                      </button>
                    </Show>
                    <Show when={data.data.canEdit && d.state !== 'over'}>
                      <ConfirmButton
                        class="small ghost"
                        label={d.state === 'upcoming' ? tr('downtime.withdraw') : tr('downtime.endNow')}
                        confirm={d.state === 'upcoming' ? tr('downtime.withdrawConfirm') : tr('downtime.endConfirm')}
                        disabled={end.isPending && end.variables?.id === d.id}
                        onConfirm={() => end.mutate(d)}
                      />
                    </Show>
                  </td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
      </div>
      <Show when={end.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>

      <Show when={adding()}>
        <AddDowntime org={props.org} template={props.template} sites={props.sites} onClose={() => setAdding(false)} />
      </Show>
      <Show when={money()}>
        {(d) => <DowntimeMoney org={props.org} template={props.template} downtime={d()} currency={currency()} onClose={() => setMoney(null)} />}
      </Show>
    </Panel>
  );
}

function AddDowntime(props: { org: string; template: Template; sites: Array<ScopeNode>; onClose: () => void }) {
  const [site, setSite] = createSignal(() => props.sites[0]?.id ?? '', { name: 'downtimeSite' });
  const [target, setTarget] = createSignal<DowntimeTarget>('resource', { name: 'downtimeTarget' });
  // What can be taken out at the location: its resources, and what it books.
  const options = useQuery(() => ({ ...bookingOptionsQuery(props.org, site()), enabled: !!site() }));
  const offerings = () => [...(options.data?.offerings ?? []), ...(options.data?.classes ?? [])];
  const add = useMutation(() => ({
    mutationFn: (input: Parameters<typeof createDowntime>[0]) => createDowntime(input),
    onSuccess: (_r, input) => {
      const what =
        options.data?.resources.find((r) => r.id === input.resourceId)?.name ??
        offerings().find((o) => o.id === input.offeringId)?.name ??
        props.sites.find((s) => s.id === input.locationId)?.name ??
        '';
      notify(tr('downtime.toastCreated', { what }));
      props.onClose();
    },
  }));
  const targets = (): Array<[DowntimeTarget, string]> => [
    ['resource', tr('downtime.targetResource')],
    ['offering', tr('downtime.targetOffering')],
    ['location', tr('downtime.targetLocation', { location: props.template.terms.location.toLowerCase() })],
  ];
  return (
    <aside class="drawer" aria-label={tr('downtime.add')}>
      <header class="drawer-head">
        <h2>{tr('downtime.add')}</h2>
        <button type="button" class="icon-btn" aria-label={tr('downtime.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          const pick = String(d.get('pick') ?? '');
          add.mutate({
            org: props.org,
            locationId: site(),
            resourceId: target() === 'resource' ? pick : undefined,
            offeringId: target() === 'offering' ? pick : undefined,
            reason: String(d.get('reason')) as DowntimeReason,
            note: String(d.get('note') ?? ''),
            start: String(d.get('start') ?? '') || undefined,
            end: String(d.get('end') ?? '') || undefined,
          });
        }}
      >
        <Show when={props.sites.length > 1}>
          <label>
            <span class="form-label">{props.template.terms.location}</span>
            <select value={site()} onChange={(event) => setSite(event.currentTarget.value)}>
              <For each={props.sites}>{(s) => <option value={s.id}>{s.name}</option>}</For>
            </select>
          </label>
        </Show>
        <fieldset class="chips" role="radiogroup" aria-label={tr('downtime.targetLabel')}>
          <legend class="form-label">{tr('downtime.targetLabel')}</legend>
          <For each={targets()}>
            {([value, label]) => (
              <button type="button" role="radio" aria-checked={target() === value ? 'true' : 'false'} class={['chip-toggle', { on: target() === value }]} onClick={() => setTarget(value)}>
                {label}
              </button>
            )}
          </For>
        </fieldset>
        <Show when={target() === 'resource'}>
          <label>
            <span class="form-label">{tr('downtime.targetResource')}</span>
            <select name="pick" required>
              <For each={options.data?.resources ?? []}>{(r) => <option value={r.id}>{`${r.name} · ${r.role}`}</option>}</For>
            </select>
          </label>
        </Show>
        <Show when={target() === 'offering'}>
          <label>
            <span class="form-label">{tr('downtime.targetOffering')}</span>
            <select name="pick" required>
              <For each={offerings()}>{(o) => <option value={o.id}>{o.name}</option>}</For>
            </select>
          </label>
        </Show>
        <label>
          <span class="form-label">{tr('downtime.reasonLabel')}</span>
          <select name="reason" required>
            <For each={REASONS}>{(r) => <option value={r}>{tr(`downtime.reason_${r}`)}</option>}</For>
          </select>
        </label>
        <label>
          <span class="form-label">{tr('downtime.noteLabel')}</span>
          <input type="text" name="note" maxlength="300" placeholder={tr('downtime.notePlaceholder')} />
        </label>
        <label>
          <span class="form-label">{tr('downtime.fromLabel')}</span>
          <input type="datetime-local" name="start" step="1800" />
          <span class="muted hint">{tr('downtime.fromHint')}</span>
        </label>
        <label>
          <span class="form-label">{tr('downtime.untilLabel')}</span>
          <input type="datetime-local" name="end" step="1800" />
          <span class="muted hint">{tr('downtime.untilHint')}</span>
        </label>
        <Show when={add.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={add.isPending}>
          {tr('downtime.save')}
        </button>
      </form>
    </aside>
  );
}

function DowntimeMoney(props: { org: string; template: Template; downtime: Downtime; currency: string; onClose: () => void }) {
  const [kind, setKind] = createSignal<'expense' | 'income'>('expense', { name: 'downtimeMoneyKind' });
  const options = useQuery(() => bookingOptionsQuery(props.org, props.downtime.locationId));
  const record = useMutation(() => ({
    mutationFn: (input: Parameters<typeof recordDowntimeMoney>[0]) => recordDowntimeMoney(input),
    onSuccess: (_r, input) => {
      notify(tr('downtime.toastMoney', { amount: fmtMoney(input.amount, props.currency) }));
      props.onClose();
    },
  }));
  const customer = () => props.template.terms.customer.toLowerCase();
  return (
    <aside class="drawer" aria-label={tr('downtime.moneyTitle', { what: props.downtime.what })}>
      <header class="drawer-head">
        <h2>{tr('downtime.moneyTitle', { what: props.downtime.what })}</h2>
        <button type="button" class="icon-btn" aria-label={tr('downtime.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          record.mutate({
            org: props.org,
            downtimeId: props.downtime.id,
            kind: kind(),
            amount: String(d.get('amount')),
            description: String(d.get('description') ?? ''),
            category: String(d.get('category') ?? ''),
            customerId: kind() === 'income' ? String(d.get('customer') ?? '') || undefined : undefined,
          });
        }}
      >
        <label>
          <span class="form-label">{tr('downtime.kindLabel')}</span>
          <select value={kind()} onChange={(event) => setKind(event.currentTarget.value as 'expense' | 'income')}>
            <option value="expense">{tr('downtime.kindExpense')}</option>
            <option value="income">{tr('downtime.kindIncome')}</option>
          </select>
        </label>
        <label>
          <span class="form-label">{tr('downtime.amountLabel')}</span>
          <input type="number" name="amount" min="0.01" step="0.01" required inputmode="decimal" />
        </label>
        <label>
          <span class="form-label">{tr('downtime.descriptionLabel')}</span>
          <input type="text" name="description" maxlength="200" />
        </label>
        <label>
          <span class="form-label">{tr('downtime.categoryLabel')}</span>
          <input type="text" name="category" maxlength="40" placeholder={tr('downtime.categoryPlaceholder')} />
        </label>
        <Show when={kind() === 'income'}>
          <label>
            <span class="form-label">{tr('downtime.chargeLabel')}</span>
            <select name="customer">
              <option value="">{tr('downtime.chargeNobody')}</option>
              <For each={options.data?.customers ?? []}>{(c) => <option value={c.id}>{c.name}</option>}</For>
            </select>
            <span class="muted hint">{tr('downtime.chargeHint', { customer: customer() })}</span>
          </label>
        </Show>
        <Show when={record.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={record.isPending}>
          {tr('downtime.recordButton')}
        </button>
      </form>
    </aside>
  );
}

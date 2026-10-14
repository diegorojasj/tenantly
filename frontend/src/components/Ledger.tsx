import { useMutation, useQuery } from '@tanstack/solid-query';
import { createSignal, For, Show } from 'solid-js';

import ConfirmButton from './ConfirmButton';
import Icon from './Icon';
import { Panel, Stat } from './ui';
import { fmtMoney, toCents } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { addLedgerEntry, voidLedgerEntry } from '../lib/ops';
import { ledgerQuery } from '../lib/queries';
import { notify } from '../lib/toast';
import type { LedgerEntry, ScopeNode, Template } from '../lib/types';

/**
 * Expenses & other income — what the business spends and earns beyond its
 * charges (rent, supplies, a repair bill, an insurance payout), so the net is
 * what it really made. Lines from a downtime are recorded there; the rest here.
 */
export default function Ledger(props: { org: string; scope: string; template: Template; sites: Array<ScopeNode> }) {
  const book = useQuery(() => ledgerQuery(props.org, props.scope));
  const [adding, setAdding] = createSignal(false, { name: 'ledgerAdding' });
  const [kind, setKind] = createSignal<LedgerEntry['kind']>('expense', { name: 'ledgerKind' });
  const [site, setSite] = createSignal(() => props.sites[0]?.id ?? '', { name: 'ledgerSite' });
  const currency = () => book.data.currency;
  const totals = () => book.data.totals;
  const add = useMutation(() => ({
    mutationFn: (input: Parameters<typeof addLedgerEntry>[0]) => addLedgerEntry(input),
    onSuccess: (_r, input) => {
      notify(tr('ledger.toastAdded', { amount: fmtMoney(input.amount, currency()) }));
      setAdding(false);
    },
  }));
  const voiding = useMutation(() => ({
    mutationFn: (entryId: string) => voidLedgerEntry({ org: props.org, entryId }),
    onSuccess: () => notify(tr('ledger.toastVoided')),
  }));

  return (
    <Panel
      title={tr('ledger.title')}
      icon="chart"
      aside={
        <span class="row">
          <span class="muted">{tr('ledger.period')}</span>
          <Show when={book.data.canRecord}>
            <button type="button" class="btn small" onClick={() => setAdding(!adding())}>
              <Icon name="plus" size={14} /> {tr('ledger.add')}
            </button>
          </Show>
        </span>
      }
    >
      <div class="stats">
        <Stat label={tr('ledger.statRevenue')} value={fmtMoney(totals().revenue, currency())} foot={tr('ledger.footRevenue')} />
        <Stat label={tr('ledger.statIncome')} value={fmtMoney(totals().income, currency())} />
        <Stat label={tr('ledger.statExpense')} value={fmtMoney(totals().expense, currency())} />
        <Stat
          label={tr('ledger.statNet')}
          value={<span class={{ bad: toCents(totals().net) < 0 }}>{fmtMoney(totals().net, currency())}</span>}
          foot={tr('ledger.footNet')}
        />
      </div>

      <Show when={adding()}>
        <form
          class="inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            const d = new FormData(event.currentTarget);
            add.mutate({
              org: props.org,
              locationId: site(),
              kind: kind(),
              category: String(d.get('category')),
              description: String(d.get('description') ?? ''),
              amount: String(d.get('amount')),
              on: String(d.get('on') ?? '') || undefined,
            });
          }}
        >
          <select aria-label={tr('downtime.kindLabel')} value={kind()} onChange={(event) => setKind(event.currentTarget.value as LedgerEntry['kind'])}>
            <option value="expense">{tr('ledger.kindExpense')}</option>
            <option value="income">{tr('ledger.kindIncome')}</option>
          </select>
          <Show when={props.sites.length > 1}>
            <select aria-label={props.template.terms.location} value={site()} onChange={(event) => setSite(event.currentTarget.value)}>
              <For each={props.sites}>{(s) => <option value={s.id}>{s.name}</option>}</For>
            </select>
          </Show>
          <input type="text" name="category" required maxlength="40" aria-label={tr('ledger.colCategory')} placeholder={tr('ledger.categoryPlaceholder')} />
          <input type="text" name="description" maxlength="200" aria-label={tr('ledger.colDescription')} placeholder={tr('ledger.colDescription')} />
          <input type="number" name="amount" min="0.01" step="0.01" required inputmode="decimal" aria-label={tr('ledger.colAmount')} placeholder={tr('ledger.colAmount')} />
          <input type="date" name="on" aria-label={tr('ledger.colDate')} />
          <button type="submit" class="btn small" disabled={add.isPending}>
            {tr('downtime.recordButton')}
          </button>
        </form>
      </Show>

      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>{tr('ledger.colDate')}</th>
              <th>{tr('ledger.colCategory')}</th>
              <th>{tr('ledger.colDescription')}</th>
              <th class="num">{tr('ledger.colAmount')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <For each={book.data.entries} fallback={<tr><td colspan="5" class="muted empty">{tr('ledger.empty')}</td></tr>}>
              {(e) => (
                <tr class={{ dim: e.voided }}>
                  <td class="mono muted">{e.date}</td>
                  <td>
                    <span class={['pill', e.kind === 'expense' ? 'warn' : 'ok']}>{e.kind === 'expense' ? tr('ledger.kindExpense') : tr('ledger.kindIncome')}</span>{' '}
                    {e.category}
                  </td>
                  <td>
                    <span style={e.voided ? { 'text-decoration': 'line-through' } : {}}>{e.description}</span>
                    <Show when={e.source === 'downtime'}>
                      <span class="muted"> · {tr('ledger.fromDowntime')}</span>
                    </Show>
                    <Show when={e.charged}>
                      <span class="muted"> · {tr('ledger.chargedNote')}</span>
                    </Show>
                  </td>
                  <td class={['num mono', { bad: e.kind === 'expense' && !e.voided }]}>
                    {e.kind === 'expense' ? '−' : '+'}
                    {fmtMoney(e.amount, e.currency)}
                  </td>
                  <td class="row-actions">
                    <Show when={book.data.canRecord && !e.voided}>
                      <ConfirmButton
                        class="small ghost"
                        label={tr('ledger.voidButton')}
                        confirm={tr('ledger.voidConfirm')}
                        disabled={voiding.isPending && voiding.variables === e.id}
                        onConfirm={() => voiding.mutate(e.id)}
                      />
                    </Show>
                  </td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
      </div>
      <Show when={add.error ?? voiding.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
    </Panel>
  );
}

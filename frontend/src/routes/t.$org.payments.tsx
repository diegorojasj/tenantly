import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import Icon from '../components/Icon';
import Ledger from '../components/Ledger';
import { PageHead, Panel, Stat } from '../components/ui';
import { fmtMoney, toCents } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { issueInvoice, settleCharge, settleInvoice } from '../lib/ops';
import { invoicesQuery, ledgerQuery, paymentsQuery, prefetch, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { notify } from '../lib/toast';
import type { ChargeStatus } from '../lib/types';

// Payments — one job: know what's owed and what's been paid, and act on it.
// Open charges come first, oldest debt on top; the last 30 days of settled
// history follow. A customer's open charges can be gathered onto an invoice
// (with tax per the business's settings), paid or voided as one. Below, what
// the business spends and earns beyond its charges, for the real net.
export const Route = createFileRoute('/t/$org/payments')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, paymentsQuery(params.org, deps.scope));
    prefetch(context.queryClient, invoicesQuery(params.org, deps.scope));
    prefetch(context.queryClient, ledgerQuery(params.org, deps.scope));
  },
  head: () => ({ meta: [{ title: tr('payments.headTitle') }] }),
  component: PaymentsPage,
});

type Filter = 'open' | ChargeStatus | 'all';

function PaymentsPage() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const pay = useQuery(() => paymentsQuery(org(), scope()));
  const invoices = useQuery(() => invoicesQuery(org(), scope()));
  const issue = useMutation(() => ({
    mutationFn: (customerId: string) => issueInvoice({ org: org(), customerId }),
    onSuccess: (_r, customerId) =>
      notify(
        tr('payments.toastInvoiceIssued', {
          name: pay.data.charges.find((c) => c.customerId === customerId)?.customerName ?? tr('payments.fallbackCustomer'),
        }),
      ),
  }));
  const settleInv = useMutation(() => ({
    mutationFn: (input: { invoiceId: string; action: 'pay' | 'void' }) => settleInvoice({ org: org(), ...input }),
    onSuccess: (_r, input) => {
      const inv = invoices.data.invoices.find((i) => i.id === input.invoiceId);
      const number = inv?.number ?? tr('payments.fallbackInvoice');
      notify(input.action === 'pay' ? tr('payments.toastInvoicePaid', { number }) : tr('payments.toastInvoiceVoided', { number }));
    },
  }));
  const t = () => ctx.data.tenant.template;
  const s = () => pay.data.summary;
  // Locations in scope a ledger line can be filed under, the focused one first.
  const sites = () =>
    ctx.data.nodes
      .filter((n) => n.kind === 'location' && n.reachable && (n.id === ctx.data.scopeId || ctx.data.path.at(-1)!.kind !== 'location'))
      .sort((a, b) => Number(b.id === ctx.data.scopeId) - Number(a.id === ctx.data.scopeId));

  const [filter, setFilter] = createSignal<Filter>('open', { name: 'paymentsFilter' });
  const [text, setText] = createSignal('', { name: 'paymentsText' });
  const rows = createMemo(() => {
    const q = text().trim().toLowerCase();
    return pay.data.charges.filter(
      (c) =>
        (filter() === 'all' || (filter() === 'open' ? c.status === 'due' || c.status === 'overdue' : c.status === filter())) &&
        (!q || `${c.customerName} ${c.description}`.toLowerCase().includes(q)),
    );
  });
  const settle = useMutation(() => ({
    mutationFn: (input: { chargeId: string; action: 'collect' | 'refund' }) => settleCharge({ org: org(), ...input }),
    onSuccess: (_r, input) => {
      const c = pay.data.charges.find((x) => x.id === input.chargeId);
      const params = { amount: fmtMoney(c?.amount ?? '0', c?.currency), name: c?.customerName ?? tr('payments.fallbackCustomer') };
      notify(input.action === 'collect' ? tr('payments.toastCollected', params) : tr('payments.toastRefunded', params));
    },
  }));
  const busy = (id: string) => settle.isPending && settle.variables?.chargeId === id;

  const filters: Array<[Filter, string]> = [
    ['open', tr('payments.filterOpen')],
    ['overdue', tr('payments.filterOverdue')],
    ['paid', tr('payments.filterPaid')],
    ['refunded', tr('payments.filterRefunded')],
    ['all', tr('payments.filterAll')],
  ];

  return (
    <div class="page">
      <PageHead eyebrow={ctx.data.path.at(-1)!.name} title={tr('payments.title')} lede={tr('payments.lede', { customers: t().terms.customers.toLowerCase() })} />

      <div class="stats">
        <Stat label={tr('payments.statCollected')} value={fmtMoney(s().collected30, pay.data.currency)} foot={tr('payments.footLast30')} />
        <Stat label={tr('payments.statDue')} value={fmtMoney(s().due, pay.data.currency)} foot={tr('payments.footDue')} />
        <Stat label={tr('payments.statOverdue')} value={<span class={{ bad: toCents(s().overdue) > 0 }}>{fmtMoney(s().overdue, pay.data.currency)}</span>} foot={tr('payments.footOverdue')} />
        <Stat label={tr('payments.statRefunded')} value={fmtMoney(s().refunded30, pay.data.currency)} foot={tr('payments.footLast30')} />
      </div>

      <Panel>
        <div class="toolbar">
          <div class="chips" role="group" aria-label={tr('payments.statusLabel')}>
            <For each={filters}>
              {([value, label]) => (
                <button type="button" class={['chip-toggle', { on: filter() === value }]} onClick={() => setFilter(value)}>
                  {label}
                </button>
              )}
            </For>
          </div>
          <label class="filter">
            <Icon name="search" size={15} />
            <input type="search" placeholder={tr('payments.searchPlaceholder', { customer: t().terms.customer })} value={text()} onInput={(event) => setText(event.currentTarget.value)} />
          </label>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{tr('payments.colDate')}</th>
                <th>{t().terms.customer}</th>
                <th>{tr('payments.colFor')}</th>
                <th class="num">{tr('payments.colAmount')}</th>
                <th>{tr('payments.colStatus')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <For each={rows().slice(0, 300)} fallback={<tr><td colspan="6" class="muted empty">{tr('payments.emptyCharges')}</td></tr>}>
                {(c) => (
                  <tr>
                    <td class="mono muted">{c.date}</td>
                    <td>
                      <strong>{c.customerName}</strong>
                    </td>
                    <td>
                      <span class={['kind-badge', c.source === 'plan' ? 'k-plan' : 'k-appointment']}>{c.source === 'plan' ? tr('payments.sourcePlan') : t().terms.booking}</span>{' '}
                      {c.description}
                    </td>
                    <td class="num mono">{fmtMoney(c.amount, c.currency)}</td>
                    <td>
                      <span class={['pill', c.status === 'paid' ? 'ok' : c.status === 'overdue' ? 'bad' : c.status === 'due' ? 'warn' : 'neutral']}>{tr(`payments.chargeStatus_${c.status}`)}</span>
                    </td>
                    <td class="row-actions">
                      <Show when={pay.data.canCollect}>
                        <Show when={(c.status === 'due' || c.status === 'overdue') && c.invoiceId}>
                          {(id) => (
                            <Link to="/t/$org/invoices/$id" params={{ org: org(), id: id() }} search={scope() ? { scope: scope() } : {}} class="pill neutral">
                              {tr('payments.onInvoice')} →
                            </Link>
                          )}
                        </Show>
                        <Show when={(c.status === 'due' || c.status === 'overdue') && !c.invoiceId}>
                          <button type="button" class="btn small" disabled={busy(c.id)} onClick={() => settle.mutate({ chargeId: c.id, action: 'collect' })}>
                            {tr('payments.collectButton')}
                          </button>
                          <button
                            type="button"
                            class="btn small ghost"
                            title={tr('payments.invoiceButtonTitle')}
                            disabled={issue.isPending}
                            onClick={() => issue.mutate(c.customerId)}
                          >
                            {tr('payments.invoiceButton')}
                          </button>
                        </Show>
                        <Show when={c.status === 'paid'}>
                          <ConfirmButton
                            class="small ghost"
                            label={tr('payments.refundButton')}
                            confirm={tr('payments.refundConfirm', { amount: fmtMoney(c.amount, c.currency) })}
                            disabled={busy(c.id)}
                            onConfirm={() => settle.mutate({ chargeId: c.id, action: 'refund' })}
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
        <Show when={rows().length > 300}>
          <p class="muted empty">{tr('payments.showingCapped', { shown: 300, count: rows().length })}</p>
        </Show>
        <Show when={settle.error ?? issue.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      </Panel>

      <Panel
        title={tr('payments.invoicesTitle')}
        icon="audit"
        aside={
          <span class="muted">
            {ctx.data.tenant.taxLabel} {ctx.data.tenant.taxRate}% · {ctx.data.tenant.pricesIncludeTax ? tr('payments.taxIncluded') : tr('payments.taxAdded')}
          </span>
        }
      >
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{tr('payments.colInvoice')}</th>
                <th>{tr('payments.colIssued')}</th>
                <th>{t().terms.customer}</th>
                <th class="num">{tr('payments.colSubtotal')}</th>
                <th class="num">{tr('payments.colTax')}</th>
                <th class="num">{tr('payments.colTotal')}</th>
                <th>{tr('payments.colStatus')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <For
                each={invoices.data.invoices}
                fallback={
                  <tr>
                    <td colspan="8" class="muted empty">
                      {tr('payments.emptyInvoices', { customer: t().terms.customer.toLowerCase() })}
                    </td>
                  </tr>
                }
              >
                {(inv) => (
                  <tr class={{ dim: inv.status === 'void' }}>
                    <td class="mono">
                      <Link to="/t/$org/invoices/$id" params={{ org: org(), id: inv.id }} search={scope() ? { scope: scope() } : {}} class="link">
                        {inv.number}
                      </Link>
                    </td>
                    <td class="mono muted">{inv.issuedOn}</td>
                    <td>
                      <strong>{inv.customerName}</strong>
                    </td>
                    <td class="num mono">{fmtMoney(inv.subtotal, inv.currency)}</td>
                    <td class="num mono" title={`${inv.taxLabel} ${inv.taxRate}%`}>
                      {fmtMoney(inv.tax, inv.currency)}
                    </td>
                    <td class="num mono">{fmtMoney(inv.total, inv.currency)}</td>
                    <td>
                      <span class={['pill', inv.status === 'paid' ? 'ok' : inv.status === 'open' ? 'warn' : 'neutral']}>{tr(`payments.invoiceStatus_${inv.status}`)}</span>
                    </td>
                    <td class="row-actions">
                      <Link
                        to="/t/$org/invoices/$id"
                        params={{ org: org(), id: inv.id }}
                        search={scope() ? { scope: scope() } : {}}
                        class="btn small ghost"
                        title={tr('payments.viewInvoiceTitle', { number: inv.number })}
                      >
                        {tr('payments.viewInvoice')}
                      </Link>
                      <Show when={invoices.data.canIssue && inv.status === 'open'}>
                        <button
                          type="button"
                          class="btn small"
                          disabled={settleInv.isPending}
                          onClick={() => settleInv.mutate({ invoiceId: inv.id, action: 'pay' })}
                        >
                          {tr('payments.markPaid')}
                        </button>
                        <ConfirmButton
                          class="small ghost"
                          label={tr('payments.voidButton')}
                          confirm={tr('payments.voidConfirm')}
                          disabled={settleInv.isPending}
                          onConfirm={() => settleInv.mutate({ invoiceId: inv.id, action: 'void' })}
                        />
                      </Show>
                    </td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
        <Show when={settleInv.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      </Panel>

      <Ledger org={org()} scope={scope()} template={t()} sites={sites()} />
    </div>
  );
}

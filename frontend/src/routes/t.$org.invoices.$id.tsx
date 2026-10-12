import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { Errored, For, Loading, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import Icon from '../components/Icon';
import { Skeleton } from '../components/ui';
import { fmtDay, fmtMoney } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { settleInvoice } from '../lib/ops';
import { customerQuery, invoiceQuery, prefetch, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { notify } from '../lib/toast';

// Invoice — one job: show a customer invoice the way the customer gets it,
// and print it. The page is the document; the print stylesheet drops the
// workspace around it (App.css, `@media print`), so "Print" or the browser's
// own print gives one clean page, or a PDF via "Save as PDF".
export const Route = createFileRoute('/t/$org/invoices/$id')({
  loader: ({ context, params }) => {
    prefetch(context.queryClient, invoiceQuery(params.org, params.id));
  },
  head: () => ({ meta: [{ title: tr('payments.invoiceDoc') }] }),
  component: InvoicePage,
});

function InvoicePage() {
  const { org, scope } = useTenantScope();
  const params = Route.useParams();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const inv = useQuery(() => invoiceQuery(org(), params().id));
  const tenant = () => ctx.data.tenant;
  const canSettle = () => ctx.data.role.permissions.includes('payments.collect');
  const location = () => ctx.data.nodes.find((n) => n.id === inv.data.locationId)?.name;
  const money = (amount: string) => fmtMoney(amount, inv.data.currency);
  const rate = () => String(Number(inv.data.taxRate));
  const settle = useMutation(() => ({
    mutationFn: (action: 'pay' | 'void') => settleInvoice({ org: org(), invoiceId: inv.data.id, action }),
    onSuccess: (_r, action) =>
      notify(action === 'pay' ? tr('payments.toastInvoicePaid', { number: inv.data.number }) : tr('payments.toastInvoiceVoided', { number: inv.data.number })),
  }));

  return (
    <div class="page invoice-page">
      <div class="invoice-bar no-print">
        <Link to="/t/$org/payments" params={{ org: org() }} search={scope() ? { scope: scope() } : {}} class="btn ghost">
          <Icon name="arrowLeft" size={15} /> {tr('payments.invoiceBack')}
        </Link>
        <div class="row-actions">
          <Show when={canSettle() && inv.data.status === 'open'}>
            <button type="button" class="btn ghost" disabled={settle.isPending} onClick={() => settle.mutate('pay')}>
              {tr('payments.markPaid')}
            </button>
            <ConfirmButton class="ghost" label={tr('payments.voidButton')} confirm={tr('payments.voidConfirm')} disabled={settle.isPending} onConfirm={() => settle.mutate('void')} />
          </Show>
          <button type="button" class="btn" onClick={() => window.print()}>
            {tr('payments.invoicePrint')}
          </button>
        </div>
      </div>
      <Show when={settle.error}>{(error) => <p role="alert" class="error no-print">{error()?.message}</p>}</Show>

      <article class={['invoice-doc', `inv-${inv.data.status}`]} aria-label={`${tr('payments.invoiceDoc')} ${inv.data.number}`}>
        <header class="inv-head">
          <div>
            <Show when={tenant().logoUrl}>{(src) => <img class="inv-logo" src={src()} alt="" />}</Show>
            <strong class="inv-business">{tenant().name}</strong>
            <Show when={location()}>{(name) => <span class="muted block">{name()}</span>}</Show>
          </div>
          <div class="inv-title">
            <h1>{tr('payments.invoiceDoc')}</h1>
            <span class={['inv-stamp', `inv-stamp-${inv.data.status}`]}>{tr(`payments.invoiceStamp_${inv.data.status}`)}</span>
          </div>
        </header>

        <section class="inv-meta">
          <div>
            <p class="eyebrow">{tr('payments.invoiceBilledTo')}</p>
            <strong>{inv.data.customerName}</strong>
            {/* Contact details come from operations; a role that can't open customers just sees the name. */}
            <Errored fallback={() => null}>
              <Loading fallback={<Skeleton rows={1} height={16} />}>
                <Contact org={org()} id={inv.data.customerId} />
              </Loading>
            </Errored>
          </div>
          <dl class="inv-facts">
            <dt>{tr('payments.invoiceNumberLabel')}</dt>
            <dd class="mono">{inv.data.number}</dd>
            <dt>{tr('payments.invoiceIssuedLabel')}</dt>
            <dd>{fmtDay(inv.data.issuedOn)}</dd>
            <Show when={inv.data.paidOn}>
              {(day) => (
                <>
                  <dt>{tr('payments.invoicePaidLabel')}</dt>
                  <dd>{fmtDay(day())}</dd>
                </>
              )}
            </Show>
          </dl>
        </section>

        <table class="table inv-lines">
          <thead>
            <tr>
              <th>{tr('payments.invoiceColDescription')}</th>
              <th>{tr('payments.invoiceColDate')}</th>
              <th class="num">{tr('payments.invoiceColAmount')}</th>
            </tr>
          </thead>
          <tbody>
            <For each={inv.data.lines ?? []} fallback={<tr><td colspan="3" class="muted empty">{tr('payments.invoiceNoLines')}</td></tr>}>
              {(line) => (
                <tr>
                  <td>{line.description}</td>
                  <td class="mono nowrap">{line.date}</td>
                  <td class="num mono">{money(line.amount)}</td>
                </tr>
              )}
            </For>
          </tbody>
        </table>

        <dl class="inv-totals">
          <dt>{tr('payments.colSubtotal')}</dt>
          <dd class="mono">{money(inv.data.subtotal)}</dd>
          <dt>{tr('payments.invoiceTaxLine', { label: inv.data.taxLabel, rate: rate() })}</dt>
          <dd class="mono">{money(inv.data.tax)}</dd>
          <dt class="inv-total">{tr('payments.colTotal')}</dt>
          <dd class="inv-total mono">{money(inv.data.total)}</dd>
        </dl>

        <footer class="inv-foot muted">
          <Show when={Number(inv.data.taxRate) > 0}>
            <p>
              {inv.data.pricesIncludeTax
                ? tr('payments.invoiceTaxNoteIncluded', { label: inv.data.taxLabel, rate: rate() })
                : tr('payments.invoiceTaxNoteAdded', { label: inv.data.taxLabel, rate: rate() })}
            </p>
          </Show>
          <Show when={inv.data.status === 'void'}>
            <p>{tr('payments.invoiceVoidNote')}</p>
          </Show>
        </footer>
      </article>
    </div>
  );
}

function Contact(props: { org: string; id: string }) {
  const customer = useQuery(() => customerQuery(props.org, props.id));
  const c = () => customer.data.customer;
  return (
    <>
      <Show when={c().account}>{(a) => <span class="block">{a().name}</span>}</Show>
      <Show when={c().email}>{(email) => <span class="muted block">{email()}</span>}</Show>
      <Show when={c().phone}>{(phone) => <span class="muted block">{phone()}</span>}</Show>
    </>
  );
}

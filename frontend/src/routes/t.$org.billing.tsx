import { useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { For, Show } from 'solid-js';

import { Ring, Sparkline } from '../components/Spark';
import { PageHead, Panel, Stat } from '../components/ui';
import { fmtCompact, fmtMoney, pct } from '../lib/format';
import { t } from '../lib/i18n';
import { billingQuery, prefetch } from '../lib/queries';
import { useTenantScope } from '../lib/scope';

// Usage-based billing: the plan is priced on the month's consumption (customers served,
// payments taken), never on seats. A month past its tier's limits is billed on the tier
// that fits; past Enterprise, Tenantly agrees a Custom plan with the owner.
export const Route = createFileRoute('/t/$org/billing')({
  loader: ({ context, params }) => {
    prefetch(context.queryClient, billingQuery(params.org));
  },
  head: () => ({ meta: [{ title: t('billing.headTitle') }] }),
  component: BillingPage,
});

function BillingPage() {
  const { org } = useTenantScope();
  const billing = useQuery(() => billingQuery(org()));
  const b = () => billing.data;
  const movedUp = () => b().billedPlan !== b().plan;
  const limit = (n: number | null) => (n === null ? t('billing.noLimit') : fmtCompact(n));
  const meterLimit = (id: string) => limit(b().meters.find((m) => m.id === id)?.limit ?? null);

  return (
    <div class="page">
      <PageHead
        eyebrow={t('billing.eyebrow', { plan: b().plan })}
        title={t('billing.title')}
        lede={t('billing.lede')}
      />

      <Show when={b().outgrown}>
        <p class="notice banner" role="status">
          {t('billing.outgrown')}
        </p>
      </Show>

      <div class="stats">
        <Stat
          label={t('billing.statPlan')}
          value={b().billedPlan}
          foot={
            movedUp()
              ? t('billing.footMovedUp', { plan: b().plan })
              : t('billing.footPrice', { price: fmtMoney(b().price, b().currency) })
          }
        />
        <Stat label={t('billing.statNextInvoice')} value={fmtMoney(b().nextInvoice.estimate, b().currency)} foot={t('billing.footEstimated', { date: b().nextInvoice.date })} />
        <Stat
          label={t('billing.statCollected')}
          value={fmtMoney(b().collectedThisMonth.amount, b().collectedThisMonth.currency)}
          foot={t('billing.footCollected')}
        />
      </div>

      <Panel title={t('billing.usageTitle')} icon="billing">
        <div class="meters">
          <For each={b().meters}>
            {(m) => (
              <div class="meter">
                <Ring value={m.limit === null ? 0 : pct(m.used, m.limit)} />
                <div class="meter-main">
                  <strong>{m.label}</strong>
                  <span class="muted">
                    {m.limit === null
                      ? t('billing.meterUnlimited', { used: fmtCompact(m.used), unit: m.unit, service: m.service })
                      : t('billing.meterUsage', { used: fmtCompact(m.used), limit: fmtCompact(m.limit), unit: m.unit, service: m.service })}
                  </span>
                </div>
                <span class="mono meter-pct">{m.limit === null ? '—' : `${pct(m.used, m.limit)}%`}</span>
                <Show when={m.series.length > 1}>
                  <Sparkline values={m.series} label={t('billing.meterPerDay', { label: m.label })} height={30} />
                </Show>
              </div>
            )}
          </For>
        </div>
      </Panel>

      <Panel title={t('billing.plansTitle')} icon="audit" aside={<span class="muted">{t('billing.plansAside', { currency: b().currency })}</span>}>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{t('billing.colPlan')}</th>
                <th class="num">{t('billing.colPrice')}</th>
                <th class="num">{t('billing.colCustomers')}</th>
                <th class="num">{t('billing.colPayments')}</th>
              </tr>
            </thead>
            <tbody>
              <For each={b().plans}>
                {(p) => {
                  // A Custom plan's terms are the business's own: show them on its row.
                  const mine = () => p.name === b().billedPlan && p.name === 'Custom';
                  return (
                    <tr class={{ mine: p.name === b().billedPlan }}>
                      <td>
                        {p.name}
                        <Show when={p.name === b().plan}>
                          {' '}
                          <span class="pill ok">{t('billing.current')}</span>
                        </Show>
                        <Show when={movedUp() && p.name === b().billedPlan}>
                          {' '}
                          <span class="pill warn">{t('billing.thisMonth')}</span>
                        </Show>
                      </td>
                      <td class="num mono">
                        {mine() ? fmtMoney(b().price, b().currency) : p.price === null ? t('billing.negotiated') : fmtMoney(p.price, b().currency)}
                      </td>
                      <td class="num mono">{mine() ? meterLimit('customers') : p.price === null ? t('billing.agreed') : limit(p.customerLimit)}</td>
                      <td class="num mono">{mine() ? meterLimit('payments') : p.price === null ? t('billing.agreed') : limit(p.paymentLimit)}</td>
                    </tr>
                  );
                }}
              </For>
            </tbody>
          </table>
        </div>
        <p class="muted">{t('billing.plansFoot')}</p>
      </Panel>
    </div>
  );
}

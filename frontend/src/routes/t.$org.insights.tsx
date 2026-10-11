import { useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Show } from 'solid-js';

import { Bars } from '../components/Spark';
import { Delta, KindBadge, PageHead, Panel, Stat } from '../components/ui';
import { fmtMoney, moneyValue } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { insightsQuery, prefetch, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';

// Insights — one job: is the business getting better? Every number is
// compared with the previous period of the same length. Today covers "now";
// this page covers trends, so they never repeat each other.
export const Route = createFileRoute('/t/$org/insights')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '', days: search.days ?? 28 }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, insightsQuery(params.org, deps.scope, deps.days));
  },
  head: () => ({ meta: [{ title: tr('insights.headTitle') }] }),
  component: InsightsPage,
});

function InsightsPage() {
  const { org, scope } = useTenantScope();
  const search = Route.useSearch();
  // View state, not navigation: same-route search navigations that swap a
  // query key never settled their transition on the current router RC.
  const [days, setDays] = createSignal<7 | 28>(() => search().days ?? 28, { name: 'insightsDays' });
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const data = useQuery(() => insightsQuery(org(), scope(), days()));
  const t = () => ctx.data.tenant.template;
  const d = () => data.data;
  const hasAssets = () => d().utilization.assets + d().utilization.previousAssets > 0;
  const maxSite = createMemo(() => Math.max(...d().locations.map((l) => moneyValue(l.revenue)), 1));
  const maxOffer = createMemo(() => Math.max(...d().topOfferings.map((o) => moneyValue(o.revenue)), 1));

  return (
    <div class="page">
      <PageHead
        eyebrow={tr('insights.eyebrow', { place: ctx.data.path.at(-1)!.name, days: days() })}
        title={tr('insights.title')}
        lede={tr('insights.lede')}
      >
        <div class="segmented" role="tablist">
          <button type="button" role="tab" aria-selected={days() === 7 ? 'true' : 'false'} onClick={() => setDays(7)}>
            {tr('insights.daysTab', { count: 7 })}
          </button>
          <button type="button" role="tab" aria-selected={days() === 28 ? 'true' : 'false'} onClick={() => setDays(28)}>
            {tr('insights.daysTab', { count: 28 })}
          </button>
        </div>
      </PageHead>

      <div class="stats">
        <Stat label={tr('insights.statRevenue')} value={fmtMoney(d().revenue.total, ctx.data.tenant.currency)} delta={<Delta now={moneyValue(d().revenue.total)} before={moneyValue(d().revenue.previous)} />} foot={tr('insights.footBefore', { value: fmtMoney(d().revenue.previous, ctx.data.tenant.currency) })} />
        <Stat
          label={tr('insights.statUtilization', { resource: t().terms.staff })}
          value={`${d().utilization.staff}%`}
          delta={<Delta now={d().utilization.staff} before={d().utilization.previousStaff} unit="pts" />}
          foot={tr('insights.footUtilization')}
        />
        <Show when={hasAssets()}>
          <Stat
            label={tr('insights.statUtilization', { resource: t().terms.asset })}
            value={`${d().utilization.assets}%`}
            delta={<Delta now={d().utilization.assets} before={d().utilization.previousAssets} unit="pts" />}
            foot={tr('insights.footUtilization')}
          />
        </Show>
        <Stat
          label={tr('insights.statReturning')}
          value={`${d().retention.value}%`}
          delta={d().retention.previous === null ? undefined : <Delta now={d().retention.value} before={d().retention.previous!} unit="pts" />}
          foot={tr('insights.footReturning', { customers: t().terms.customers.toLowerCase() })}
        />
        <Stat
          label={tr('insights.statNoShow')}
          value={`${d().noShowRate.value}%`}
          delta={<Delta now={d().noShowRate.value} before={d().noShowRate.previous} unit="pts" better="down" />}
          foot={tr('insights.footNoShow')}
        />
        <Stat
          label={tr('insights.statNew', { customers: t().terms.customers.toLowerCase() })}
          value={d().newCustomers.value}
          delta={<Delta now={d().newCustomers.value} before={d().newCustomers.previous} />}
          foot={tr('insights.footBefore', { value: d().newCustomers.previous })}
        />
      </div>

      <Panel title={tr('insights.revenuePerDay')} icon="billing" aside={<span class="muted">{tr('insights.revenueAside')}</span>}>
        <Bars values={d().revenue.series.map(moneyValue)} label={tr('insights.revenuePerDay')} />
        <div class="axis">
          <span>{tr('insights.axisDaysAgo', { count: days() })}</span>
          <span>{tr('insights.axisToday')}</span>
        </div>
      </Panel>

      <div class="grid two">
        <Panel title={tr('insights.topTitle')} icon="tag">
          <ol class="ranked">
            <For each={d().topOfferings} fallback={<li class="muted">{tr('insights.topEmpty')}</li>}>
              {(o) => (
                <li>
                  <span class="ranked-name">
                    <KindBadge kind={o.kind} /> {o.name}
                  </span>
                  <span class="hotspot-bar" style={{ '--w': `${(moneyValue(o.revenue) / maxOffer()) * 100}%` }} />
                  <span class="mono">{fmtMoney(o.revenue, ctx.data.tenant.currency)}</span>
                  <span class="mono muted">{o.bookings}×</span>
                </li>
              )}
            </For>
          </ol>
        </Panel>

        <Panel title={tr('insights.locationsCompared', { locations: t().terms.locations })} icon="structure">
          <ol class="ranked">
            <For each={d().locations}>
              {(l) => (
                <li>
                  <Link to="." search={{ scope: l.id, ...(days() === 7 ? { days: 7 as const } : {}) }} class="ranked-name link">
                    {l.name}
                  </Link>
                  <span class="hotspot-bar" style={{ '--w': `${(moneyValue(l.revenue) / maxSite()) * 100}%` }} />
                  <span class="mono">{fmtMoney(l.revenue, ctx.data.tenant.currency)}</span>
                  <span class={['mono', { warn: l.utilization < 35 }]}>{l.utilization}%</span>
                </li>
              )}
            </For>
          </ol>
        </Panel>
      </div>
    </div>
  );
}

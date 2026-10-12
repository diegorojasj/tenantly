import { useMutation, useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createSignal, For, Loading, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import { Bars, Ring } from '../components/Spark';
import { PageHead, Panel, Skeleton, Stat } from '../components/ui';
import { fmtDay, fmtMoney, fmtNumber } from '../lib/format';
import { t } from '../lib/i18n';
import {
  billingHistoryQuery,
  billingQuery,
  countedCustomersQuery,
  planInvoiceQuery,
  prefetch,
} from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import {
  cancelPlan,
  changePlan,
  extendPayment,
  readBillingNotice,
  resumePlan,
  withdrawPlanChange,
  startCardSetup,
  updatePlanSettings,
} from '../lib/tenancy';
import { notify } from '../lib/toast';
import type { Billing, BillingNotice, PlanLine, Standing } from '../lib/types';
import type { MessageKey } from '../locales';

// Usage-based billing (docs/BILLING.md §9): the business pays for the active
// customers it serves each month. Every number here is billing's — this page
// only words it, shows where it comes from, and offers the changes the owner
// can make. Nothing is priced in the browser.
export const Route = createFileRoute('/t/$org/billing')({
  loader: ({ context, params }) => {
    prefetch(context.queryClient, billingQuery(params.org));
    prefetch(context.queryClient, billingHistoryQuery(params.org));
  },
  head: () => ({ meta: [{ title: t('billing.headTitle') }] }),
  component: BillingPage,
});

// ------------------------------------------------------------- formatting --

/** `2026-11-01T00:00:00+00:00` → the day, read in UTC (periods are UTC months). */
const day = (iso: string) => fmtDay(iso.slice(0, 10));
/** A period's last day: its end is exclusive. */
const lastDay = (iso: string) => fmtDay(new Date(new Date(iso).getTime() - 1).toISOString().slice(0, 10));
const usd = (amount: string | number | null | undefined) => fmtMoney(amount ?? '0', 'USD');

const STANDING_LABEL: Record<Standing, MessageKey> = {
  active: 'billing.standingActive',
  past_due: 'billing.standingPastDue',
  limited: 'billing.standingLimited',
  restricted: 'billing.standingRestricted',
  canceled: 'billing.standingCanceled',
};
const STANDING_PILL: Record<Standing, string> = {
  active: 'ok',
  past_due: 'warn',
  limited: 'warn',
  restricted: 'bad',
  canceled: 'neutral',
};

const SOURCE_LABEL: Record<string, MessageKey> = {
  'booking.checked_in': 'billing.srcCheckedIn',
  'booking.completed': 'billing.srcCompleted',
  attendance: 'billing.srcAttendance',
  'plan.sold': 'billing.srcPlanSold',
};
const sourceLabel = (source: string) => (SOURCE_LABEL[source] ? t(SOURCE_LABEL[source]) : t('billing.srcOther', { source }));

const CHANGE_LABEL: Record<string, MessageKey> = {
  created: 'billing.changeCreated',
  upgrade: 'billing.changeUpgrade',
  downgrade_scheduled: 'billing.changeDowngradeScheduled',
  downgrade_withdrawn: 'billing.changeDowngradeWithdrawn',
  downgrade_applied: 'billing.changeDowngradeApplied',
  cancel_scheduled: 'billing.changeCancelScheduled',
  cancel_withdrawn: 'billing.changeCancelWithdrawn',
  canceled: 'billing.changeCanceled',
  reactivated: 'billing.changeReactivated',
  assigned: 'billing.changeAssigned',
  settings: 'billing.changeSettings',
  extension: 'billing.changeExtension',
  reprice_scheduled: 'billing.changeRepriceScheduled',
  reprice_applied: 'billing.changeRepriceApplied',
};

/** A notice in the reader's language, from its kind and the numbers billing kept with it. */
function noticeText(n: BillingNotice): string {
  const p = n.params;
  const s = (key: string) => String(p[key] ?? '');
  const on = (key: string) => (p[key] ? day(String(p[key])) : '');
  switch (n.kind) {
    case 'threshold':
      return p.overagePrice
        ? t('billing.nThreshold', {
            percent: s('percent'),
            allowance: s('allowance'),
            used: s('used'),
            price: usd(s('overagePrice')),
            cap: p.cap ? usd(s('cap')) : t('billing.spendCapWord'),
          })
        : t('billing.nThresholdNoOverage', { percent: s('percent'), allowance: s('allowance'), used: s('used') });
    case 'cap':
      return t('billing.nCap', { cap: usd(s('cap')), date: lastDay(s('periodEnd')) });
    case 'invoice':
      return t('billing.nInvoice', { number: s('number'), total: usd(s('total')), due: on('dueOn') });
    case 'paid':
      return t('billing.nPaid', { number: s('number'), total: usd(s('total')) });
    case 'card_failed':
      return t('billing.nCardFailed', { number: s('number') });
    case 'canceled':
      return t('billing.nCanceled', { number: s('number'), date: on('retentionUntil') });
    case 'plan_repriced':
      return t('billing.nRepriced', {
        plan: s('plan'),
        old: usd(s('oldPrice')),
        price: usd(s('price')),
        included: p.included === null || p.included === undefined ? '∞' : s('included'),
        date: on('effectiveOn'),
      });
    default: {
      const keys: Record<string, MessageKey> = {
        overdue: 'billing.nOverdue',
        limit_warning: 'billing.nLimitWarning',
        limited: 'billing.nLimited',
        restrict_warning: 'billing.nRestrictWarning',
        restricted: 'billing.nRestricted',
        cancel_warning: 'billing.nCancelWarning',
      };
      return t(keys[n.kind] ?? 'billing.nOverdue', {
        number: s('number'),
        balance: usd(s('balance')),
        limitsOn: on('limitsOn'),
        restrictsOn: on('restrictsOn'),
        cancelsOn: on('cancelsOn'),
      });
    }
  }
}

function lineText(line: PlanLine): string {
  const d = line.detail;
  switch (line.kind) {
    case 'base':
      return d.prorated
        ? t('billing.lineBaseProrated', { plan: String(d.plan), from: day(String(d.from)), until: lastDay(String(d.until)) })
        : t('billing.lineBase', { plan: String(d.plan) });
    case 'overage':
      return t('billing.lineOverage', { count: line.quantity, allowance: String(d.allowance), price: usd(line.unitPrice) });
    case 'cap':
      return t('billing.lineCap', { cap: usd(String(d.cap)) });
    case 'discount':
      return t('billing.lineDiscount', { percent: String(d.percent) });
    default:
      return t('billing.lineCredit');
  }
}

// ------------------------------------------------------------------ page --

function BillingPage() {
  const { org } = useTenantScope();
  const billing = useQuery(() => billingQuery(org()));
  const b = () => billing.data;

  return (
    <div class="page">
      <PageHead eyebrow={t('billing.eyebrow', { plan: b().plan.name })} title={t('billing.title')} lede={t('billing.lede')} />

      <Header billing={b()} />
      <StandingBanner billing={b()} org={org()} />
      <Notices billing={b()} org={org()} />

      <div class="grid two">
        <UsagePanel billing={b()} />
        <EstimatePanel billing={b()} />
      </div>

      <Counted org={org()} billing={b()} />
      <Plans billing={b()} org={org()} />
      <Settings billing={b()} org={org()} />
      <History org={org()} />

      <Panel title={t('billing.infoTitle')} icon="chart">
        <div class="stats">
          <Stat label={t('billing.infoBookings')} value={fmtNumber(b().informational.bookings)} />
          <Stat label={t('billing.infoPayments')} value={fmtNumber(b().informational.payments)} />
          <Stat
            label={t('billing.infoCollected')}
            value={fmtMoney(b().informational.collected.amount, b().informational.collected.currency)}
          />
        </div>
      </Panel>
    </div>
  );
}

function Header(props: { billing: Billing }) {
  const b = () => props.billing;
  const priceFoot = () =>
    b().plan.custom
      ? t('billing.footCustom', { price: usd(b().plan.price) })
      : b().plan.legacy
        ? t('billing.footLegacy', { price: usd(b().plan.price) })
        : t('billing.footPlanPrice', { price: usd(b().plan.price) });
  const ending = () => b().cancelAtPeriodEnd || b().status === 'canceled';
  return (
    <div class="stats">
      <Stat label={t('billing.statPlan')} value={b().plan.name} foot={priceFoot()} />
      <Stat
        label={t('billing.statPeriod')}
        value={`${day(b().period.start)} – ${lastDay(b().period.end)}`}
        foot={ending() ? t('billing.footEnds', { date: day(b().period.end) }) : t('billing.footRenews', { date: day(b().period.end) })}
      />
      <Stat
        label={t('billing.statEstimate')}
        value={usd(b().estimate.total)}
        foot={
          b().estimate.projectedTotal
            ? t('billing.footProjected', { total: usd(b().estimate.projectedTotal), date: lastDay(b().period.end) })
            : t('billing.footSettled')
        }
      />
      <Stat
        label={t('billing.statStatus')}
        value={<span class={['pill', STANDING_PILL[b().standing.status]]}>{t(STANDING_LABEL[b().standing.status])}</span>}
        foot={b().payment.method === 'stripe' ? t('billing.footPaidCard') : t('billing.footPaidTransfer')}
      />
    </div>
  );
}

/** What an unpaid invoice holds back, from when, and the ways out — or that the plan is ending. */
function StandingBanner(props: { billing: Billing; org: string }) {
  const b = () => props.billing;
  const st = () => b().standing;
  const inv = () => st().invoice;
  const card = useMutation(() => ({
    mutationFn: () =>
      startCardSetup({ org: props.org, returnUrl: `${location.origin}${location.pathname}` }) as unknown as Promise<{ url: string }>,
    onSuccess: (result) => {
      location.assign(result.url);
    },
  }));
  const extend = useMutation(() => ({
    mutationFn: () => extendPayment({ org: props.org, revision: b().revision }),
    onSuccess: () => notify(t('billing.toastExtended')),
  }));
  const resume = useMutation(() => ({
    mutationFn: () => resumePlan({ org: props.org, revision: b().revision }),
    onSuccess: () => notify(t('billing.toastResumed')),
  }));
  const message = () => {
    const i = inv();
    const params = {
      number: i?.number ?? '',
      amount: usd(st().balance),
      due: i ? fmtDay(i.dueOn) : '',
      limitsOn: st().limitsOn ? fmtDay(st().limitsOn!) : '',
      restrictsOn: st().restrictsOn ? fmtDay(st().restrictsOn!) : '',
      cancelsOn: st().cancelsOn ? fmtDay(st().cancelsOn!) : '',
    };
    switch (st().status) {
      case 'past_due':
        return st().disputed ? t('billing.bannerDisputed', params) : t('billing.bannerPastDue', params);
      case 'limited':
        return t('billing.bannerLimited', params);
      case 'restricted':
        return t('billing.bannerRestricted', params);
      default:
        return '';
    }
  };
  const retention = () => (st().retentionUntil ? fmtDay(st().retentionUntil!) : '');
  const owing = () => b().notices.some((n) => n.kind === 'canceled');
  return (
    <>
      <Show when={['past_due', 'limited', 'restricted'].includes(st().status)}>
        <div class={['banner', st().status === 'restricted' ? 'error' : 'notice']} role="status">
          <p>{message()}</p>
          <Show when={inv()}>{(i) => <p class="muted">{t('billing.bannerPayTransfer', { number: i().number })}</p>}</Show>
          <Show when={b().canManage}>
            <div class="row start">
              <Show when={b().payment.cardsAvailable}>
                <button type="button" class="btn small" disabled={card.isPending} onClick={() => card.mutate()}>
                  {t('billing.payByCard')}
                </button>
              </Show>
              <Show when={st().extensionAvailable}>
                <ConfirmButton
                  class="small ghost"
                  label={t('billing.extend', { days: b().policy.extensionDays })}
                  confirm={t('billing.extendConfirm', { days: b().policy.extensionDays })}
                  disabled={extend.isPending}
                  onConfirm={() => extend.mutate()}
                />
              </Show>
            </div>
          </Show>
        </div>
      </Show>
      <Show when={st().status === 'canceled'}>
        <div class="banner notice" role="status">
          <p>
            {owing()
              ? t('billing.bannerCanceledOwing', { number: String(b().notices.find((n) => n.kind === 'canceled')?.params.number ?? ''), date: retention() })
              : t('billing.bannerCanceled', { date: retention() })}
          </p>
          <Show when={b().canManage && !owing()}>
            <div class="row start">
              <button type="button" class="btn small" disabled={resume.isPending} onClick={() => resume.mutate()}>
                {t('billing.reactivate')}
              </button>
            </div>
          </Show>
        </div>
      </Show>
      <Show when={b().cancelAtPeriodEnd}>
        <div class="banner notice" role="status">
          <p>{t('billing.bannerEnding', { date: lastDay(b().period.end) })}</p>
          <Show when={b().canManage}>
            <div class="row start">
              <button type="button" class="btn small" disabled={resume.isPending} onClick={() => resume.mutate()}>
                {t('billing.resume')}
              </button>
            </div>
          </Show>
        </div>
      </Show>
      <Show when={card.error ?? extend.error ?? resume.error}>
        {(error) => <p role="alert" class="error banner">{error()?.message}</p>}
      </Show>
    </>
  );
}

function Notices(props: { billing: Billing; org: string }) {
  const ordered = () => [...props.billing.notices].sort((a, b) => Number(a.read) - Number(b.read));
  const read = useMutation(() => ({
    mutationFn: (id: number) => readBillingNotice({ org: props.org, id }),
  }));
  return (
    <Show when={props.billing.notices.some((n) => !n.read)}>
      <Panel title={t('billing.noticesTitle')} icon="audit">
        <ul class="notice-list">
          <For each={ordered()}>
            {(n) => (
              <li class={{ dim: n.read }}>
                <span>{noticeText(n)}</span>
                <span class="muted nowrap">{day(n.createdAt)}</span>
                <Show when={!n.read}>
                  <button type="button" class="btn small ghost" disabled={read.isPending} onClick={() => read.mutate(n.id)}>
                    {t('billing.markRead')}
                  </button>
                </Show>
              </li>
            )}
          </For>
        </ul>
      </Panel>
    </Show>
  );
}

function UsagePanel(props: { billing: Billing }) {
  const u = () => props.billing.usage;
  const share = () => (u().allowance ? Math.min(100, Math.round((u().used / u().allowance!) * 100)) : 0);
  const over = () => (u().allowance === null ? 0 : Math.max(0, u().used - u().allowance!));
  return (
    <Panel title={t('billing.usageTitle')} icon="billing">
      <div class="meter usage-meter">
        <Ring value={share()} size={64} />
        <div class="meter-main">
          <strong>
            {u().allowance === null
              ? t('billing.usageNoLimit', { used: fmtNumber(u().used) })
              : t('billing.usageOf', { used: fmtNumber(u().used), allowance: fmtNumber(u().allowance!) })}
          </strong>
          <Show when={u().allowance !== null}>
            <span class={['muted', { bad: over() > 0 }]}>
              {over() > 0 ? t('billing.usageOver', { count: over() }) : t('billing.usageLeft', { count: u().remaining ?? 0 })}
            </span>
          </Show>
          <Show when={u().projected}>
            {(n) => <span class="muted">{t('billing.usageProjected', { count: fmtNumber(n()), date: lastDay(props.billing.period.end) })}</span>}
          </Show>
        </div>
        <span class="mono meter-pct">{u().percent === null ? '—' : `${u().percent}%`}</span>
      </div>
      <Show when={u().allowance !== null}>
        {/* The 80% and 100% marks the alerts default to. */}
        <div class="usage-bar" role="img" aria-label={t('billing.usageOf', { used: u().used, allowance: u().allowance ?? 0 })}>
          <span class={['usage-fill', { hot: share() >= 80 }]} style={{ width: `${share()}%` }} />
          <span class="usage-mark" style={{ left: '80%' }} />
        </div>
      </Show>
      <Show when={u().series.length > 1}>
        <Bars values={u().series} label={t('billing.usagePerDay')} />
      </Show>
      <p class="muted hint">{t('billing.usageHow')}</p>
    </Panel>
  );
}

function EstimatePanel(props: { billing: Billing }) {
  const e = () => props.billing.estimate;
  return (
    <Panel title={t('billing.estimateTitle')} icon="billing">
      <div class="table-wrap">
        <table class="table">
          <tbody>
            <For each={e().lines}>
              {(line) => (
                <tr>
                  <td>{lineText(line)}</td>
                  <td class="num mono">{usd(line.amount)}</td>
                </tr>
              )}
            </For>
            <tr>
              <td>
                <strong>{t('billing.estimateTotal')}</strong>
              </td>
              <td class="num mono">
                <strong>{usd(e().total)}</strong>
              </td>
            </tr>
            <Show when={e().projectedTotal}>
              {(total) => (
                <tr class="dim">
                  <td>{t('billing.estimateProjected')}</td>
                  <td class="num mono">{usd(total())}</td>
                </tr>
              )}
            </Show>
          </tbody>
        </table>
      </div>
      <p class="muted hint">{t('billing.estimateFoot')}</p>
    </Panel>
  );
}

/** The customers behind the number, 100 at a time, downloadable for a dispute. */
function Counted(props: { org: string; billing: Billing }) {
  const [offset, setOffset] = createSignal(0, { name: 'countedOffset' });
  const counted = useQuery(() => countedCustomersQuery(props.org, props.billing.period.id, offset()));
  const csv = () => {
    const rows = counted.data.customers.map((c) =>
      [c.name, c.customerId, c.firstSeenAt, c.source, c.reference].map((v) => `"${String(v).replaceAll('"', '""')}"`).join(','),
    );
    const blob = new Blob([['name,customer_id,first_counted_at,source,reference', ...rows].join('\n')], { type: 'text/csv' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `active-customers-${props.billing.period.start.slice(0, 7)}-${offset() / 100 + 1}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  };
  return (
    <Panel title={t('billing.countedTitle')} icon="users" aside={<span class="muted">{t('billing.countedAside', { count: props.billing.usage.used })}</span>}>
      <Loading fallback={<Skeleton rows={3} height={36} />}>
        <Show when={counted.data.total > 0} fallback={<p class="muted">{t('billing.countedEmpty')}</p>}>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>{t('billing.colCustomer')}</th>
                  <th>{t('billing.colWhy')}</th>
                  <th>{t('billing.colFirst')}</th>
                </tr>
              </thead>
              <tbody>
                <For each={counted.data.customers}>
                  {(c) => (
                    <tr>
                      <td>{c.name || c.customerId}</td>
                      <td>{sourceLabel(c.source)}</td>
                      <td class="nowrap">{day(c.firstSeenAt)}</td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
          </div>
          <div class="row start">
            <span class="muted">
              {t('billing.pageOf', {
                from: offset() + 1,
                to: offset() + counted.data.customers.length,
                total: counted.data.total,
              })}
            </span>
            <button type="button" class="btn small ghost" disabled={offset() === 0} onClick={() => setOffset((o) => Math.max(0, o - 100))}>
              {t('billing.prevPage')}
            </button>
            <button
              type="button"
              class="btn small ghost"
              disabled={offset() + 100 >= counted.data.total}
              onClick={() => setOffset((o) => o + 100)}
            >
              {t('billing.nextPage')}
            </button>
            <button type="button" class="btn small ghost" onClick={csv}>
              {t('billing.downloadCsv')}
            </button>
          </div>
        </Show>
      </Loading>
    </Panel>
  );
}

function Plans(props: { billing: Billing; org: string }) {
  const b = () => props.billing;
  const renewal = () => day(b().period.end);
  const change = useMutation(() => ({
    mutationFn: (input: { plan: string; name: string }) => changePlan({ org: props.org, plan: input.plan, revision: b().revision }),
    onSuccess: (_r, input) => {
      const current = b().plan;
      const target = b().plans.find((p) => p.code === input.plan);
      if (target && target.id === current.id) notify(t('billing.toastWithdrawn', { plan: input.name }));
      else if (target && target.rank > current.rank) notify(t('billing.toastUpgraded', { plan: input.name }));
      else notify(t('billing.toastScheduled', { plan: input.name }));
    },
  }));
  const withdraw = useMutation(() => ({
    mutationFn: () => withdrawPlanChange({ org: props.org, revision: b().revision }),
    onSuccess: () => notify(t('billing.toastWithdrawn', { plan: b().plan.name })),
  }));
  const cancel = useMutation(() => ({
    mutationFn: () => cancelPlan({ org: props.org, revision: b().revision }),
    onSuccess: () => notify(t('billing.toastCanceled')),
  }));
  const live = () => b().status === 'active';
  // While the plan is ending billing refuses changes (an upgrade would be billed, then end anyway):
  // the owner resumes it first, from the banner.
  const changeable = () => b().canManage && live() && !b().cancelAtPeriodEnd;
  const busy = () => change.isPending || withdraw.isPending || cancel.isPending;
  return (
    <Panel title={t('billing.plansTitle')} icon="audit" aside={<span class="muted">{t('billing.plansAside', { currency: b().currency })}</span>}>
      <Show when={b().scheduled}>
        {(next) => (
          <div class="banner notice" role="status">
            <p>{t('billing.bannerScheduled', { plan: next().name, date: renewal(), current: b().plan.name })}</p>
            <Show when={b().canManage}>
              <button type="button" class="btn small" disabled={busy()} onClick={() => withdraw.mutate()}>
                {t('billing.withdraw', { plan: b().plan.name })}
              </button>
            </Show>
          </div>
        )}
      </Show>
      <Show when={b().plan.custom}>
        <p class="muted">{t('billing.customNote', { price: usd(b().plan.price) })}</p>
      </Show>
      <Show when={b().plan.legacy && !b().plan.custom}>
        <p class="muted">{t('billing.legacyNote', { plan: b().plan.name })}</p>
      </Show>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>{t('billing.colPlan')}</th>
              <th class="num">{t('billing.colPrice')}</th>
              <th class="num">{t('billing.colIncluded')}</th>
              <th class="num">{t('billing.colOverage')}</th>
              <th class="num">{t('billing.colCap')}</th>
              <th class="num">{t('billing.colThisPeriod')}</th>
              <Show when={changeable()}>
                <th />
              </Show>
            </tr>
          </thead>
          <tbody>
            <For each={b().plans}>
              {(p) => {
                const mine = () => p.id === b().plan.id;
                const sameTier = () => p.code === b().plan.code;
                const up = () => p.rank > b().plan.rank;
                const waiting = () => b().scheduled?.id === p.id;
                return (
                  <tr class={{ mine: sameTier() }}>
                    <td>
                      {p.name}
                      <Show when={mine()}>
                        {' '}
                        <span class="pill ok">{t('billing.current')}</span>
                      </Show>
                      <Show when={waiting()}>
                        {' '}
                        <span class="pill warn">{t('billing.scheduledPill', { date: renewal() })}</span>
                      </Show>
                    </td>
                    <td class="num mono">{usd(p.price)}</td>
                    <td class="num mono">{p.included === null ? t('billing.noLimit') : fmtNumber(p.included)}</td>
                    <td class="num mono">{p.overagePrice ? usd(p.overagePrice) : t('billing.noOverage')}</td>
                    <td class="num mono">{p.cap ? usd(p.cap) : p.overagePrice ? t('billing.spendCapWord') : t('billing.noOverage')}</td>
                    <td class="num mono">{usd(p.thisPeriod)}</td>
                    <Show when={changeable()}>
                      <td class="num">
                        <Show when={!mine() && !waiting()}>
                          <ConfirmButton
                            class="small"
                            label={up() ? t('billing.upgrade') : sameTier() ? t('billing.switchVersion') : t('billing.downgrade')}
                            confirm={up() ? t('billing.upgradeConfirm') : t('billing.downgradeConfirm', { date: renewal() })}
                            disabled={busy()}
                            onConfirm={() => change.mutate({ plan: p.code, name: p.name })}
                          />
                        </Show>
                      </td>
                    </Show>
                  </tr>
                );
              }}
            </For>
          </tbody>
        </table>
      </div>
      <p class="muted">{t('billing.plansFoot')}</p>
      <Show when={b().canManage} fallback={<p class="muted hint">{t('billing.readOnly')}</p>}>
        <Show when={changeable()} fallback={<Show when={b().cancelAtPeriodEnd}><p class="muted hint">{t('billing.endingNoChanges')}</p></Show>}>
          <div class="row start">
            <ConfirmButton
              class="small ghost"
              label={t('billing.cancel')}
              confirm={t('billing.cancelConfirm', { date: lastDay(b().period.end) })}
              disabled={busy()}
              onConfirm={() => cancel.mutate()}
            />
          </div>
        </Show>
      </Show>
      <Show when={change.error ?? withdraw.error ?? cancel.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
    </Panel>
  );
}

function Settings(props: { billing: Billing; org: string }) {
  const b = () => props.billing;
  const save = useMutation(() => ({
    mutationFn: (input: { spendCap: string | null; alertThresholds: Array<number> }) => updatePlanSettings({ org: props.org, ...input }),
    onSuccess: () => notify(t('billing.toastSaved')),
  }));
  const card = useMutation(() => ({
    mutationFn: () =>
      startCardSetup({ org: props.org, returnUrl: `${location.origin}${location.pathname}` }) as unknown as Promise<{ url: string }>,
    onSuccess: (result) => {
      location.assign(result.url);
    },
  }));
  return (
    <Panel title={t('billing.settingsTitle')} icon="config">
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          const thresholds = String(d.get('thresholds') ?? '')
            .split(/[,\s]+/)
            .map(Number)
            .filter((n) => Number.isFinite(n) && n > 0);
          const cap = String(d.get('spendCap') ?? '').trim();
          save.mutate({ spendCap: cap || null, alertThresholds: thresholds });
        }}
      >
        <label>
          <span class="form-label">{t('billing.thresholdsLabel')}</span>
          <input name="thresholds" value={b().alertThresholds.join(', ')} disabled={!b().canManage} inputmode="numeric" />
          <span class="muted hint">{t('billing.thresholdsHint')}</span>
        </label>
        <Show when={b().spendCap.editable}>
          <label>
            <span class="form-label">{t('billing.spendCapLabel')}</span>
            <input
              name="spendCap"
              type="number"
              min={b().plan.price}
              step="0.01"
              value={b().spendCap.value ?? ''}
              placeholder={b().spendCap.default}
              disabled={!b().canManage}
            />
            <span class="muted hint">{t('billing.spendCapHint', { default: usd(b().spendCap.default) })}</span>
          </label>
        </Show>
        <Show when={b().canManage}>
          <button type="submit" class="btn" disabled={save.isPending}>
            {t('billing.save')}
          </button>
        </Show>
      </form>
      <p class="muted">{b().payment.method === 'stripe' ? t('billing.methodCard') : t('billing.methodTransfer', { days: b().policy.paymentTermsDays })}</p>
      <Show when={b().canManage}>
        <Show when={b().payment.cardsAvailable} fallback={<p class="muted hint">{t('billing.cardsUnavailable')}</p>}>
          <button type="button" class="btn small ghost" disabled={card.isPending} onClick={() => card.mutate()}>
            {b().payment.card ? t('billing.updateCard') : t('billing.addCard')}
          </button>
        </Show>
      </Show>
      <Show when={save.error ?? card.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
    </Panel>
  );
}

function History(props: { org: string }) {
  const history = useQuery(() => billingHistoryQuery(props.org));
  const [open, setOpen] = createSignal<string | null>(null, { name: 'openPlanInvoice' });
  const invoiceStatus = (inv: { status: string; dueOn: string }) =>
    inv.status === 'paid' ? t('billing.invPaid') : inv.status === 'void' ? t('billing.invVoid') : t('billing.invOpen', { date: fmtDay(inv.dueOn) });
  const periodStatus = (status: string) =>
    status === 'open' ? t('billing.periodOpen') : status === 'held' ? t('billing.periodHeld') : t('billing.periodClosing');
  return (
    <Panel title={t('billing.historyTitle')} icon="calendar">
      <Loading fallback={<Skeleton rows={3} height={36} />}>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{t('billing.colMonth')}</th>
                <th>{t('billing.colPlan')}</th>
                <th class="num">{t('billing.colUsed')}</th>
                <th>{t('billing.colInvoice')}</th>
                <th>{t('billing.colStatus')}</th>
              </tr>
            </thead>
            <tbody>
              <For each={history.data.periods}>
                {(p) => (
                  <tr>
                    <td class="nowrap">
                      {day(p.start)} – {lastDay(p.end)}
                    </td>
                    <td>{p.plan}</td>
                    <td class="num mono">{p.allowance === null ? fmtNumber(p.used) : `${fmtNumber(p.used)} / ${fmtNumber(p.allowance)}`}</td>
                    <td>
                      <Show when={p.invoice} fallback={<span class="muted">—</span>}>
                        {(inv) => (
                          <button type="button" class="btn small ghost" onClick={() => setOpen(open() === inv().id ? null : inv().id)}>
                            {inv().number} · {usd(inv().total)}
                          </button>
                        )}
                      </Show>
                    </td>
                    <td>
                      {p.invoice ? (
                        <span class={['pill', p.invoice.status === 'paid' ? 'ok' : p.invoice.status === 'void' ? 'neutral' : 'warn']}>
                          {invoiceStatus(p.invoice)}
                        </span>
                      ) : (
                        <span class="pill neutral">{periodStatus(p.status)}</span>
                      )}
                    </td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
        <Show when={open()}>{(id) => <InvoiceLines org={props.org} id={id()} onClose={() => setOpen(null)} />}</Show>

        <h3 class="subhead">{t('billing.changesTitle')}</h3>
        <ul class="change-list">
          <For each={history.data.changes}>
            {(c) => (
              <li>
                <span>
                  {CHANGE_LABEL[c.kind] ? t(CHANGE_LABEL[c.kind], { from: c.from ?? '', to: c.to ?? '', days: String(c.detail.days ?? 7) }) : c.kind}{' '}
                  <span class="muted">{t('billing.changeBy', { name: c.by })}</span>
                </span>
                <span class="muted nowrap">{day(c.at)}</span>
              </li>
            )}
          </For>
        </ul>
      </Loading>
    </Panel>
  );
}

function InvoiceLines(props: { org: string; id: string; onClose: () => void }) {
  const invoice = useQuery(() => planInvoiceQuery(props.org, props.id));
  return (
    <Loading fallback={<Skeleton rows={2} height={32} />}>
      <div class="invoice-detail">
        <div class="row">
          <strong>{t('billing.invoiceTitle', { number: invoice.data.number })}</strong>
          <button type="button" class="btn small ghost" onClick={() => props.onClose()}>
            {t('billing.closeInvoice')}
          </button>
        </div>
        <table class="table">
          <tbody>
            <For each={invoice.data.lines ?? []}>
              {(line) => (
                <tr>
                  <td>{lineText(line)}</td>
                  <td class="num mono">{usd(line.amount)}</td>
                </tr>
              )}
            </For>
            <tr>
              <td>
                <strong>{t('billing.estimateTotal')}</strong>
              </td>
              <td class="num mono">
                <strong>{usd(invoice.data.total)}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Loading>
  );
}

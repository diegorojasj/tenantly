import { useMutation, useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createSignal, Errored, For, Loading, onSettled, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import Icon from '../components/Icon';
import LanguageSwitch from '../components/LanguageSwitch';
import Toaster from '../components/Toaster';
import { Boundary, Mark, PageHead, Panel, Skeleton, Stat } from '../components/ui';
import {
  addBusiness,
  addGrant,
  adminSignIn,
  adminSignOut,
  assignPlan,
  createOwner,
  editPolicy,
  markInvoicePaid,
  repricePlan,
  setOwnerStatus,
} from '../lib/admin';
import { fmtDay, fmtMoney, fmtNumber, fmtStamp } from '../lib/format';
import { t } from '../lib/i18n';
import {
  adminAuditQuery,
  adminOwnersQuery,
  adminPlansQuery,
  adminPolicyQuery,
  adminSubscriptionQuery,
  adminViewerQuery,
  prefetch,
} from '../lib/queries';
import { notify } from '../lib/toast';
import type {
  AdminAuditEvent,
  AdminBusiness,
  AdminOwner,
  AdminPlan,
  AdminSubscription,
  AdminViewer,
  BillingPolicy,
  GrantKind,
  NewBusiness,
  OwnerStatus,
  PlanInvoice,
  PlanLine,
  PolicyFields,
  Standing,
  StartingPlan,
} from '../lib/types';
import type { MessageKey } from '../locales';

// The Tenantly admin console. It is served only on the admin host (ADMIN_HOST; the proxy
// and src/middleware.ts keep it off the app's host and the app off this one), with its own
// session: an admin token that lasts no longer than the admin's access window, opened from
// the server with `manage.py activate_admin`. The page counts the window down and signs out
// when it closes; identity refuses every call after that anyway. Every change lands in the
// admin audit log (the Audit tab) and, for a business, in its own audit trail.
export const Route = createFileRoute('/admin')({
  loader: ({ context }) => {
    prefetch(context.queryClient, adminViewerQuery());
  },
  head: () => ({ meta: [{ title: t('admin.headTitle') }] }),
  component: AdminPage,
});

// ------------------------------------------------------------- formatting --

/** `2026-11-01T00:00:00+00:00` → the day, read in UTC. */
const day = (iso: string) => fmtDay(iso.slice(0, 10));
/** A period's last day: its end is exclusive. */
const lastDay = (iso: string) => fmtDay(new Date(new Date(iso).getTime() - 1).toISOString().slice(0, 10));
const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

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

const OWNER_STATUSES: Array<OwnerStatus> = ['active', 'restricted', 'suspended'];
const OWNER_LABEL: Record<OwnerStatus, MessageKey> = {
  active: 'admin.active',
  restricted: 'admin.restricted',
  suspended: 'admin.suspended',
};
const OWNER_PILL: Record<OwnerStatus, string> = { active: 'ok', restricted: 'warn', suspended: 'bad' };

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

const GRANT_KINDS: Array<GrantKind> = ['extra_allowance', 'discount_pct', 'waive_overage', 'extend_grace', 'dispute'];
const GRANT_LABEL: Record<GrantKind, MessageKey> = {
  extra_allowance: 'admin.grantExtraAllowance',
  discount_pct: 'admin.grantDiscount',
  waive_overage: 'admin.grantWaiveOverage',
  extend_grace: 'admin.grantExtendGrace',
  dispute: 'admin.grantDispute',
};
/** What `value` means for each kind (how it reads, and its field's label); none for kinds without a number. */
const GRANT_VALUE: Partial<Record<GrantKind, [MessageKey, MessageKey]>> = {
  extra_allowance: ['admin.grantValueCustomers', 'admin.grantFieldCustomers'],
  discount_pct: ['admin.grantValuePercent', 'admin.grantFieldPercent'],
  extend_grace: ['admin.grantValueDays', 'admin.grantFieldDays'],
};

const EVENT_LABEL: Record<AdminAuditEvent['kind'], MessageKey> = {
  created: 'admin.evCreated',
  activated: 'admin.evActivated',
  login: 'admin.evLogin',
  login_denied: 'admin.evLoginDenied',
  expired: 'admin.evExpired',
  blocked: 'admin.evBlocked',
  action: 'admin.evAction',
};

type PlanCode = 'starter' | 'growth' | 'enterprise' | 'custom';
type Tab = 'owners' | 'plans' | 'policy' | 'audit';
const TABS: Array<[Tab, MessageKey]> = [
  ['owners', 'admin.tabOwners'],
  ['plans', 'admin.tabPlans'],
  ['policy', 'admin.tabPolicy'],
  ['audit', 'admin.tabAudit'],
];

function lineText(line: PlanLine): string {
  const d = line.detail;
  switch (line.kind) {
    case 'base':
      return d.prorated
        ? t('billing.lineBaseProrated', { plan: String(d.plan), from: day(String(d.from)), until: lastDay(String(d.until)) })
        : t('billing.lineBase', { plan: String(d.plan) });
    case 'overage':
      return t('billing.lineOverage', { count: line.quantity, allowance: String(d.allowance), price: fmtMoney(line.unitPrice ?? '0') });
    case 'cap':
      return t('billing.lineCap', { cap: fmtMoney(String(d.cap)) });
    case 'discount':
      return t('billing.lineDiscount', { percent: String(d.percent) });
    default:
      return t('billing.lineCredit');
  }
}

const usage = (used: number, allowance: number | null) =>
  allowance === null ? fmtNumber(used) : `${fmtNumber(used)} / ${fmtNumber(allowance)}`;

// ------------------------------------------------------------------ page --

function AdminPage() {
  const me = useQuery(adminViewerQuery);
  // Set when the window closed while the page was open, so the sign-in form says why.
  const [ended, setEnded] = createSignal(false, { name: 'adminWindowEnded' });
  return (
    <div class="admin-shell">
      <header class="topbar admin-top">
        <span class="brand">
          <Mark />
        </span>
        <strong class="admin-title">{t('admin.consoleName')}</strong>
        <span class="spacer" />
        <Loading fallback={null}>
          <Show when={me.data}>{(viewer) => <WindowClock viewer={viewer()} onEnded={() => setEnded(true)} />}</Show>
        </Loading>
        <LanguageSwitch />
      </header>
      <Errored fallback={(error) => <div class="page"><Boundary error={error()} /></div>}>
        <Loading fallback={<div class="page"><Skeleton rows={4} height={88} /></div>}>
          <Show when={me.data} fallback={<SignIn ended={ended()} />}>
            <Console />
          </Show>
        </Loading>
      </Errored>
      <Toaster />
    </div>
  );
}

/** What's left of the access window, ticking; at zero the console signs out. */
function WindowClock(props: { viewer: AdminViewer; onEnded: () => void }) {
  // The window as it stood when the page loaded; the clock runs on from there.
  const loadedAt = Date.now();
  const left = () => Math.max(0, props.viewer.remainingSeconds - Math.round((Date.now() - loadedAt) / 1000));
  const [seconds, setSeconds] = createSignal(left(), { name: 'adminWindowLeft' });
  const out = useMutation(() => ({ mutationFn: () => adminSignOut() }));
  onSettled(() => {
    const id = setInterval(() => {
      setSeconds(left());
      if (left() === 0) {
        clearInterval(id);
        props.onEnded();
        out.mutate();
      }
    }, 1000);
    return () => clearInterval(id);
  });
  return (
    <div class="row start admin-window">
      <span class={['pill', seconds() <= 60 ? 'bad' : 'warn']} title={t('admin.windowHint')} role="timer">
        <Icon name="shield" size={12} /> {t('admin.windowLeft', { time: clock(seconds()) })}
      </span>
      <span class="muted">{props.viewer.name}</span>
      <button type="button" class="btn small ghost" disabled={out.isPending} onClick={() => out.mutate()}>
        <Icon name="logout" size={14} /> {t('admin.signOut')}
      </button>
    </div>
  );
}

/** Admin accounts are separate from workspace accounts; only an open window lets one in. */
function SignIn(props: { ended: boolean }) {
  const enter = useMutation(() => ({
    mutationFn: (input: { email: string; password: string }) => adminSignIn(input),
  }));
  return (
    <main class="gateway">
      <section class="gateway-card narrow-form">
        <p class="eyebrow">{t('admin.eyebrow')}</p>
        <h1>{t('admin.signInTitle')}</h1>
        <Show when={props.ended}>
          <p class="notice banner" role="status">
            {t('admin.windowEnded')}
          </p>
        </Show>
        <form
          class="form"
          onSubmit={(event) => {
            event.preventDefault();
            const d = new FormData(event.currentTarget);
            enter.mutate({ email: String(d.get('email')), password: String(d.get('password')) });
          }}
        >
          <label>
            <span class="form-label">{t('gateway.email')}</span>
            <input type="email" name="email" autocomplete="username" required />
          </label>
          <label>
            <span class="form-label">{t('gateway.password')}</span>
            <input type="password" name="password" autocomplete="current-password" required />
          </label>
          <Show when={enter.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
          <button type="submit" class="btn" disabled={enter.isPending}>
            {t('admin.signIn')}
          </button>
        </form>
        <p class="muted hint">{t('admin.signInHint')}</p>
      </section>
    </main>
  );
}

function Console() {
  // Tabs, search and paging stay in local state (see docs/ARCHITECTURE.md, known limits).
  const [tab, setTab] = createSignal<Tab>('owners', { name: 'adminTab' });
  return (
    <div class="page">
      <PageHead eyebrow={t('admin.eyebrow')} title={t('admin.title')} lede={t('admin.lede')} />
      <div class="segmented" role="tablist">
        <For each={TABS}>
          {([key, label]) => (
            <button type="button" role="tab" aria-selected={tab() === key ? 'true' : 'false'} onClick={() => setTab(key)}>
              {t(label)}
            </button>
          )}
        </For>
      </div>
      <Errored fallback={(error) => <Panel><Boundary error={error()} /></Panel>}>
        <Loading fallback={<Panel><Skeleton rows={5} height={40} /></Panel>}>
          <Show when={tab() === 'owners'}>
            <OwnersTab />
          </Show>
          <Show when={tab() === 'plans'}>
            <PlansTab />
          </Show>
          <Show when={tab() === 'policy'}>
            <PolicyTab />
          </Show>
          <Show when={tab() === 'audit'}>
            <AuditTab />
          </Show>
        </Loading>
      </Errored>
    </div>
  );
}

// ---------------------------------------------------------------- owners --

function OwnersTab() {
  const [q, setQ] = createSignal('', { name: 'adminQuery' });
  const [offset, setOffset] = createSignal(0, { name: 'adminOffset' });
  const [picked, setPicked] = createSignal<AdminBusiness | null>(null, { name: 'adminBusiness' });
  const [creating, setCreating] = createSignal(false, { name: 'creatingOwner' });

  return (
    <>
      <Show when={creating()}>
        <NewOwner onClose={() => setCreating(false)} />
      </Show>
      <Panel>
        <form
          class="toolbar"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            setOffset(0);
            setQ(String(new FormData(event.currentTarget).get('q') ?? '').trim());
          }}
        >
          <label class="filter">
            <Icon name="search" size={15} />
            <input type="search" name="q" value={q()} placeholder={t('admin.searchPlaceholder')} aria-label={t('admin.searchLabel')} />
          </label>
          <button type="submit" class="btn ghost">
            {t('admin.search')}
          </button>
          <Show when={!creating()}>
            <button type="button" class="btn" onClick={() => setCreating(true)}>
              <Icon name="plus" size={16} /> {t('admin.newOwner')}
            </button>
          </Show>
        </form>
        <Loading fallback={<Skeleton rows={5} height={40} />}>
          <Owners q={q()} offset={offset()} picked={picked()?.id ?? null} onPage={setOffset} onPick={setPicked} />
        </Loading>
      </Panel>

      <Show when={picked()}>
        {(business) => (
          <Errored fallback={(error) => <Panel><Boundary error={error()} /></Panel>}>
            <Loading fallback={<Panel><Skeleton rows={4} height={56} /></Panel>}>
              <Subscription business={business()} onClose={() => setPicked(null)} />
            </Loading>
          </Errored>
        )}
      </Show>
    </>
  );
}

function Owners(props: {
  q: string;
  offset: number;
  picked: string | null;
  onPage: (offset: number) => void;
  onPick: (business: AdminBusiness) => void;
}) {
  const owners = useQuery(() => adminOwnersQuery(props.q, props.offset));
  const [open, setOpen] = createSignal<string | null>(null, { name: 'adminOwnerOpen' });
  const data = () => owners.data;
  const last = () => Math.min(data().offset + data().limit, data().total);

  return (
    <>
      <Show when={!data().billingAvailable}>
        <p class="notice banner" role="status">
          {t('admin.billingDown')}
        </p>
      </Show>
      <Show when={data().owners.length} fallback={<p class="muted empty">{props.q ? t('admin.noMatches') : t('admin.noOwners')}</p>}>
        <div class="table-wrap">
          <table class="table admin-owners">
            <thead>
              <tr>
                <th>{t('admin.colName')}</th>
                <th>{t('admin.colEmail')}</th>
                <th>{t('admin.colJoined')}</th>
                <th>{t('admin.colStatus')}</th>
                <th class="num">{t('admin.colBusinesses')}</th>
              </tr>
            </thead>
            <tbody>
              <For each={data().owners}>
                {(owner) => (
                  <>
                    <tr class={['clickable', { picked: open() === owner.id }]} onClick={() => setOpen(open() === owner.id ? null : owner.id)}>
                      <td>
                        <button
                          type="button"
                          class="link-btn"
                          aria-expanded={open() === owner.id ? 'true' : 'false'}
                          onClick={(event) => {
                            event.stopPropagation();
                            setOpen(open() === owner.id ? null : owner.id);
                          }}
                        >
                          <Icon name="chevron" size={12} /> <strong>{owner.name}</strong>
                        </button>
                      </td>
                      <td class="mono">{owner.email}</td>
                      <td class="nowrap">{day(owner.createdAt)}</td>
                      <td>
                        <span class={['pill', OWNER_PILL[owner.status]]}>{t(OWNER_LABEL[owner.status])}</span>
                      </td>
                      <td class="num mono">{fmtNumber(owner.businesses.length)}</td>
                    </tr>
                    <Show when={open() === owner.id}>
                      <tr class="admin-expand">
                        <td colspan={5}>
                          <OwnerStatusForm owner={owner} />
                          <Businesses owner={owner} picked={props.picked} onPick={props.onPick} />
                          <AddBusiness owner={owner} />
                        </td>
                      </tr>
                    </Show>
                  </>
                )}
              </For>
            </tbody>
          </table>
        </div>
        <div class="row admin-pager">
          <span class="muted">{t('admin.showing', { from: data().offset + 1, to: last(), total: data().total })}</span>
          <div class="row start">
            <button
              type="button"
              class="btn small ghost"
              disabled={data().offset === 0}
              onClick={() => props.onPage(Math.max(0, data().offset - data().limit))}
            >
              {t('admin.previous')}
            </button>
            <button
              type="button"
              class="btn small ghost"
              disabled={last() >= data().total}
              onClick={() => props.onPage(data().offset + data().limit)}
            >
              {t('admin.next')}
            </button>
          </div>
        </div>
      </Show>
    </>
  );
}

const STARTING_PLANS: Array<[StartingPlan, MessageKey]> = [
  ['starter', 'admin.planStarter'],
  ['growth', 'admin.planGrowth'],
  ['enterprise', 'admin.planEnterprise'],
];

function businessOf(d: FormData): NewBusiness {
  return {
    name: String(d.get('businessName') ?? '').trim(),
    industry: String(d.get('industry') ?? '').trim(),
    locationName: String(d.get('locationName') ?? '').trim(),
    currency: String(d.get('currency') ?? 'USD').trim().toUpperCase() || 'USD',
  };
}

/** A business's name, first location, currency and starting plan; Custom terms are set on its subscription after. */
function BusinessFields() {
  return (
    <>
      <div class="form-row">
        <label>
          <span class="form-label">{t('admin.businessName')}</span>
          <input type="text" name="businessName" required minlength="2" maxlength="120" />
        </label>
        <label>
          <span class="form-label">{t('admin.industry')}</span>
          <input type="text" name="industry" maxlength="160" />
        </label>
      </div>
      <div class="form-row">
        <label>
          <span class="form-label">{t('admin.firstLocation')}</span>
          <input type="text" name="locationName" required minlength="2" maxlength="120" />
        </label>
        <label>
          <span class="form-label">{t('admin.currency')}</span>
          <input type="text" name="currency" value="USD" required minlength="3" maxlength="3" class="mono" />
        </label>
        <label>
          <span class="form-label">{t('admin.startingPlan')}</span>
          <select name="plan">
            <For each={STARTING_PLANS}>{([code, label]) => <option value={code}>{t(label)}</option>}</For>
          </select>
        </label>
      </div>
      <label>
        <span class="form-label">{t('admin.reason')}</span>
        <input type="text" name="reason" required maxlength="200" placeholder={t('admin.createReasonPlaceholder')} />
      </label>
    </>
  );
}

/**
 * The only way a business owner gets an account: an admin creates it with their first business
 * and the plan it starts on, and hands them the first password. Their team's accounts are theirs to create.
 */
function NewOwner(props: { onClose: () => void }) {
  const create = useMutation(() => ({
    mutationFn: (input: Parameters<typeof createOwner>[0]) =>
      createOwner(input) as unknown as Promise<{ name: string; business: { name: string; billingPending: boolean } }>,
    onSuccess: (owner) => {
      notify(t('admin.toastOwnerCreated', { name: owner.name, business: owner.business.name }));
      if (owner.business.billingPending) notify(t('admin.toastBillingPending'));
      props.onClose();
    },
  }));
  return (
    <Panel title={t('admin.newOwnerTitle')} icon="users">
      <form
        class="form admin-form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          create.mutate({
            name: String(d.get('name') ?? '').trim(),
            email: String(d.get('email') ?? '').trim(),
            password: String(d.get('password') ?? ''),
            business: businessOf(d),
            plan: String(d.get('plan')) as StartingPlan,
            reason: String(d.get('reason') ?? '').trim(),
          });
        }}
      >
        <div class="form-row">
          <label>
            <span class="form-label">{t('admin.ownerName')}</span>
            <input type="text" name="name" required minlength="2" maxlength="120" autocomplete="off" />
          </label>
          <label>
            <span class="form-label">{t('admin.ownerEmail')}</span>
            <input type="email" name="email" required maxlength="254" autocomplete="off" />
          </label>
          <label>
            <span class="form-label">{t('admin.firstPassword')}</span>
            <input type="password" name="password" required minlength="8" maxlength="200" autocomplete="new-password" />
          </label>
        </div>
        <span class="muted hint">{t('admin.newOwnerHint')}</span>
        <BusinessFields />
        <Show when={create.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <div class="row start">
          <button type="submit" class="btn" disabled={create.isPending}>
            {t('admin.createOwner')}
          </button>
          <button type="button" class="btn ghost" onClick={() => props.onClose()}>
            {t('admin.cancel')}
          </button>
        </div>
      </form>
    </Panel>
  );
}

/** Another business for this owner, on a subscription of its own. */
function AddBusiness(props: { owner: AdminOwner }) {
  const [open, setOpen] = createSignal(false, { name: 'addingBusiness' });
  const add = useMutation(() => ({
    mutationFn: (input: { business: NewBusiness; plan: StartingPlan; reason: string }) =>
      addBusiness({ userId: props.owner.id, ...input }) as unknown as Promise<{ name: string; billingPending: boolean }>,
    onSuccess: (business) => {
      notify(t('admin.toastBusinessAdded', { name: props.owner.name, business: business.name }));
      if (business.billingPending) notify(t('admin.toastBillingPending'));
      setOpen(false);
    },
  }));
  return (
    <Show
      when={open()}
      fallback={
        <button type="button" class="btn small ghost" disabled={props.owner.status !== 'active'} onClick={() => setOpen(true)}>
          <Icon name="plus" size={14} /> {t('admin.addBusiness')}
        </button>
      }
    >
      <form
        class="form admin-form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          add.mutate({ business: businessOf(d), plan: String(d.get('plan')) as StartingPlan, reason: String(d.get('reason') ?? '').trim() });
        }}
      >
        <h3 class="subhead">{t('admin.addBusinessTitle', { name: props.owner.name })}</h3>
        <BusinessFields />
        <Show when={add.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <div class="row start">
          <button type="submit" class="btn small" disabled={add.isPending}>
            {t('admin.addBusiness')}
          </button>
          <button type="button" class="btn small ghost" onClick={() => setOpen(false)}>
            {t('admin.cancel')}
          </button>
        </div>
      </form>
    </Show>
  );
}

/** Active, restricted (read-only) or suspended (signed out); always with a reason, kept in the log. */
function OwnerStatusForm(props: { owner: AdminOwner }) {
  const stored = () => props.owner.status;
  const [status, setStatus] = createSignal<OwnerStatus>(stored(), { name: 'ownerStatus' });
  const [reason, setReason] = createSignal('', { name: 'ownerReason' });
  const apply = useMutation(() => ({
    mutationFn: () => setOwnerStatus({ userId: props.owner.id, status: status(), reason: reason().trim() }),
    onSuccess: () => {
      setReason('');
      notify(t('admin.toastStatus', { name: props.owner.name, status: t(OWNER_LABEL[status()]) }));
    },
  }));
  return (
    <form
      class="row start admin-inline admin-status"
      onSubmit={(event) => {
        event.preventDefault();
      }}
    >
      <label>
        <span class="form-label">{t('admin.ownerStatus')}</span>
        <select value={status()} onChange={(event) => setStatus(event.currentTarget.value as OwnerStatus)}>
          <For each={OWNER_STATUSES}>{(s) => <option value={s}>{t(OWNER_LABEL[s])}</option>}</For>
        </select>
      </label>
      <label class="grow">
        <span class="form-label">{t('admin.reason')}</span>
        <input
          type="text"
          required
          maxlength={200}
          placeholder={t('admin.statusReasonPlaceholder')}
          value={reason()}
          onInput={(event) => setReason(event.currentTarget.value)}
        />
      </label>
      <ConfirmButton
        class="small"
        label={t('admin.applyStatus')}
        confirm={t(status() === 'active' ? 'admin.reactivateConfirm' : status() === 'restricted' ? 'admin.restrictConfirm' : 'admin.suspendConfirm')}
        disabled={apply.isPending || status() === props.owner.status || !reason().trim()}
        onConfirm={() => apply.mutate()}
      />
      <Show when={apply.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      <span class="muted hint block">{t('admin.statusHint')}</span>
    </form>
  );
}

function Businesses(props: { owner: AdminOwner; picked: string | null; onPick: (business: AdminBusiness) => void }) {
  return (
    <Show when={props.owner.businesses.length} fallback={<p class="muted">{t('admin.noBusinesses')}</p>}>
      <table class="table admin-businesses">
        <thead>
          <tr>
            <th>{t('admin.colBusiness')}</th>
            <th>{t('admin.colPlan')}</th>
            <th>{t('admin.colStanding')}</th>
            <th class="num">{t('admin.colUsage')}</th>
            <th class="num">{t('admin.colBalance')}</th>
            <th class="num">{t('admin.colMembers')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <For each={props.owner.businesses}>
            {(business) => (
              <tr class={{ picked: props.picked === business.id }}>
                <td>
                  <strong>{business.name}</strong> <span class="muted mono">{business.slug}</span>
                  <span class="muted block">{t('admin.since', { date: day(business.createdAt) })}</span>
                </td>
                <Show
                  when={business.billing}
                  fallback={
                    <td colspan={3} class="muted">
                      {t('admin.noBilling')}
                    </td>
                  }
                >
                  {(b) => (
                    <>
                      <td>
                        {b().plan} <span class="muted mono">{fmtMoney(b().price, b().currency)}</span>
                      </td>
                      <td>
                        <span class={['pill', STANDING_PILL[b().status]]}>{t(STANDING_LABEL[b().status])}</span>
                      </td>
                      <td class="num mono">{usage(b().used, b().allowance)}</td>
                    </>
                  )}
                </Show>
                <td class="num mono">{business.billing ? fmtMoney(business.billing.openBalance, business.billing.currency) : '—'}</td>
                <td class="num mono">{fmtNumber(business.members)}</td>
                <td class="row-actions">
                  <button type="button" class="btn small ghost" onClick={() => props.onPick(business)}>
                    {t('admin.openSubscription')}
                  </button>
                </td>
              </tr>
            )}
          </For>
        </tbody>
      </table>
    </Show>
  );
}

// ----------------------------------------------------------------- plans --

function PlansTab() {
  const plans = useQuery(adminPlansQuery);
  const [editing, setEditing] = createSignal<string | null>(null, { name: 'repricing' });
  const money = (amount: string | null, currency: string) => (amount === null ? '—' : fmtMoney(amount, currency));
  return (
    <Panel title={t('admin.plansTitle')} icon="billing">
      <p class="muted">{t('admin.plansLede', { count: plans.data.customSubscribers })}</p>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>{t('admin.colPlan')}</th>
              <th class="num">{t('admin.colPrice')}</th>
              <th class="num">{t('admin.colIncluded')}</th>
              <th class="num">{t('admin.colOverage')}</th>
              <th class="num">{t('admin.colCap')}</th>
              <th class="num">{t('admin.colSubscribers')}</th>
              <th class="num">{t('admin.colUsageNow')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <For each={plans.data.plans}>
              {(p) => (
                <>
                  <tr>
                    <td>
                      <strong>{p.name}</strong> <span class="muted mono">v{p.version}</span>{' '}
                      <span class={['pill', p.status === 'active' ? 'ok' : 'neutral']}>
                        {p.status === 'active' ? t('admin.onSale') : t('admin.legacy')}
                      </span>
                      <span class="muted block">{t('admin.since', { date: day(p.effectiveFrom) })}</span>
                    </td>
                    <td class="num mono">{money(p.price, p.currency)}</td>
                    <td class="num mono">{p.included === null ? '∞' : fmtNumber(p.included)}</td>
                    <td class="num mono">{money(p.overagePrice, p.currency)}</td>
                    <td class="num mono">{money(p.cap, p.currency)}</td>
                    <td class="num mono">
                      {fmtNumber(p.subscribers)}
                      <Show when={p.scheduledIn}>
                        <span class="muted block">{t('admin.movingIn', { count: p.scheduledIn })}</span>
                      </Show>
                    </td>
                    <td class="num mono">
                      {fmtNumber(p.usage.used)}
                      <Show when={p.usage.over}>
                        <span class="muted block">{t('admin.overAllowance', { count: p.usage.over })}</span>
                      </Show>
                    </td>
                    <td class="row-actions">
                      <Show when={p.status === 'active'}>
                        <button type="button" class="btn small ghost" onClick={() => setEditing(editing() === p.id ? null : p.id)}>
                          {t('admin.changePrice')}
                        </button>
                      </Show>
                    </td>
                  </tr>
                  <Show when={editing() === p.id}>
                    <tr class="admin-expand">
                      <td colspan={8}>
                        <Reprice plan={p} onDone={() => setEditing(null)} />
                      </td>
                    </tr>
                  </Show>
                </>
              )}
            </For>
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/** A new price list for the plan: published as its next version; nothing already invoiced changes. */
function Reprice(props: { plan: AdminPlan; onDone: () => void }) {
  // The form starts from the price list on sale.
  const was = () => props.plan;
  const [price, setPrice] = createSignal(was().price, { name: 'newPrice' });
  const [included, setIncluded] = createSignal(was().included === null ? '' : String(was().included), { name: 'newIncluded' });
  const [overage, setOverage] = createSignal(was().overagePrice ?? '', { name: 'newOverage' });
  const [cap, setCap] = createSignal(was().cap ?? '', { name: 'newCap' });
  const [reason, setReason] = createSignal('', { name: 'repriceReason' });
  const save = useMutation(() => ({
    mutationFn: () =>
      repricePlan({
        versionId: props.plan.id,
        price: price().trim(),
        included: included().trim() ? Number(included()) : null,
        overagePrice: included().trim() && overage().trim() ? overage().trim() : null,
        cap: cap().trim() || null,
        reason: reason().trim(),
      }),
    onSuccess: () => {
      notify(t('admin.toastRepriced', { plan: props.plan.name }));
      props.onDone();
    },
  }));
  return (
    <div class="form admin-form">
      <div class="form-row">
        <label>
          <span class="form-label">{t('admin.colPrice')}</span>
          <input type="number" min="0" step="0.01" required value={price()} onInput={(event) => setPrice(event.currentTarget.value)} />
        </label>
        <label>
          <span class="form-label">{t('admin.colIncluded')}</span>
          <input
            type="number"
            min="1"
            step="1"
            placeholder={t('admin.customNoLimit')}
            value={included()}
            onInput={(event) => setIncluded(event.currentTarget.value)}
          />
        </label>
        <label>
          <span class="form-label">{t('admin.colOverage')}</span>
          <input
            type="number"
            min="0"
            step="0.01"
            placeholder={t('admin.customNoOverage')}
            disabled={!included().trim()}
            value={overage()}
            onInput={(event) => setOverage(event.currentTarget.value)}
          />
        </label>
        <label>
          <span class="form-label">{t('admin.colCap')}</span>
          <input type="number" min="0" step="0.01" placeholder={t('admin.noCap')} value={cap()} onInput={(event) => setCap(event.currentTarget.value)} />
        </label>
      </div>
      <label>
        <span class="form-label">{t('admin.reason')}</span>
        <input
          type="text"
          required
          maxlength={200}
          placeholder={t('admin.repriceReasonPlaceholder')}
          value={reason()}
          onInput={(event) => setReason(event.currentTarget.value)}
        />
        <span class="muted hint">{t('admin.repriceHint', { count: props.plan.subscribers + props.plan.scheduledIn })}</span>
      </label>
      <Show when={save.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      <div class="row start">
        <ConfirmButton
          class="small"
          label={t('admin.publishPrice')}
          confirm={t('admin.publishPriceConfirm')}
          disabled={save.isPending || !reason().trim() || !price().trim()}
          onConfirm={() => save.mutate()}
        />
        <button type="button" class="btn small ghost" onClick={() => props.onDone()}>
          {t('admin.cancel')}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- policy --

const POLICY_DAYS: Array<[keyof PolicyFields, MessageKey]> = [
  ['limitAfterDays', 'admin.polLimit'],
  ['restrictAfterDays', 'admin.polRestrict'],
  ['cancelAfterDays', 'admin.polCancel'],
  ['paymentTermsDays', 'admin.polTerms'],
  ['extensionDays', 'admin.polExtension'],
  ['extensionEveryDays', 'admin.polExtensionEvery'],
  ['retentionDays', 'admin.polRetention'],
  ['usageGraceHours', 'admin.polGrace'],
];

function PolicyTab() {
  const policy = useQuery(adminPolicyQuery);
  const current = () => policy.data.current;
  let form: HTMLFormElement | undefined;
  const save = useMutation(() => ({
    mutationFn: (input: PolicyFields & { reason: string }) => editPolicy(input),
    onSuccess: () => {
      form?.reset();
      notify(t('admin.toastPolicy'));
    },
  }));
  return (
    <>
      <Panel title={t('admin.policyTitle', { version: current().version })} icon="config">
        <p class="muted">
          {t('admin.policyLede', { by: current().editedBy, date: current().effectiveAt ? day(current().effectiveAt!) : '—' })}
        </p>
        <form
          class="form admin-form"
          onSubmit={(event) => {
            event.preventDefault();
            form = event.currentTarget;
            const d = new FormData(form);
            const num = (key: string) => Number(d.get(key) ?? 0);
            save.mutate({
              limitAfterDays: num('limitAfterDays'),
              restrictAfterDays: num('restrictAfterDays'),
              cancelAfterDays: num('cancelAfterDays'),
              paymentTermsDays: num('paymentTermsDays'),
              extensionDays: num('extensionDays'),
              extensionEveryDays: num('extensionEveryDays'),
              retentionDays: num('retentionDays'),
              usageGraceHours: num('usageGraceHours'),
              smallBalance: String(d.get('smallBalance') ?? '0'),
              spendCapMultiple: String(d.get('spendCapMultiple') ?? '2'),
              alertThresholds: String(d.get('alertThresholds') ?? '')
                .split(',')
                .map((v) => Number(v.trim()))
                .filter((v) => Number.isFinite(v) && v > 0),
              reason: String(d.get('reason') ?? '').trim(),
            });
          }}
        >
          <div class="form-row admin-policy">
            <For each={POLICY_DAYS}>
              {([key, label]) => (
                <label>
                  <span class="form-label">{t(label)}</span>
                  <input type="number" name={key} min="0" step="1" required value={String(current()[key])} />
                </label>
              )}
            </For>
            <label>
              <span class="form-label">{t('admin.polSmallBalance')}</span>
              <input type="number" name="smallBalance" min="0" step="0.01" required value={current().smallBalance} />
            </label>
            <label>
              <span class="form-label">{t('admin.polSpendCap')}</span>
              <input type="number" name="spendCapMultiple" min="1" max="10" step="0.01" required value={current().spendCapMultiple} />
            </label>
            <label>
              <span class="form-label">{t('admin.polAlerts')}</span>
              <input type="text" name="alertThresholds" required pattern="[0-9, ]+" value={current().alertThresholds.join(', ')} />
            </label>
          </div>
          <label>
            <span class="form-label">{t('admin.reason')}</span>
            <input type="text" name="reason" required maxlength={200} placeholder={t('admin.policyReasonPlaceholder')} />
            <span class="muted hint">{t('admin.policyHint')}</span>
          </label>
          <Show when={save.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
          <div class="row start">
            <button type="submit" class="btn small" disabled={save.isPending}>
              {t('admin.savePolicy')}
            </button>
          </div>
        </form>
      </Panel>
      <Panel title={t('admin.policyHistory')}>
        <ul class="change-list">
          <For each={policy.data.history}>
            {(p) => (
              <li>
                <span>
                  <strong>v{p.version}</strong> {policySummary(p)}
                  <span class="muted block">
                    {p.reason} · {t('billing.changeBy', { name: p.editedBy })}
                  </span>
                </span>
                <span class="muted nowrap">{p.effectiveAt ? day(p.effectiveAt) : '—'}</span>
              </li>
            )}
          </For>
        </ul>
      </Panel>
    </>
  );
}

const policySummary = (p: BillingPolicy) =>
  t('admin.policySummary', {
    limit: p.limitAfterDays,
    restrict: p.restrictAfterDays,
    cancel: p.cancelAfterDays,
    terms: p.paymentTermsDays,
    retention: p.retentionDays,
  });

// ----------------------------------------------------------------- audit --

function AuditTab() {
  const [offset, setOffset] = createSignal(0, { name: 'auditOffset' });
  const log = useQuery(() => adminAuditQuery(offset()));
  const data = () => log.data;
  const last = () => Math.min(data().offset + data().limit, data().total);
  const show = (value: unknown) => (value === null || value === undefined ? '—' : JSON.stringify(value));
  return (
    <Panel title={t('admin.auditTitle')} icon="audit">
      <p class="muted">{t('admin.auditLede')}</p>
      <div class="table-wrap">
        <table class="table admin-audit">
          <thead>
            <tr>
              <th>{t('admin.colWhen')}</th>
              <th>{t('admin.colAdmin')}</th>
              <th>{t('admin.colEvent')}</th>
              <th>{t('admin.colTarget')}</th>
              <th>{t('admin.colChange')}</th>
              <th>{t('admin.colIp')}</th>
            </tr>
          </thead>
          <tbody>
            <For each={data().events}>
              {(e) => (
                <tr>
                  <td class="nowrap">{fmtStamp(e.at)}</td>
                  <td>{e.admin ? e.admin.name : <span class="muted">{t('admin.unknownAdmin')}</span>}</td>
                  <td>
                    <span class={['pill', e.kind === 'login_denied' || e.kind === 'expired' || e.kind === 'blocked' ? 'warn' : 'neutral']}>
                      {t(EVENT_LABEL[e.kind])}
                    </span>{' '}
                    <span class="mono">{e.action}</span>
                  </td>
                  <td class="mono">{e.targetType ? `${e.targetType} ${e.targetId}` : '—'}</td>
                  <td class="mono admin-diff">
                    <span class="muted">{show(e.before)}</span> → {show(e.after)}
                  </td>
                  <td class="mono">{e.ip || '—'}</td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
      </div>
      <div class="row admin-pager">
        <span class="muted">{t('admin.showing', { from: data().total ? data().offset + 1 : 0, to: last(), total: data().total })}</span>
        <div class="row start">
          <button type="button" class="btn small ghost" disabled={data().offset === 0} onClick={() => setOffset(Math.max(0, data().offset - data().limit))}>
            {t('admin.previous')}
          </button>
          <button type="button" class="btn small ghost" disabled={last() >= data().total} onClick={() => setOffset(data().offset + data().limit)}>
            {t('admin.next')}
          </button>
        </div>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------- subscription --

function Subscription(props: { business: AdminBusiness; onClose: () => void }) {
  const detail = useQuery(() => adminSubscriptionQuery(props.business.id));
  const s = () => detail.data;
  const money = (amount: string | null | undefined) => fmtMoney(amount ?? '0', s().currency);

  return (
    <Panel
      title={t('admin.subscriptionTitle', { name: props.business.name })}
      icon="billing"
      aside={
        <button type="button" class="icon-btn" aria-label={t('admin.close')} title={t('admin.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      }
    >
      <div class="stats">
        <Stat
          label={t('admin.statPlan')}
          value={s().plan.name}
          foot={
            s().scheduled
              ? t('admin.footScheduled', { plan: s().scheduled!.name })
              : t('admin.footPrice', { price: money(s().plan.price) })
          }
        />
        <Stat
          label={t('admin.statStanding')}
          value={<span class={['pill', STANDING_PILL[s().standing.status]]}>{t(STANDING_LABEL[s().standing.status])}</span>}
          foot={
            s().standing.overdueDays
              ? t('admin.footOverdue', { count: s().standing.overdueDays, balance: money(s().standing.balance) })
              : s().cancelAtPeriodEnd
                ? t('admin.footEnding')
                : s().paymentMethod === 'stripe'
                  ? t('admin.footCard')
                  : t('admin.footTransfer')
          }
        />
        <Stat
          label={t('admin.statUsage')}
          value={usage(s().usage.used, s().usage.allowance)}
          foot={
            s().usage.projected !== null
              ? t('admin.footProjected', { count: fmtNumber(s().usage.projected!) })
              : s().period
                ? t('admin.footPeriod', { from: day(s().period!.start), to: lastDay(s().period!.end) })
                : undefined
          }
        />
        <Stat
          label={t('admin.statEstimate')}
          value={s().estimate ? money(s().estimate!.total) : '—'}
          foot={s().estimate?.projectedTotal ? t('admin.footProjectedTotal', { total: money(s().estimate!.projectedTotal) }) : undefined}
        />
      </div>

      <Show when={s().estimate?.lines.length}>
        <div class="table-wrap">
          <table class="table">
            <tbody>
              <For each={s().estimate!.lines}>
                {(line) => (
                  <tr>
                    <td>{lineText(line)}</td>
                    <td class="num mono">{money(line.amount)}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Show>

      <Invoices invoices={s().invoices} />
      <Grants subscription={s()} />
      <ChangePlan subscription={s()} />

      <h3 class="subhead">{t('admin.changesTitle')}</h3>
      <Show when={s().changes.length} fallback={<p class="muted">{t('admin.noChanges')}</p>}>
        <ul class="change-list">
          <For each={s().changes}>
            {(c) => (
              <li>
                <span>
                  {CHANGE_LABEL[c.kind] ? t(CHANGE_LABEL[c.kind], { from: c.from ?? '', to: c.to ?? '' }) : c.kind}{' '}
                  <span class="muted">{t('billing.changeBy', { name: c.by })}</span>
                  <Show when={typeof c.detail.reason === 'string' && c.detail.reason}>
                    {(reason) => <span class="muted block">{String(reason())}</span>}
                  </Show>
                </span>
                <span class="muted nowrap">{day(c.at)}</span>
              </li>
            )}
          </For>
        </ul>
      </Show>
    </Panel>
  );
}

function Invoices(props: { invoices: Array<PlanInvoice> }) {
  return (
    <>
      <h3 class="subhead">{t('admin.invoicesTitle')}</h3>
      <Show when={props.invoices.length} fallback={<p class="muted">{t('admin.noInvoices')}</p>}>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{t('admin.colInvoice')}</th>
                <th>{t('admin.colPeriod')}</th>
                <th class="num">{t('admin.colTotal')}</th>
                <th>{t('admin.colStatus')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <For each={props.invoices}>{(invoice) => <InvoiceRow invoice={invoice} />}</For>
            </tbody>
          </table>
        </div>
      </Show>
    </>
  );
}

/** "Mark paid" asks for the payment's reference (bank transfer, cheque…) before it records anything. */
function InvoiceRow(props: { invoice: PlanInvoice }) {
  const [asking, setAsking] = createSignal(false, { name: 'askingReference' });
  const [reference, setReference] = createSignal('', { name: 'paymentReference' });
  const pay = useMutation(() => ({
    mutationFn: () => markInvoicePaid({ invoiceId: props.invoice.id, reference: reference().trim() }),
    onSuccess: () => {
      setAsking(false);
      notify(t('admin.toastPaid', { number: props.invoice.number }));
    },
  }));
  const inv = () => props.invoice;
  const status = () =>
    inv().status === 'paid'
      ? t('admin.invPaid', { date: inv().paidOn ? fmtDay(inv().paidOn!) : '', via: inv().paidVia ?? '' })
      : inv().status === 'void'
        ? t('admin.invVoid')
        : t('admin.invOpen', { date: fmtDay(inv().dueOn) });
  return (
    <tr>
      <td class="mono">{inv().number}</td>
      <td class="nowrap">
        {day(inv().periodStart)} – {lastDay(inv().periodEnd)}
      </td>
      <td class="num mono">{fmtMoney(inv().total, inv().currency)}</td>
      <td>
        <span class={['pill', inv().status === 'paid' ? 'ok' : inv().status === 'void' ? 'neutral' : 'warn']}>{status()}</span>
      </td>
      <td class="row-actions">
        <Show when={inv().status === 'open'}>
          <Show
            when={asking()}
            fallback={
              <button type="button" class="btn small ghost" onClick={() => setAsking(true)}>
                {t('admin.markPaid')}
              </button>
            }
          >
            <form
              class="row start admin-inline"
              onSubmit={(event) => {
                event.preventDefault();
                if (reference().trim()) pay.mutate();
              }}
            >
              <input
                type="text"
                required
                maxlength={120}
                placeholder={t('admin.referencePlaceholder')}
                aria-label={t('admin.reference')}
                value={reference()}
                onInput={(event) => setReference(event.currentTarget.value)}
              />
              <button type="submit" class="btn small" disabled={pay.isPending || !reference().trim()}>
                {t('admin.recordPayment')}
              </button>
              <button type="button" class="btn small ghost" onClick={() => setAsking(false)}>
                {t('admin.cancel')}
              </button>
            </form>
            <Show when={pay.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
          </Show>
        </Show>
      </td>
    </tr>
  );
}

function Grants(props: { subscription: AdminSubscription }) {
  const [kind, setKind] = createSignal<GrantKind>('extra_allowance', { name: 'grantKind' });
  let form: HTMLFormElement | undefined;
  const add = useMutation(() => ({
    mutationFn: (input: { value: string; days: number; reason: string }) =>
      addGrant({
        tenantId: props.subscription.tenantId,
        kind: kind(),
        ...(kind() === 'extra_allowance' ? { metric: 'active_customers' } : {}),
        ...input,
      }),
    onSuccess: () => {
      form?.reset();
      setKind('extra_allowance');
      notify(t('admin.toastGranted'));
    },
  }));
  const grantValue = (g: { kind: GrantKind; value: string }) =>
    GRANT_VALUE[g.kind] ? t(GRANT_VALUE[g.kind]![0], { value: g.value.replace(/\.00$/, '') }) : '';

  return (
    <>
      <h3 class="subhead">{t('admin.grantsTitle')}</h3>
      <Show when={props.subscription.grants.length} fallback={<p class="muted">{t('admin.noGrants')}</p>}>
        <ul class="change-list">
          <For each={props.subscription.grants}>
            {(g) => (
              <li>
                <span>
                  <strong>{t(GRANT_LABEL[g.kind])}</strong> {grantValue(g)}
                  <span class="muted block">
                    {g.reason} · {t('billing.changeBy', { name: g.approvedBy })}
                  </span>
                </span>
                <span class="muted nowrap">
                  {day(g.validFrom)} – {day(g.validUntil)}
                </span>
              </li>
            )}
          </For>
        </ul>
      </Show>
      <form
        class="form admin-form"
        onSubmit={(event) => {
          event.preventDefault();
          form = event.currentTarget;
          const d = new FormData(form);
          add.mutate({
            value: GRANT_VALUE[kind()] ? String(d.get('value') ?? '0') : '0',
            days: Number(d.get('days') ?? 31),
            reason: String(d.get('reason') ?? '').trim(),
          });
        }}
      >
        <div class="form-row">
          <label>
            <span class="form-label">{t('admin.grantKind')}</span>
            <select name="kind" value={kind()} onChange={(event) => setKind(event.currentTarget.value as GrantKind)}>
              <For each={GRANT_KINDS}>{(k) => <option value={k}>{t(GRANT_LABEL[k])}</option>}</For>
            </select>
          </label>
          <Show when={GRANT_VALUE[kind()]}>
            {(key) => (
              <label>
                <span class="form-label">{t(key()[1])}</span>
                <input type="number" name="value" min="0" step="1" required />
              </label>
            )}
          </Show>
          <label>
            <span class="form-label">{t('admin.grantDays')}</span>
            <input type="number" name="days" min="1" max="366" value="31" required />
          </label>
        </div>
        <label>
          <span class="form-label">{t('admin.reason')}</span>
          <input type="text" name="reason" required maxlength={200} placeholder={t('admin.grantReasonPlaceholder')} />
        </label>
        <Show when={add.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <div class="row start">
          <button type="submit" class="btn small" disabled={add.isPending}>
            <Icon name="plus" size={14} /> {t('admin.addGrant')}
          </button>
        </div>
      </form>
    </>
  );
}

/** A public tier, or Custom with its agreed price, included customers and overage; always with a reason. */
function ChangePlan(props: { subscription: AdminSubscription }) {
  const current = () => (props.subscription.plan.custom ? 'custom' : props.subscription.plan.code) as PlanCode;
  const [plan, setPlan] = createSignal<PlanCode>(current(), { name: 'adminPlan' });
  const [price, setPrice] = createSignal('', { name: 'customPrice' });
  const [included, setIncluded] = createSignal('', { name: 'customIncluded' });
  const [overage, setOverage] = createSignal('', { name: 'customOverage' });
  const [reason, setReason] = createSignal('', { name: 'planReason' });
  const change = useMutation(() => ({
    mutationFn: () =>
      assignPlan({
        tenantId: props.subscription.tenantId,
        plan: plan(),
        reason: reason().trim(),
        ...(plan() === 'custom'
          ? {
              terms: {
                price: price().trim(),
                ...(included().trim() ? { customerLimit: Number(included()) } : {}),
                ...(included().trim() && overage().trim() ? { overagePrice: overage().trim() } : {}),
              },
            }
          : {}),
      }),
    onSuccess: () => {
      setReason('');
      notify(t('admin.toastPlanChanged'));
    },
  }));
  const ready = () => reason().trim().length > 0 && (plan() !== 'custom' || price().trim().length > 0);

  return (
    <>
      <h3 class="subhead">{t('admin.changePlanTitle')}</h3>
      <div class="form admin-form">
        <div class="form-row">
          <label>
            <span class="form-label">{t('admin.plan')}</span>
            <select value={plan()} onChange={(event) => setPlan(event.currentTarget.value as PlanCode)}>
              <For each={props.subscription.plans}>
                {(p) => (
                  <option value={p.code}>
                    {t('admin.planOption', {
                      name: p.name,
                      price: fmtMoney(p.price, p.currency),
                      included: p.included === null ? '∞' : fmtNumber(p.included),
                    })}
                  </option>
                )}
              </For>
              <option value="custom">{t('admin.planCustom')}</option>
            </select>
          </label>
          <Show when={plan() === 'custom'}>
            <label>
              <span class="form-label">{t('admin.customPrice')}</span>
              <input type="number" min="0" step="0.01" required value={price()} onInput={(event) => setPrice(event.currentTarget.value)} />
            </label>
            <label>
              <span class="form-label">{t('admin.customIncluded')}</span>
              <input
                type="number"
                min="1"
                step="1"
                placeholder={t('admin.customNoLimit')}
                value={included()}
                onInput={(event) => setIncluded(event.currentTarget.value)}
              />
            </label>
            <label>
              <span class="form-label">{t('admin.customOverage')}</span>
              <input
                type="number"
                min="0"
                step="0.01"
                placeholder={t('admin.customNoOverage')}
                disabled={!included().trim()}
                value={overage()}
                onInput={(event) => setOverage(event.currentTarget.value)}
              />
            </label>
          </Show>
        </div>
        <label>
          <span class="form-label">{t('admin.reason')}</span>
          <input
            type="text"
            required
            maxlength={200}
            placeholder={t('admin.planReasonPlaceholder')}
            value={reason()}
            onInput={(event) => setReason(event.currentTarget.value)}
          />
          <span class="muted hint">{t('admin.planHint')}</span>
        </label>
        <Show when={change.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <div class="row start">
          <ConfirmButton
            class="small"
            label={t('admin.applyPlan')}
            confirm={t('admin.applyPlanConfirm')}
            disabled={change.isPending || !ready()}
            onConfirm={() => change.mutate()}
          />
        </div>
      </div>
    </>
  );
}

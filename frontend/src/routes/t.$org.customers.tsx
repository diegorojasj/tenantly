import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Loading, Show } from 'solid-js';

import FieldInput from '../components/FieldInput';
import Icon from '../components/Icon';
import { KindBadge, PageHead, Panel, Skeleton, Stat, StatusPill } from '../components/ui';
import { fieldsOf, readFields, showValue } from '../lib/fields';
import { fmtAgo, fmtMoney, sumMoney, toCents } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { cancelPlan, createCustomer, createSubject, recordDocument, sellPlan } from '../lib/ops';
import { accountsQuery, customerQuery, customersQuery, prefetch, tenantQuery } from '../lib/queries';
import { useCurrency, useTenantScope } from '../lib/scope';
import { notify } from '../lib/toast';
import type { Account, Customer, ScopeNode, Subject, Template } from '../lib/types';

// Customers — one job: know who you serve before you serve them. The list
// finds them; the profile shows what the template says matters (typed
// fields), their account, what is served for them (pets, vehicles…), their
// plans, documents on file, balance and history.
export const Route = createFileRoute('/t/$org/customers')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, customersQuery(params.org, deps.scope));
  },
  head: () => ({ meta: [{ title: tr('customers.pageTitle') }] }),
  component: CustomersPage,
});

type Filter = 'all' | 'plan' | 'balance' | 'docs';

const planText = (c: Customer) => c.subscriptions.map((p) => p.name).join(', ');

function CustomersPage() {
  const { org, scope } = useTenantScope();
  const search = Route.useSearch();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const customers = useQuery(() => customersQuery(org(), scope()));
  const t = () => ctx.data.tenant.template;
  const canManage = () => ctx.data.role.permissions.includes('bookings.manage');

  const [text, setText] = createSignal('', { name: 'customerText' });
  const [filter, setFilter] = createSignal<Filter>('all', { name: 'customerFilter' });
  const [adding, setAdding] = createSignal(false, { name: 'customerAdding' });

  const rows = createMemo(() => {
    const q = text().trim().toLowerCase();
    return customers.data.filter(
      (c) =>
        (filter() === 'all' ||
          (filter() === 'plan' && c.subscriptions.length) ||
          (filter() === 'balance' && toCents(c.balance) > 0) ||
          (filter() === 'docs' && c.missingDocuments.length)) &&
        (!q || `${c.name} ${c.phone} ${c.email} ${Object.values(c.fields).join(' ')}`.toLowerCase().includes(q)),
    );
  });
  const totals = createMemo(() => ({
    count: customers.data.length,
    plan: customers.data.filter((c) => c.subscriptions.length).length,
    balance: sumMoney(customers.data.map((c) => c.balance)),
    owing: customers.data.filter((c) => toCents(c.balance) > 0).length,
    docs: customers.data.filter((c) => c.missingDocuments.length).length,
  }));
  const lead = () => fieldsOf(t(), 'customer').slice(0, 2);
  // Plans and documents show once the business uses them, not just because the template offers them.
  const onPlans = () => totals().plan > 0;
  const asksDocs = () => totals().docs > 0;
  // The open profile is local state seeded from `?customer=` (deep links
  // from a booking land on it). Opening one doesn't navigate: a search-only
  // navigation here would hold the drawer's query in the router transition.
  const [openId, setOpenId] = createSignal<string | null>(() => search().customer ?? null, { name: 'customerOpen' });
  const openProfile = (id: string | null) => setOpenId(id);
  const sites = () => ctx.data.nodes.filter((n) => n.kind === 'location' && n.reachable);

  return (
    <div class="page">
      <PageHead eyebrow={ctx.data.path.at(-1)!.name} title={t().terms.customers} lede={tr('customers.lede')}>
        <Show when={canManage()}>
          <button type="button" class="btn" onClick={() => setAdding(true)}>
            <Icon name="plus" size={16} /> {tr('customers.addThing', { what: t().terms.customer.toLowerCase() })}
          </button>
        </Show>
      </PageHead>

      <div class="stats">
        <Stat label={t().terms.customers} value={totals().count} foot={tr('customers.statInScope')} />
        <Show when={onPlans()}>
          <Stat label={tr('customers.onPlan')} value={`${Math.round((totals().plan / Math.max(totals().count, 1)) * 100)}%`} foot={tr('customers.statActive', { count: totals().plan })} />
        </Show>
        <Stat label={tr('customers.openBalances')} value={fmtMoney(totals().balance, ctx.data.tenant.currency)} foot={`${totals().owing} ${t().terms.customers.toLowerCase()}`} />
        <Show when={asksDocs()}>
          <Stat label={tr('customers.missingDocuments')} value={totals().docs} foot={tr('customers.statNeededBeforeService')} />
        </Show>
      </div>

      <Panel>
        <div class="toolbar">
          <div class="chips" role="group" aria-label={tr('customers.filter')}>
            <For each={[['all', tr('customers.filterEveryone')], ...(onPlans() ? [['plan', tr('customers.onPlan')]] : []), ['balance', tr('customers.filterOwes')], ...(asksDocs() ? [['docs', tr('customers.missingDocuments')]] : [])] as Array<[Filter, string]>}>
              {([value, label]) => (
                <button type="button" class={['chip-toggle', { on: filter() === value }]} onClick={() => setFilter(value)}>
                  {label}
                </button>
              )}
            </For>
          </div>
          <label class="filter">
            <Icon name="search" size={15} />
            <input
              type="search"
              placeholder={tr('customers.searchPlaceholder', { fields: lead().map((f) => f.label.toLowerCase()).join(', ') })}
              value={text()}
              onInput={(event) => setText(event.currentTarget.value)}
            />
          </label>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{t().terms.customer}</th>
                <For each={lead()}>{(f) => <th>{f.label}</th>}</For>
                <Show when={onPlans()}>
                  <th>{tr('customers.colPlan')}</th>
                </Show>
                <th class="num">{tr('customers.colVisits')}</th>
                <th class="num">{tr('customers.colBalance')}</th>
                <th>{tr('customers.colLastVisit')}</th>
              </tr>
            </thead>
            <tbody>
              <For each={rows().slice(0, 300)} fallback={<tr><td colspan="7" class="muted empty">{tr('customers.noMatches')}</td></tr>}>
                {(c) => (
                  <tr class={['clickable', { picked: openId() === c.id }]} onClick={() => openProfile(c.id)}>
                    <td>
                      <div class="person">
                        <span class="avatar sm">{c.name.split(' ').map((p) => p[0]).join('').slice(0, 2)}</span>
                        <span>
                          <strong>{c.name}</strong>
                          <span class="muted block">
                            {c.phone}
                            {c.account ? ` · ${c.account.name}` : ''}
                          </span>
                        </span>
                        <Show when={c.missingDocuments.length}>
                          <span class="pill warn">{tr('customers.missingPill', { what: c.missingDocuments.map((d) => d.label.toLowerCase()).join(', ') })}</span>
                        </Show>
                      </div>
                    </td>
                    <For each={lead()}>{(f) => <td>{c.fields[f.key] === undefined ? '' : showValue(c.fields[f.key])}</td>}</For>
                    <Show when={onPlans()}>
                      <td>{c.subscriptions.length ? planText(c) : <span class="muted">{tr('customers.payAsYouGo')}</span>}</td>
                    </Show>
                    <td class="num mono">{c.visits}</td>
                    <td class={['num mono', { warn: toCents(c.balance) > 0 }]}>{toCents(c.balance) ? fmtMoney(c.balance, ctx.data.tenant.currency) : '—'}</td>
                    <td class="muted">{c.lastVisit ? fmtAgo(`${c.lastVisit}:00Z`) : tr('customers.notYet')}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Panel>

      <Show when={openId()}>
        {(id) => (
          <aside class="drawer" aria-label={tr('customers.profileLabel', { term: t().terms.customer })}>
            <Loading fallback={<Skeleton rows={5} height={48} />}>
              <Profile org={org()} id={id()} template={t()} onClose={() => openProfile(null)} />
            </Loading>
          </aside>
        )}
      </Show>
      <Show when={adding()}>
        <AddCustomer org={org()} scope={scope()} template={t()} sites={sites()} siteId={ctx.data.path.at(-1)!.kind === 'location' ? ctx.data.scopeId : ''} onClose={() => setAdding(false)} />
      </Show>
    </div>
  );
}

function Profile(props: { org: string; id: string; template: Template; onClose: () => void }) {
  const profile = useQuery(() => customerQuery(props.org, props.id));
  const currency = useCurrency();
  const c = () => profile.data.customer;
  const sell = useMutation(() => ({
    mutationFn: (offeringId: string) => sellPlan({ org: props.org, customerId: props.id, offeringId }),
    onSuccess: (_r, offeringId) =>
      notify(tr('customers.toastPlanSold', { plan: profile.data.plans.find((p) => p.id === offeringId)?.name ?? tr('customers.planFallback'), name: c().name })),
  }));
  const cancel = useMutation(() => ({
    mutationFn: (subscriptionId: string) => cancelPlan({ org: props.org, customerId: props.id, subscriptionId }),
    onSuccess: () => notify(tr('customers.toastPlanCancelled', { name: c().name })),
  }));
  const record = useMutation(() => ({
    mutationFn: (input: Omit<Parameters<typeof recordDocument>[0], 'org' | 'customerId'>) =>
      recordDocument({ org: props.org, customerId: props.id, ...input }),
    onSuccess: (_r, input) =>
      notify(tr('customers.toastDocRecorded', { doc: profile.data.documentTypes.find((d) => d.key === input.type)?.label ?? tr('customers.docFallback'), name: c().name })),
  }));
  const [docType, setDocType] = createSignal('', { name: 'profileDocType' });
  const chosenDoc = () => profile.data.documentTypes.find((d) => d.key === (docType() || profile.data.documentTypes[0]?.key));
  const subjectName = (id: string | null) => profile.data.subjects.find((x) => x.id === id)?.name;

  return (
    <>
      <header class="drawer-head">
        <div>
          <p class="eyebrow">
            {props.template.terms.customer} · {c().locationName}
          </p>
          <h2>{c().name}</h2>
          <p class="muted">
            {c().phone} · {c().email}
          </p>
        </div>
        <button type="button" class="icon-btn" aria-label={tr('customers.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>

      <div class="profile-flags">
        <For each={c().missingDocuments}>
          {(d) => <span class="flag warn">{tr('customers.flagMissing', { doc: d.label })}</span>}
        </For>
        <Show when={toCents(c().balance) > 0}>
          <Link to="/t/$org/payments" params={{ org: props.org }} search={{ scope: c().locationId }} class="flag bad">
            {tr('customers.flagOwes', { amount: fmtMoney(c().balance, currency()) })}
          </Link>
        </Show>
      </div>

      <dl class="facts">
        <Show when={c().account}>
          {(account) => (
            <>
              <dt>{account().typeLabel}</dt>
              <dd>
                {account().name}
                {account().role ? ` · ${account().role}` : ''}
                <Show when={profile.data.contacts.length}>
                  <span class="muted block">{tr('customers.withContacts', { names: profile.data.contacts.map((o) => o.name).join(', ') })}</span>
                </Show>
              </dd>
            </>
          )}
        </Show>
        <For each={fieldsOf(props.template, 'customer')}>
          {(f) => (
            <>
              <dt>{f.label}</dt>
              <dd class={{ warn: c().expiredFields.includes(f.key) }}>
                {showValue(c().fields[f.key])}
                {c().expiredFields.includes(f.key) ? ` ${tr('customers.expiredSuffix')}` : ''}
              </dd>
            </>
          )}
        </For>
        <dt>{tr('customers.since')}</dt>
        <dd>{c().since.slice(0, 10)}</dd>
        <dt>{tr('customers.colVisits')}</dt>
        <dd>{tr('customers.visitsPaid', { visits: c().visits, amount: fmtMoney(c().spend, currency()) })}</dd>
      </dl>

      <Show when={props.template.subjectTypes.length}>
        <section class="intake">
          <h3>{props.template.subjectTypes.map((x) => x.plural).join(' & ')}</h3>
          <ul class="mini-list">
            <For each={profile.data.subjects} fallback={<li class="muted">{tr('customers.noneYet')}</li>}>
              {(x) => <SubjectRow subject={x} template={props.template} missing={profile.data.subjectMissing[x.id] ?? []} />}
            </For>
          </ul>
          <Show when={profile.data.canBook}>
            <AddSubject org={props.org} customerId={props.id} template={props.template} />
          </Show>
        </section>
      </Show>

      <Show when={profile.data.documentTypes.some((d) => d.level !== 'Not needed') || c().documents.length}>
        <section class="intake">
          <h3>{tr('customers.documents')}</h3>
          <ul class="mini-list">
            <For each={c().documents} fallback={<li class="muted">{tr('customers.nothingOnFile')}</li>}>
              {(d) => (
                <li>
                  <span class="mono muted">{d.issued}</span>
                  <span>
                    {d.label}
                    {d.subjectId ? ` · ${subjectName(d.subjectId) ?? ''}` : ''}
                    {d.reference ? ` · ${d.reference}` : ''}
                  </span>
                  <span class={['pill', d.valid ? 'ok' : 'warn']}>{d.valid ? (d.expires ? tr('customers.docUntil', { date: d.expires }) : tr('customers.docValid')) : tr('customers.docExpired', { date: d.expires ?? '' })}</span>
                </li>
              )}
            </For>
          </ul>
          <Show when={profile.data.canBook}>
            <form
              class="form"
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                const text = (k: string) => String(data.get(k) ?? '').trim() || undefined;
                record.mutate({ type: String(data.get('doc')), subjectId: text('doc-subject'), issued: text('doc-issued'), expires: text('doc-expires'), reference: text('doc-ref') });
              }}
            >
              <div class="form-row">
                <label>
                  <span class="form-label">{tr('customers.recordLabel')}</span>
                  <select name="doc" onChange={(event) => setDocType(event.currentTarget.value)}>
                    <For each={profile.data.documentTypes}>
                      {(d) => (
                        <option value={d.key}>
                          {d.label}
                          {d.level === 'Not needed' ? '' : ` · ${d.level.toLowerCase()}`}
                        </option>
                      )}
                    </For>
                  </select>
                </label>
                <Show when={chosenDoc()?.appliesTo === 'subject'}>
                  <label>
                    <span class="form-label">{tr('customers.forLabel')}</span>
                    <select name="doc-subject" required>
                      <For each={profile.data.subjects.filter((x) => !chosenDoc()?.subjectType || x.type === chosenDoc()?.subjectType)}>
                        {(x) => <option value={x.id}>{x.name}</option>}
                      </For>
                    </select>
                  </label>
                </Show>
              </div>
              <div class="form-row">
                <label>
                  <span class="form-label">{tr('customers.issuedLabel')}</span>
                  <input type="date" name="doc-issued" />
                </label>
                <label>
                  <span class="form-label">
                    {chosenDoc()?.validDays ? tr('customers.expiresDefault', { count: chosenDoc()?.validDays ?? 0 }) : tr('customers.expiresOptional')}
                  </span>
                  <input type="date" name="doc-expires" />
                </label>
              </div>
              <label>
                <span class="form-label">{tr('customers.referenceLabel')}</span>
                <input type="text" name="doc-ref" maxlength="120" />
              </label>
              <button type="submit" class="btn small" disabled={record.isPending}>
                {tr('customers.recordDocument')}
              </button>
            </form>
          </Show>
          <Show when={record.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        </section>
      </Show>

      <Show when={profile.data.plans.length || c().subscriptions.length}>
        <section class="intake">
          <h3>{tr('customers.plans')}</h3>
          <Show when={c().subscriptions.length} fallback={<p class="muted">{tr('customers.paysAsTheyGo')}</p>}>
            <ul class="mini-list">
              <For each={c().subscriptions}>
                {(plan) => (
                  <li>
                    <strong>{plan.name}</strong>
                    <span class="muted">{plan.credits !== null ? tr('customers.creditsLeft', { count: plan.credits }) : tr('customers.renews', { date: plan.renews ?? '—' })}</span>
                    <Show when={profile.data.canCollect}>
                      <button type="button" class="btn small ghost" disabled={cancel.isPending} onClick={() => cancel.mutate(plan.id)}>
                        {tr('customers.cancel')}
                      </button>
                    </Show>
                  </li>
                )}
              </For>
            </ul>
          </Show>
          <Show when={profile.data.canCollect}>
            <form
              class="row start"
              onSubmit={(event) => {
                event.preventDefault();
                sell.mutate(String(new FormData(event.currentTarget).get('plan')));
              }}
            >
              <select name="plan">
                <For each={profile.data.plans}>
                  {(p) => (
                    <option value={p.id}>
                      {p.name} · {fmtMoney(p.price, currency())}
                      {p.unit === 'month' ? tr('customers.perMonthShort') : ''}
                    </option>
                  )}
                </For>
              </select>
              <button type="submit" class="btn small" disabled={sell.isPending}>
                {c().subscriptions.length ? tr('customers.addOrRenewPlan') : tr('customers.sellPlan')}
              </button>
            </form>
          </Show>
          <Show when={sell.error ?? cancel.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        </section>
      </Show>
      <section>
        <h3 class="drawer-sub">{tr('customers.recentBookings', { term: props.template.terms.bookings.toLowerCase() })}</h3>
        <ul class="mini-list">
          <For each={profile.data.history} fallback={<li class="muted">{tr('customers.nothingYet')}</li>}>
            {(b) => (
              <li>
                <span class="mono muted">{b.start.slice(0, 10)}</span>
                <span>
                  <KindBadge kind={b.kind} /> {b.offeringName}
                </span>
                <StatusPill status={b.status} labels={props.template.status} />
              </li>
            )}
          </For>
        </ul>
      </section>

      <section>
        <h3 class="drawer-sub">{tr('customers.charges')}</h3>
        <ul class="mini-list">
          <For each={profile.data.charges} fallback={<li class="muted">{tr('customers.noCharges')}</li>}>
            {(ch) => (
              <li>
                <span class="mono muted">{ch.date}</span>
                <span>{ch.description}</span>
                <span class={['pill', ch.status === 'paid' ? 'ok' : ch.status === 'refunded' ? 'neutral' : 'warn']}>
                  {fmtMoney(ch.amount, ch.currency)} {tr(`customers.charge_${ch.status}`)}
                </span>
              </li>
            )}
          </For>
        </ul>
      </section>
    </>
  );
}

function SubjectRow(props: { subject: Subject; template: Template; missing: Array<string> }) {
  const defs = () => props.template.subjectTypes.find((x) => x.key === props.subject.type)?.fields ?? [];
  return (
    <li>
      <strong>{props.subject.name}</strong>
      <span class="muted">
        {[props.subject.typeLabel, ...defs().filter((f) => props.subject.fields[f.key] !== undefined).map((f) => `${f.label}: ${showValue(props.subject.fields[f.key])}`)].join(' · ')}
      </span>
      <Show when={props.missing.length || props.subject.expiredFields.length}>
        <span class="pill warn">{[...props.missing.map((m) => tr('customers.missingPill', { what: m.toLowerCase() })), ...props.subject.expiredFields.map((k) => tr('customers.fieldExpired', { field: k }))].join(', ')}</span>
      </Show>
    </li>
  );
}

function AddSubject(props: { org: string; customerId: string; template: Template }) {
  const [type, setType] = createSignal('', { name: 'subjectType' });
  const kind = () => props.template.subjectTypes.find((x) => x.key === type()) ?? props.template.subjectTypes[0];
  const add = useMutation(() => ({
    mutationFn: (input: Parameters<typeof createSubject>[0]) => createSubject(input),
    onSuccess: (_r, input) => {
      notify(tr('customers.toastAdded', { name: input.name.trim() }));
      form?.reset();
    },
  }));
  let form: HTMLFormElement | undefined;
  return (
    <form
      ref={(el) => (form = el)}
      class="form"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        add.mutate({ org: props.org, customerId: props.customerId, type: kind().key, name: String(data.get('subject-name')), fields: readFields(kind().fields ?? [], data, 's-') });
      }}
    >
      <div class="form-row">
        <Show when={props.template.subjectTypes.length > 1}>
          <label>
            <span class="form-label">{tr('customers.addLabel')}</span>
            <select name="subject-type" onChange={(event) => setType(event.currentTarget.value)}>
              <For each={props.template.subjectTypes}>{(x) => <option value={x.key}>{x.label}</option>}</For>
            </select>
          </label>
        </Show>
        <label>
          <span class="form-label">{tr('customers.nameOf', { type: kind().label })}</span>
          <input type="text" name="subject-name" required minlength="2" />
        </label>
      </div>
      <For each={kind().fields ?? []}>{(f) => <FieldInput def={f} prefix="s-" />}</For>
      <Show when={add.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      <button type="submit" class="btn small" disabled={add.isPending}>
        {tr('customers.addThing', { what: kind().label.toLowerCase() })}
      </button>
    </form>
  );
}

function AddCustomer(props: { org: string; scope: string; template: Template; sites: Array<ScopeNode>; siteId: string; onClose: () => void }) {
  const hasAccounts = () => props.template.accountTypes.length > 0;
  const accounts = useQuery(() => ({ ...accountsQuery(props.org, props.scope), enabled: hasAccounts() }));
  // '' no account · an account id · `new:<type>` to open one.
  const [account, setAccount] = createSignal('', { name: 'customerAccount' });
  const opening = () => (account().startsWith('new:') ? props.template.accountTypes.find((a) => `new:${a.key}` === account()) : undefined);
  const add = useMutation(() => ({
    mutationFn: (input: Parameters<typeof createCustomer>[0]) => createCustomer(input),
    onSuccess: (_r, input) => {
      notify(tr('customers.toastAdded', { name: input.name.trim() }));
      props.onClose();
    },
  }));
  return (
    <aside class="drawer" aria-label={tr('customers.addThing', { what: props.template.terms.customer.toLowerCase() })}>
      <header class="drawer-head">
        <h2>{tr('customers.addThing', { what: props.template.terms.customer.toLowerCase() })}</h2>
        <button type="button" class="icon-btn" aria-label={tr('customers.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          add.mutate({
            org: props.org,
            locationId: String(data.get('site')),
            name: String(data.get('name')),
            phone: String(data.get('phone')),
            email: String(data.get('email')),
            fields: readFields(fieldsOf(props.template, 'customer'), data, 'f-'),
            ...(opening()
              ? { accountType: opening()!.key, accountName: String(data.get('account-name')) }
              : account()
                ? { accountId: account() }
                : {}),
            ...(account() ? { accountRole: String(data.get('account-role') ?? '') } : {}),
          });
        }}
      >
        <label>
          <span class="form-label">{props.template.terms.location}</span>
          <select name="site" value={props.siteId || props.sites[0]?.id}>
            <For each={props.sites}>{(s) => <option value={s.id}>{s.name}</option>}</For>
          </select>
        </label>
        <label>
          <span class="form-label">{tr('customers.name')}</span>
          <input type="text" name="name" required minlength="2" />
        </label>
        <div class="form-row">
          <label>
            <span class="form-label">{tr('customers.phone')}</span>
            <input type="text" name="phone" />
          </label>
          <label>
            <span class="form-label">{tr('customers.email')}</span>
            <input type="text" name="email" />
          </label>
        </div>
        <For each={fieldsOf(props.template, 'customer')}>{(f) => <FieldInput def={f} prefix="f-" />}</For>
        <Show when={hasAccounts()}>
          <label>
            <span class="form-label">{tr('customers.accountLabel')}</span>
            <select name="account" onChange={(event) => setAccount(event.currentTarget.value)}>
              <option value="">{tr('customers.none')}</option>
              <For each={accounts.data ?? ([] as Array<Account>)}>
                {(a) => (
                  <option value={a.id}>
                    {a.name} · {a.typeLabel}
                  </option>
                )}
              </For>
              <For each={props.template.accountTypes}>{(a) => <option value={`new:${a.key}`}>{tr('customers.newAccount', { type: a.label.toLowerCase() })}</option>}</For>
            </select>
          </label>
          <Show when={account()}>
            <div class="form-row">
              <Show when={opening()}>
                {(kind) => (
                  <label>
                    <span class="form-label">{tr('customers.nameOf', { type: kind().label })}</span>
                    <input type="text" name="account-name" required minlength="2" />
                  </label>
                )}
              </Show>
              <label>
                <span class="form-label">{tr('customers.roleLabel')}</span>
                <input type="text" name="account-role" maxlength="60" placeholder={tr('customers.rolePlaceholder')} />
              </label>
            </div>
          </Show>
        </Show>
        <Show when={add.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={add.isPending}>
          {tr('customers.addThing', { what: props.template.terms.customer.toLowerCase() })}
        </button>
      </form>
    </aside>
  );
}

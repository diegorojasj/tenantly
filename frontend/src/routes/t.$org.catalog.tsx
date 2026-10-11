import { useMutation, useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createSignal, For, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import FieldInput from '../components/FieldInput';
import Icon from '../components/Icon';
import { KindBadge, PageHead, Panel } from '../components/ui';
import { fieldsOf, readFields } from '../lib/fields';
import { defined, fmtMoney, perUnit } from '../lib/format';
import { t as tr } from '../lib/i18n';
import { presetOf, resourceType, ruleText } from '../lib/fulfilment';
import { createOffering, toggleOffering } from '../lib/ops';
import { catalogQuery, prefetch, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { notify } from '../lib/toast';
import type { Offering, Preset, Requirement, Template } from '../lib/types';

// Catalog — one job: define what you sell and how it's fulfilled. Each
// offering starts from one of the template's presets and states its rules in
// plain words: capacity, time, place and the resources each booking takes.
// Every preset is available to every business; a group only shows once
// something of its kind is on sale, so the page grows with the business.
export const Route = createFileRoute('/t/$org/catalog')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, catalogQuery(params.org, deps.scope));
  },
  head: () => ({ meta: [{ title: tr('catalog.pageTitle') }] }),
  component: CatalogPage,
});

const priceLabel = (o: Offering, currency: string) => `${fmtMoney(o.price, currency)}${o.unit === 'month' ? tr('catalog.perMonthShort') : perUnit(o.unit)}`;

function CatalogPage() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const catalog = useQuery(() => catalogQuery(org(), scope()));
  const t = () => ctx.data.tenant.template;
  const [adding, setAdding] = createSignal(false, { name: 'catalogAdding' });
  // One panel per preset, then one for offerings whose preset the template no longer has.
  const groups = () => {
    const keys = new Set(t().presets.map((p) => p.key));
    return [
      ...t().presets.map((p) => ({ title: p.plural, intro: p.intro ?? '', has: (k: string) => k === p.key })),
      { title: tr('catalog.otherTitle'), intro: tr('catalog.otherIntro'), has: (k: string) => !keys.has(k) },
    ];
  };
  const toggle = useMutation(() => ({
    // The intent travels with the call: after the refresh the offering
    // already shows its new state, so reading it then would invert the message.
    mutationFn: (input: { id: string; name: string; retire: boolean }) => toggleOffering({ org: org(), offeringId: input.id }),
    onSuccess: (_r, input) => notify(input.retire ? tr('catalog.toastRetired', { name: input.name }) : tr('catalog.toastOnSale', { name: input.name })),
  }));

  return (
    <div class="page">
      <PageHead
        eyebrow={ctx.data.tenant.name}
        title={tr('catalog.title')}
        lede={tr('catalog.lede')}
      >
        <Show when={catalog.data.canEdit}>
          <button type="button" class="btn" onClick={() => setAdding(true)}>
            <Icon name="plus" size={16} /> {tr('catalog.addOffering')}
          </button>
        </Show>
      </PageHead>

      <Show when={!catalog.data.offerings.length}>
        <Panel>
          <p class="empty-note">
            {tr('catalog.emptyNote', { business: ctx.data.tenant.name })}
          </p>
        </Panel>
      </Show>

      <For each={groups()}>
        {(group) => (
          <Show when={catalog.data.offerings.some((e) => group.has(e.offering.kind))}>
            <Panel title={group.title} aside={<span class="muted">{group.intro}</span>}>
              <div class="cards">
                <For each={catalog.data.offerings.filter((e) => group.has(e.offering.kind))}>
                  {(e) => (
                    <article class={['card', 'offer', { on: e.offering.active }]}>
                      <header>
                        <KindBadge kind={e.offering.kind} label={presetOf(t(), e.offering.kind)?.label} />
                        <strong>{e.offering.name}</strong>
                        <span class="price mono">{e.offering.price ? priceLabel(e.offering, ctx.data.tenant.currency) : tr('catalog.free')}</span>
                      </header>
                      <p class="rule">{ruleText(e.offering, t())}</p>
                      <dl class="offer-stats">
                        <Show
                          when={e.offering.time === 'none'}
                          fallback={
                            <>
                              <dt>{tr('catalog.delivered')}</dt>
                              <dd class="mono">{e.bookings}</dd>
                              <dt>{tr('catalog.revenue')}</dt>
                              <dd class="mono">{fmtMoney(e.revenue, ctx.data.tenant.currency)}</dd>
                              <Show when={e.fill !== null}>
                                <dt>{tr('catalog.avgFill')}</dt>
                                <dd class={['mono', { warn: (e.fill ?? 0) < 50 }]}>{e.fill}%</dd>
                              </Show>
                            </>
                          }
                        >
                          <dt>{tr('catalog.subscribers')}</dt>
                          <dd class="mono">{e.subscribers}</dd>
                          <dt>{tr('catalog.monthlyValue')}</dt>
                          <dd class="mono">{fmtMoney(e.revenue, ctx.data.tenant.currency)}</dd>
                        </Show>
                      </dl>
                      <footer>
                        <span class="muted">{e.offering.category}</span>
                        <Show when={catalog.data.canEdit} fallback={<span class="muted">{e.offering.active ? tr('catalog.onSale') : tr('catalog.retired')}</span>}>
                          <Show
                            when={e.offering.active}
                            fallback={
                              <button
                                type="button"
                                class="btn small ghost"
                                disabled={toggle.isPending && toggle.variables?.id === e.offering.id}
                                onClick={() => toggle.mutate({ id: e.offering.id, name: e.offering.name, retire: false })}
                              >
                                {tr('catalog.putOnSale')}
                              </button>
                            }
                          >
                            <ConfirmButton
                              class="small ghost"
                              label={tr('catalog.retire')}
                              confirm={tr('catalog.retireConfirm')}
                              disabled={toggle.isPending && toggle.variables?.id === e.offering.id}
                              onConfirm={() => toggle.mutate({ id: e.offering.id, name: e.offering.name, retire: true })}
                            />
                          </Show>
                        </Show>
                      </footer>
                    </article>
                  )}
                </For>
              </div>
            </Panel>
          </Show>
        )}
      </For>

      <Show when={adding()}>
        <AddOffering org={org()} template={t()} roles={catalog.data.roles} onClose={() => setAdding(false)} />
      </Show>
    </div>
  );
}

const unitLabel = (unit: Offering['unit']) => tr(`catalog.unit_${unit}`);

/** One row per requirement of the preset, then one (at zero) for every other resource type. */
function requirementRows(t: Template, preset: Preset | undefined): Array<Requirement> {
  const own = preset?.requires ?? [];
  const rest = t.resourceTypes.filter((r) => !own.some((q) => q.type === r.key)).map((r) => ({ type: r.key, quantity: 0 }));
  return preset?.time === 'none' ? [] : [...own, ...rest];
}

function AddOffering(props: { org: string; template: Template; roles: Record<string, Array<string>>; onClose: () => void }) {
  const [kind, setKind] = createSignal(() => props.template.presets[0]?.key ?? '', { name: 'newOfferingKind' });
  const preset = () => presetOf(props.template, kind());
  const [unitChoice, setUnit] = createSignal<Offering['unit'] | ''>('', { name: 'newOfferingUnit' });
  const unit = () => (preset()?.units.includes(unitChoice() as Offering['unit']) ? (unitChoice() as Offering['unit']) : (preset()?.units[0] ?? 'session'));
  // Hire presets book by the hour on one day, or whole days, nights or months.
  const time = () => {
    const base = preset()?.time ?? 'slot';
    return base === 'window' || base === 'span' ? (unit() === 'hour' ? 'window' : 'span') : base;
  };
  const rows = () => requirementRows(props.template, preset());
  // The preset's own requirements show up front; the other resource types wait under "More options".
  const own = () => (time() === 'none' ? 0 : (preset()?.requires.length ?? 0));
  const offeringFields = () => fieldsOf(props.template, 'offering');
  // Only single-customer offerings can each be for a subject (a pet, a vehicle).
  const servesSubject = () => props.template.subjectTypes.length > 0 && time() !== 'none';
  const priceFor = () => {
    const u = unit();
    return u === 'session' ? tr('catalog.price') : u === 'pack' ? tr('catalog.pricePack') : time() === 'none' ? tr('catalog.pricePer_month') : tr(`catalog.pricePer_${u}`);
  };
  const add = useMutation(() => ({
    mutationFn: (input: Parameters<typeof createOffering>[0]) => createOffering(defined(input)),
    onSuccess: (_r, input) => {
      notify(tr('catalog.toastAdded', { name: input.name.trim() }));
      props.onClose();
    },
  }));
  return (
    <aside class="drawer" aria-label={tr('catalog.addOffering')}>
      <header class="drawer-head">
        <h2>{tr('catalog.addOffering')}</h2>
        <button type="button" class="icon-btn" aria-label={tr('catalog.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          add.mutate({
            org: props.org,
            kind: kind(),
            name: String(d.get('name')),
            category: String(d.get('category') ?? ''),
            price: String(d.get('price')),
            minutes: Number(d.get('minutes') ?? 0),
            capacity: d.get('capacity') ? Number(d.get('capacity')) : undefined,
            unit: unit(),
            place: (d.get('place') as Offering['place'] | null) ?? undefined,
            requires:
              time() === 'none'
                ? undefined
                : rows().map((r, i) => ({
                    type: r.type,
                    quantity: Number(d.get(`q${i}`) ?? 0),
                    pick: r.pick,
                    role: String(d.get(`r${i}`) ?? '').trim() || null,
                    where: r.where,
                  })),
            credits: d.get('credits') ? Number(d.get('credits')) : undefined,
            subjectType: d.get('subject') === null ? undefined : String(d.get('subject')),
            fields: offeringFields().length ? readFields(offeringFields(), d, 'of-') : undefined,
          });
        }}
      >
        <fieldset class="choice-pick">
          <legend class="form-label">{tr('catalog.whatSelling')}</legend>
          <For each={props.template.presets}>
            {(p) => (
              <label class={['choice-card', { on: kind() === p.key }]}>
                <input type="radio" name="kind" value={p.key} checked={kind() === p.key} onChange={() => setKind(p.key)} />
                <strong>{p.label}</strong>
                <Show when={p.intro}>
                  <span class="muted">{p.intro}</span>
                </Show>
              </label>
            )}
          </For>
        </fieldset>
        <label>
          <span class="form-label">{tr('catalog.name')}</span>
          <input type="text" name="name" required minlength="2" />
        </label>
        <div class="form-row">
          <label>
            <span class="form-label">{priceFor()}</span>
            <input type="number" name="price" min="0" step="0.01" required />
          </label>
        </div>
        <div class="form-row">
          <Show when={(preset()?.units.length ?? 0) > 1}>
            <label>
              <span class="form-label">{time() === 'none' ? tr('catalog.planType') : tr('catalog.pricedBy')}</span>
              <select value={unit()} onChange={(event) => setUnit(event.currentTarget.value as Offering['unit'])}>
                <For each={preset()?.units}>
                  {(u) => <option value={u}>{time() === 'none' && u === 'month' ? tr('catalog.monthlyMembership') : unitLabel(u)}</option>}
                </For>
              </select>
            </label>
          </Show>
          <Show when={unit() === 'pack'}>
            <label>
              <span class="form-label">{tr('catalog.creditsInPack')}</span>
              <input type="number" name="credits" min="1" value="10" required />
            </label>
          </Show>
        </div>
        <Show when={time() !== 'none'}>
          <div class="form-row">
            <Show when={time() !== 'span'} fallback={<input type="hidden" name="minutes" value="60" />}>
              <label>
                <span class="form-label">{time() === 'window' ? tr('catalog.defaultWindow') : tr('catalog.duration')}</span>
                <input type="number" name="minutes" min="15" step="15" value="60" required />
              </label>
            </Show>
            <Show when={time() === 'slot' && (preset()?.capacity ?? 1) > 1}>
              <label>
                <span class="form-label">{tr('catalog.spotsPerSession')}</span>
                <input type="number" name="capacity" min="1" value={preset()?.capacity ?? 1} required />
              </label>
            </Show>
          </div>
          <For each={rows().slice(0, own())}>{(r, i) => <RequirementRow template={props.template} row={r} index={i()} />}</For>
        </Show>
        <details class="more-options">
          <summary>{tr('catalog.moreOptions')}</summary>
          <div class="form">
            <label>
              <span class="form-label">{tr('catalog.categoryLabel')}</span>
              <input type="text" name="category" placeholder={tr('catalog.categoryPlaceholder')} />
            </label>
            <Show when={time() !== 'none'}>
              <div class="form-row">
                <Show when={time() === 'slot' && (preset()?.capacity ?? 1) <= 1}>
                  <label>
                    <span class="form-label">{tr('catalog.customersPerBooking')}</span>
                    <input type="number" name="capacity" min="1" value={preset()?.capacity ?? 1} required />
                  </label>
                </Show>
                <label>
                  <span class="form-label">{tr('catalog.where')}</span>
                  <select name="place" value={preset()?.place ?? 'on_site'}>
                    <option value="on_site">{tr('catalog.onSite')}</option>
                    <option value="at_customer">{tr('catalog.atCustomer')}</option>
                  </select>
                </label>
              </div>
              <Show when={time() === 'slot' && (preset()?.capacity ?? 1) <= 1}>
                <span class="muted hint">{tr('catalog.capacityHint')}</span>
              </Show>
              <Show when={servesSubject()}>
                <label>
                  <span class="form-label">{tr('catalog.eachBookingFor')}</span>
                  <select name="subject" value={preset()?.subject ?? ''}>
                    <option value="">{tr('catalog.forCustomer', { term: props.template.terms.customer.toLowerCase() })}</option>
                    <For each={props.template.subjectTypes}>{(x) => <option value={x.key}>{tr('catalog.forSubject', { plural: x.plural.toLowerCase() })}</option>}</For>
                  </select>
                </label>
              </Show>
              <fieldset class="form requirements">
                <legend class="form-label">{tr('catalog.alsoTakes')}</legend>
                <For each={rows().slice(own())}>{(r, i) => <RequirementRow template={props.template} row={r} index={own() + i()} />}</For>
                <span class="muted hint">{tr('catalog.requirementsHint')}</span>
              </fieldset>
            </Show>
          </div>
        </details>
        <For each={props.template.resourceTypes}>
          {(r) => (
            <datalist id={`roles-${r.key}`}>
              <For each={props.roles[r.key] ?? []}>{(role) => <option value={role} />}</For>
            </datalist>
          )}
        </For>
        <For each={offeringFields()}>{(f) => <FieldInput def={f} prefix="of-" />}</For>
        <Show when={add.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={add.isPending}>
          {tr('catalog.addToCatalog')}
        </button>
      </form>
    </aside>
  );
}

/** One resource a booking takes: how many, and which kind (by its specialty or type). */
function RequirementRow(props: { template: Template; row: Requirement; index: number }) {
  const type = () => resourceType(props.template, props.row.type);
  return (
    <div class="form-row">
      <label>
        <span class="form-label">
          {type().plural} {props.row.pick ?? type().people ? tr('catalog.picked') : tr('catalog.assigned')}
        </span>
        <input type="number" name={`q${props.index}`} min="0" max="20" value={props.row.quantity} />
      </label>
      <label>
        <span class="form-label">
          {type().roleLabel ?? tr('catalog.typeFallback')}
          {props.row.named ? '' : ` ${tr('catalog.optional')}`}
        </span>
        <input
          type="text"
          name={`r${props.index}`}
          list={`roles-${props.row.type}`}
          value={props.row.role ?? ''}
          placeholder={type().people ? tr('catalog.anyPlaceholder') : tr('catalog.rolePlaceholder')}
        />
      </label>
    </div>
  );
}

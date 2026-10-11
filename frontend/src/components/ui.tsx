// Small presentational building blocks shared across routes.
import type { JSX } from '@solidjs/web';
import type { ParentProps } from 'solid-js';
import { For, Show } from 'solid-js';

import { t } from '../lib/i18n';
import { isRefusal } from '../lib/refusal';
import type { BookingStatus, NodeKind, OfferingKind, RoleId } from '../lib/types';
import type { MessageKey } from '../locales';
import Icon from './Icon';
import type { IconName } from './Icon';

export function PageHead(props: ParentProps<{ eyebrow: string; title: string; lede?: string }>) {
  return (
    <header class="page-head">
      <div>
        <p class="eyebrow">{props.eyebrow}</p>
        <h1>{props.title}</h1>
        <Show when={props.lede}>
          <p class="lede">{props.lede}</p>
        </Show>
      </div>
      <div class="page-actions">{props.children}</div>
    </header>
  );
}

export function Panel(props: ParentProps<{ title?: string; icon?: IconName; aside?: JSX.Element; class?: string }>) {
  return (
    <section class={['panel', props.class]}>
      <Show when={props.title}>
        <header class="panel-head">
          <h2>
            <Show when={props.icon}>{(name) => <Icon name={name()} size={16} />}</Show>
            {props.title}
          </h2>
          {props.aside}
        </header>
      </Show>
      {props.children}
    </section>
  );
}

export function Stat(props: { label: string; value: string | number | JSX.Element; foot?: JSX.Element; delta?: JSX.Element }) {
  return (
    <div class="stat">
      <span class="stat-label">{props.label}</span>
      <strong class="stat-value">
        {props.value}
        {props.delta}
      </strong>
      <Show when={props.foot}>
        <span class="stat-foot">{props.foot}</span>
      </Show>
    </div>
  );
}

const roleLabels: Record<RoleId, MessageKey> = {
  owner: 'common.role_owner',
  admin: 'common.role_admin',
  regional_manager: 'common.role_regional_manager',
  location_manager: 'common.role_location_manager',
  analyst: 'common.role_analyst',
  auditor: 'common.role_auditor',
};

/** A role's chip: its label (roles are per business), else the default role's name, else its key. */
export function RoleChip(props: { role: RoleId; label?: string }) {
  return <span class={['chip', `role-${props.role}`]}>{props.label ?? (roleLabels[props.role] ? t(roleLabels[props.role]) : props.role)}</span>;
}

export function KindGlyph(props: { kind: NodeKind | 'platform' }) {
  return <span class={['kind', `kind-${props.kind}`]} title={props.kind === 'platform' ? props.kind : t(`common.kind_${props.kind}`)} aria-hidden="true" />;
}

export function Skeleton(props: { rows?: number; height?: number }) {
  return (
    <div class="skeleton-stack" aria-busy="true" aria-label={t('common.loading')}>
      {Array.from({ length: props.rows ?? 3 }, () => (
        <div class="skeleton" style={{ height: `${props.height ?? 56}px` }} />
      ))}
    </div>
  );
}

/** Rendered by <Errored> boundaries; access errors read as boundaries, not crashes. */
export function Boundary(props: { error: unknown; reset?: () => void }) {
  const message = () => (props.error instanceof Error ? props.error.message : String(props.error));
  const denied = () => isRefusal(props.error);
  return (
    <div class="boundary" role="alert">
      <div class="boundary-glyph">
        <Icon name={denied() ? 'lock' : 'x'} size={22} />
      </div>
      <h2>{denied() ? t('common.noAccess') : t('common.somethingWrong')}</h2>
      <p>{message()}</p>
      <div class="row">
        <a class="btn" href="/">
          <Icon name="swap" size={16} /> {t('common.chooseWorkspace')}
        </a>
        <Show when={props.reset && !denied()}>
          <button type="button" class="btn ghost" onClick={() => props.reset!()}>
            {t('common.retry')}
          </button>
        </Show>
      </div>
    </div>
  );
}

/** The Tenantly mark — three nested frames: organization, region, location. */
export function Mark() {
  return (
    <svg class="mark" viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
      <rect x="2" y="2" width="28" height="28" rx="8" class="mark-outer" />
      <rect x="8" y="8" width="16" height="16" rx="5" class="mark-mid" />
      <rect x="13" y="13" width="6" height="6" rx="2" class="mark-core" />
    </svg>
  );
}

const tones: Record<BookingStatus, string> = {
  requested: 'warn',
  confirmed: 'neutral',
  checked_in: 'live',
  completed: 'ok',
  no_show: 'bad',
  cancelled: 'muted',
};

/** A booking's lifecycle state, worded by the tenant's template. */
export function StatusPill(props: { status: BookingStatus; labels: Record<BookingStatus, string> }) {
  return <span class={['status-pill', tones[props.status]]}>{props.labels[props.status]}</span>;
}

const kindLabels: Record<string, MessageKey> = {
  appointment: 'common.offering_appointment',
  class: 'common.offering_class',
  rental: 'common.offering_rental',
  visit: 'common.offering_visit',
  plan: 'common.offering_plan',
};

/** The preset an offering started from. Templates may add their own presets: those show their key (or `label`). */
export function KindBadge(props: { kind: OfferingKind; label?: string }) {
  return (
    <span class={['kind-badge', `k-${props.kind}`]}>
      {props.label ??
        (kindLabels[props.kind] ? t(kindLabels[props.kind]) : props.kind[0].toUpperCase() + props.kind.slice(1))}
    </span>
  );
}

/** Change vs the previous period. `better` says which direction is good. */
export function Delta(props: { now: number; before: number; better?: 'up' | 'down'; unit?: '%' | 'pts' }) {
  const diff = () =>
    props.unit === 'pts' ? props.now - props.before : props.before ? ((props.now - props.before) / props.before) * 100 : 0;
  const good = () => (props.better === 'down' ? diff() < 0 : diff() > 0);
  return (
    <Show when={Math.abs(diff()) >= 0.5} fallback={<span class="delta flat">±0</span>}>
      <span class={['delta', good() ? 'good' : 'bad']}>
        {diff() > 0 ? '▲' : '▼'}{' '}
        {props.unit === 'pts'
          ? t('common.deltaPts', { n: Math.abs(Math.round(diff() * 10) / 10) })
          : `${Math.abs(Math.round(diff() * 10) / 10)}%`}
      </span>
    </Show>
  );
}

/** The booking lifecycle in order, so each state reads as a step (docs/USAGE.md §4.6). */
export function Lifecycle(props: { labels: Record<BookingStatus, string> }) {
  const flow: Array<BookingStatus> = ['requested', 'confirmed', 'checked_in', 'completed'];
  return (
    <ol class="lifecycle" aria-label={t('common.lifecycleLabel')}>
      <For each={flow}>
        {(s, i) => (
          <li>
            <StatusPill status={s} labels={props.labels} />
            <Show when={i() < flow.length - 1}>
              <span class="arrow">→</span>
            </Show>
          </li>
        )}
      </For>
      <li class="side">
        {t('common.lifecycleOr')} <StatusPill status="no_show" labels={props.labels} /> <StatusPill status="cancelled" labels={props.labels} />
      </li>
    </ol>
  );
}

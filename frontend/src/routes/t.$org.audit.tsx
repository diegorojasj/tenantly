import { useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Show } from 'solid-js';

import Icon from '../components/Icon';
import { PageHead, Panel } from '../components/ui';
import { fmtStamp } from '../lib/format';
import { t } from '../lib/i18n';
import { auditQuery, prefetch, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import type { AuditEvent } from '../lib/types';

// The audit trail as a hash-chained ledger: each entry commits to the one
// before it, and the server verifies the whole chain on every read. Filters
// are client-side over the scoped slice — no round trip per keystroke.
export const Route = createFileRoute('/t/$org/audit')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, auditQuery(params.org, deps.scope));
  },
  head: () => ({ meta: [{ title: t('audit.headTitle') }] }),
  component: AuditPage,
});

const categories: Array<AuditEvent['category']> = ['access', 'config', 'billing', 'integration', 'security'];

function AuditPage() {
  const { org, scope } = useTenantScope();
  const audit = useQuery(() => auditQuery(org(), scope()));
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  // Hover shows the entry in its location's own zone (UTC for business-wide entries).
  const zoneOf = (nodeId: string) => ctx.data?.nodes.find((n) => n.id === nodeId)?.tz ?? 'UTC';

  const [active, setActive] = createSignal<Set<string>>(new Set(categories), { name: 'auditCategories' });
  const [text, setText] = createSignal('', { name: 'auditText' });

  const events = createMemo(() => {
    const q = text().trim().toLowerCase();
    return audit.data.events.filter(
      (e) =>
        active().has(e.category) &&
        (!q || `${e.actor} ${e.action} ${e.target} ${e.scopeName} ${e.ip}`.toLowerCase().includes(q)),
    );
  });

  // Day groups, newest first (events already arrive newest first).
  const days = createMemo(() => {
    const groups: Array<[string, Array<AuditEvent>]> = [];
    for (const e of events()) {
      const day = e.at.slice(0, 10);
      if (groups.at(-1)?.[0] === day) groups.at(-1)![1].push(e);
      else groups.push([day, [e]]);
    }
    return groups;
  });

  const toggle = (c: string) =>
    setActive((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });

  const exportCsv = () => {
    const header = 'id,at,actor,action,category,target,scope,ip,hash,prev_hash';
    const quote = (v: string) => `"${v.replaceAll('"', '""')}"`;
    const rows = events().map((e) =>
      [e.id, e.at, e.actor, e.action, e.category, e.target, e.scopeName, e.ip, e.hash, e.prevHash].map(quote).join(','),
    );
    const url = URL.createObjectURL(new Blob([[header, ...rows].join('\n')], { type: 'text/csv' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: `audit-${org()}.csv` });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div class="page">
      <PageHead
        eyebrow={t('audit.eyebrow')}
        title={t('audit.title')}
        lede={t('audit.lede')}
      >
        <span class={['chain', audit.data.chain.intact ? 'ok' : 'broken']}>
          <Icon name={audit.data.chain.intact ? 'link' : 'x'} size={16} />
          {audit.data.chain.intact ? t('audit.chainVerified') : t('audit.chainBroken')} · {t('audit.chainSummary', { count: audit.data.chain.length })}{' '}
          <code>{audit.data.chain.head}</code>
        </span>
      </PageHead>

      <Panel>
        <div class="toolbar">
          <div class="chips" role="group" aria-label={t('audit.categoriesLabel')}>
            <For each={categories}>
              {(c) => (
                <button
                  type="button"
                  class={['chip-toggle', `cat-${c}`, { on: active().has(c) }]}
                  aria-pressed={active().has(c) ? 'true' : 'false'}
                  onClick={() => toggle(c)}
                >
                  <span class={['cat', `cat-${c}`]} /> {t(`audit.cat_${c}`)}
                </button>
              )}
            </For>
          </div>
          <label class="filter">
            <Icon name="search" size={15} />
            <input
              type="search"
              placeholder={t('audit.searchPlaceholder')}
              value={text()}
              onInput={(event) => setText(event.currentTarget.value)}
            />
          </label>
          <button type="button" class="btn ghost" onClick={exportCsv}>
            {t('audit.exportCsv')}
          </button>
        </div>

        <Show when={days().length} fallback={<p class="muted empty">{t('audit.empty')}</p>}>
          <For each={days()}>
            {([day, list]) => (
              <section class="ledger-day">
                <h3>{day}</h3>
                <ol class="ledger">
                  <For each={list}>
                    {(e) => (
                      <li class="ledger-entry">
                        <span class={['cat', `cat-${e.category}`]} />
                        <time datetime={e.at} class="mono muted" title={fmtStamp(e.at, zoneOf(e.scopeId))}>
                          {e.at.slice(11, 16)}
                        </time>
                        <span class="ledger-main">
                          <strong>{e.actor}</strong> <code>{e.action}</code> <span>{e.target}</span>
                          <span class="muted block">
                            {e.scopeName} · {e.ip}
                          </span>
                        </span>
                        <span class="hashes mono" title={t('audit.hashTitle', { prev: e.prevHash, hash: e.hash })}>
                          <span class="muted">{e.prevHash.slice(0, 4)}</span>
                          <Icon name="chevron" size={12} />
                          <span>{e.hash}</span>
                        </span>
                      </li>
                    )}
                  </For>
                </ol>
              </section>
            )}
          </For>
        </Show>
      </Panel>
    </div>
  );
}

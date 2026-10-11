// ⌘K / Ctrl+K / "/" — one keyboard surface for every jump: pages, scopes in
// the current tenant, and other workspaces. Pure client state; nothing here
// fetches — it indexes data the shell already holds.
import { useNavigate } from '@tanstack/solid-router';
import { createMemo, createSignal, For, onSettled, Show } from 'solid-js';

import { t as tr } from '../lib/i18n';
import type { ScopeNode, Workspace } from '../lib/types';
import Icon from './Icon';
import type { IconName } from './Icon';

export interface PageEntry {
  to: string;
  label: string;
  icon: IconName;
}

interface Item {
  id: string;
  group: 'Pages' | 'Scopes' | 'Workspaces';
  label: string;
  hint: string;
  icon: IconName;
  run: () => void;
}

const groupLabels = {
  Pages: 'common.cmdPages',
  Scopes: 'common.cmdScopes',
  Workspaces: 'common.cmdWorkspaces',
} as const;

/** Subsequence match with a bonus for word starts: "nwa" finds "Newark Air". */
function score(query: string, text: string) {
  if (!query) return 1;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  let ti = 0;
  let total = 0;
  for (const ch of q) {
    const found = t.indexOf(ch, ti);
    if (found === -1) return 0;
    total += found === 0 || t[found - 1] === ' ' ? 3 : found === ti ? 2 : 1;
    ti = found + 1;
  }
  return total;
}

export default function CommandBar(props: {
  org: string;
  pages: Array<PageEntry>;
  nodes: Array<ScopeNode>;
  workspaces: Array<Workspace>;
  open: boolean;
  onClose: () => void;
  onOpen: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = createSignal('', { name: 'commandQuery' });
  const [active, setActive] = createSignal(0, { name: 'commandActive' });

  const items = createMemo<Array<Item>>(() => [
    ...props.pages.map((p) => ({
      id: `page:${p.to}`,
      group: 'Pages' as const,
      label: p.label,
      hint: tr('common.cmdGoToPage'),
      icon: p.icon,
      run: () => void navigate({ to: p.to, params: { org: props.org }, search: (prev: object) => prev } as never),
    })),
    ...props.nodes
      .filter((n) => n.reachable)
      .map((n) => ({
        id: `scope:${n.id}`,
        group: 'Scopes' as const,
        label: n.name,
        hint: `${tr(`common.kind_${n.kind}`)} · ${n.code}`,
        icon: 'structure' as const,
        run: () => void navigate({ to: '.', search: { scope: n.id } } as never),
      })),
    ...props.workspaces
      .filter((w) => w.tenant.slug !== props.org)
      .map((w) => ({
        id: `ws:${w.tenant.slug}`,
        group: 'Workspaces' as const,
        label: w.tenant.name,
        hint: tr('common.cmdSwitchWorkspace'),
        icon: 'swap' as const,
        run: () => void navigate({ to: '/t/$org', params: { org: w.tenant.slug } }),
      })),
  ]);

  const results = createMemo(() =>
    items()
      .map((item) => ({ item, s: score(query(), `${item.label} ${item.hint}`) }))
      .filter((r) => r.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 12)
      .map((r) => r.item),
  );

  const choose = (item: Item | undefined) => {
    if (!item) return;
    props.onClose();
    setQuery('');
    item.run();
  };

  // Global shortcut. Registered once the component settles; cleaned on dispose.
  onSettled(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLElement && event.target.closest('input, textarea, select');
      if ((event.key === 'k' && (event.metaKey || event.ctrlKey)) || (event.key === '/' && !typing)) {
        event.preventDefault();
        props.onOpen();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const onKeyDown = (event: KeyboardEvent) => {
    const count = results().length;
    if (event.key === 'Escape') props.onClose();
    else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => (i + 1) % Math.max(count, 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => (i - 1 + count) % Math.max(count, 1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(results()[active()]);
    }
  };

  return (
    <Show when={props.open}>
      <div class="palette-backdrop" onClick={() => props.onClose()}>
        <div
          class="palette"
          role="dialog"
          aria-modal="true"
          aria-label={tr('common.cmdLabel')}
          onClick={(event) => event.stopPropagation()}
        >
          <label class="palette-input">
            <Icon name="search" />
            <input
              ref={(el) => queueMicrotask(() => el.focus())}
              placeholder={tr('common.cmdPlaceholder')}
              value={query()}
              onInput={(event) => {
                setQuery(event.currentTarget.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              role="combobox"
              aria-expanded="true"
              aria-controls="palette-list"
            />
            <kbd>esc</kbd>
          </label>
          <ul id="palette-list" role="listbox">
            <For each={results()} fallback={<li class="palette-empty">{tr('common.cmdNoMatches')}</li>}>
              {(item, i) => (
                <li
                  role="option"
                  aria-selected={i() === active() ? 'true' : 'false'}
                  class={{ active: i() === active() }}
                  onMouseEnter={() => setActive(i())}
                  onClick={() => choose(item)}
                >
                  <Icon name={item.icon} size={16} />
                  <span class="palette-label">{item.label}</span>
                  <span class="palette-hint">{item.hint}</span>
                  <span class="palette-group">{tr(groupLabels[item.group])}</span>
                </li>
              )}
            </For>
          </ul>
        </div>
      </div>
    </Show>
  );
}

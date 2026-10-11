// The scope tree: the business, its groups on the template's levels (any
// depth: area; or region → franchisee), and locations. Picking a node narrows
// every page to that subtree (it rewrites `?scope=`), so the same overview,
// members, config and audit views work at any altitude. Nodes outside the
// viewer's assignment render locked — RBAC made visible, enforced server-side.
import { Link } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Show } from 'solid-js';

import { t } from '../lib/i18n';
import type { ScopeNode } from '../lib/types';
import Icon from './Icon';

export default function ScopeRail(props: {
  nodes: Array<ScopeNode>;
  scopeId: string;
  pathIds: Array<string>;
  onPick?: () => void;
}) {
  const root = createMemo(() => props.nodes.find((n) => n.kind === 'org')!);
  const childrenOf = (id: string) => props.nodes.filter((n) => n.parentId === id);

  // A writable memo: regions on the focused path open whenever focus moves;
  // manual toggles hold until it moves again.
  const [open, setOpen] = createSignal<Set<string>>(() => new Set(props.pathIds), {
    name: 'scopeRailOpen',
  });
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const NodeLink = (p: { node: ScopeNode }) => (
    <Show
      when={p.node.reachable}
      fallback={
        <span class="scope-node locked" title={t('common.scopeLocked')}>
          <span class="scope-name">{p.node.name}</span>
          <Icon name="lock" size={13} />
        </span>
      }
    >
      <Link
        to="."
        search={{ scope: p.node.id }}
        // <Link> takes a plain class string (not Solid's array form), so
        // state rides attributes the stylesheet keys on.
        class="scope-node"
        aria-current={p.node.id === props.scopeId ? 'true' : undefined}
        onClick={() => props.onPick?.()}
      >
        <span class={['status', `status-${p.node.status}`]} aria-label={t(`common.status_${p.node.status}`)} />
        <span class="scope-name">{p.node.name}</span>
        <span class="scope-code">{p.node.code}</span>
      </Link>
    </Show>
  );

  // Locations are leaves, listed before the groups beside them; groups nest as deep as the template's levels.
  const Children = (p: { parentId: string; role: 'tree' | 'group' }) => (
    <ul role={p.role}>
      <For each={childrenOf(p.parentId).filter((n) => n.kind === 'location')}>
        {(location) => (
          <li role="treeitem" class="scope-leaf">
            <NodeLink node={location} />
          </li>
        )}
      </For>
      <For each={childrenOf(p.parentId).filter((n) => n.kind === 'region')}>
        {(group) => (
          <li role="treeitem" aria-expanded={open().has(group.id) ? 'true' : 'false'}>
            <div class="scope-branch">
              <button
                type="button"
                class={['twisty', { open: open().has(group.id) }]}
                aria-label={t('common.scopeToggle', { name: group.name })}
                onClick={() => toggle(group.id)}
              >
                <Icon name="chevron" size={14} />
              </button>
              <NodeLink node={group} />
            </div>
            <Show when={open().has(group.id)}>
              <Children parentId={group.id} role="group" />
            </Show>
          </li>
        )}
      </For>
    </ul>
  );

  return (
    <nav class="scope-rail" aria-label={t('common.scopeNav')}>
      <NodeLink node={root()} />
      <Children parentId={root().id} role="tree" />
    </nav>
  );
}

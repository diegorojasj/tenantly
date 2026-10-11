import { useMutation, useQuery } from '@tanstack/solid-query';
import {
  Link,
  Outlet,
  createFileRoute,
  useLocation,
  useNavigate,
} from '@tanstack/solid-router';
import { createEffect, createSignal, Errored, For, Loading, Show } from 'solid-js';

import CommandBar from '../components/CommandBar';
import Toaster from '../components/Toaster';
import type { PageEntry } from '../components/CommandBar';
import Icon from '../components/Icon';
import LanguageSwitch from '../components/LanguageSwitch';
import ScopeRail from '../components/ScopeRail';
import { Boundary, KindGlyph, Mark, RoleChip, Skeleton } from '../components/ui';
import { logout } from '../lib/auth';
import { t as tr } from '../lib/i18n';
import {
  currentUserQuery,
  prefetch,
  tenantQuery,
  workspacesQuery,
} from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { kindLabel } from '../lib/tree';
import type { Permission, Template, WorkspaceSearch } from '../lib/types';

// The workspace shell. Everything below /t/<org> renders inside it, and the
// `scope` search param it validates is inherited by every child route — one
// definition of "where am I looking" for the whole workspace.
export const Route = createFileRoute('/t/$org')({
  // Every search param in the workspace is declared here, on the parent.
  // Child-declared params broke later async renders after a same-route
  // search change (TanStack Solid 2 RC); one owner avoids it entirely.
  validateSearch: (search: Record<string, unknown>): WorkspaceSearch => {
    const out: WorkspaceSearch = {};
    if (typeof search.scope === 'string' && search.scope) out.scope = search.scope;
    if (typeof search.day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(search.day)) out.day = search.day;
    if (search.range === 'upcoming' || search.range === 'past') out.range = search.range;
    if (Number(search.days) === 7) out.days = 7;
    if (search.tab === 'assets') out.tab = 'assets';
    if (typeof search.customer === 'string' && search.customer) out.customer = search.customer;
    return out;
  },
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, tenantQuery(params.org, deps.scope));
    prefetch(context.queryClient, workspacesQuery());
    prefetch(context.queryClient, currentUserQuery());
  },
  head: ({ params }) => ({ meta: [{ title: `${params.org} · Tenantly` }] }),
  component: TenantLayout,
});

type NavGroup = 'operate' | 'setup' | 'money' | 'admin';
/** A page shows when the role holds ANY of `needs`: it can act there, or must read it for its job. */
type NavPage = PageEntry & { needs: Array<Permission>; exact?: boolean; group: NavGroup };

// Navigation by intent (docs/PRODUCT.md §2) and by job (docs/USAGE.md §1):
// you only see what you can use. Labels come from the tenant's template
// ("Customers", "Bookings"), never hardcoded.
const work: Array<Permission> = ['bookings.manage', 'analytics.view'];
const pagesFor = (t: Template): Array<NavPage> => [
  { to: '/t/$org', label: tr('shell.navToday'), icon: 'overview', exact: true, group: 'operate', needs: work },
  { to: '/t/$org/calendar', label: tr('shell.navCalendar'), icon: 'calendar', group: 'operate', needs: work },
  { to: '/t/$org/bookings', label: t.terms.bookings, icon: 'pipeline', group: 'operate', needs: work },
  { to: '/t/$org/customers', label: t.terms.customers, icon: 'users', group: 'operate', needs: work },
  { to: '/t/$org/catalog', label: tr('shell.navCatalog'), icon: 'tag', group: 'setup', needs: ['pricing.write', 'analytics.view'] },
  { to: '/t/$org/resources', label: tr('shell.navResources'), icon: 'integrations', group: 'setup', needs: ['config.write', 'analytics.view'] },
  { to: '/t/$org/payments', label: tr('shell.navPayments'), icon: 'billing', group: 'money', needs: ['payments.collect', 'analytics.view'] },
  { to: '/t/$org/insights', label: tr('shell.navInsights'), icon: 'chart', group: 'money', needs: ['analytics.view'] },
  { to: '/t/$org/structure', label: t.terms.locations, icon: 'structure', group: 'admin', needs: ['tenant.manage', 'roles.assign'] },
  { to: '/t/$org/access', label: tr('shell.navAccess'), icon: 'access', group: 'admin', needs: ['members.invite', 'roles.assign'] },
  { to: '/t/$org/config', label: tr('shell.navConfig'), icon: 'config', group: 'admin', needs: ['config.write', 'pricing.write'] },
  { to: '/t/$org/settings', label: tr('shell.navSettings'), icon: 'config', group: 'admin', needs: ['tenant.manage'] },
  { to: '/t/$org/audit', label: tr('shell.navAudit'), icon: 'audit', group: 'admin', needs: ['audit.view'] },
  { to: '/t/$org/billing', label: tr('shell.navBilling'), icon: 'shield', group: 'admin', needs: ['billing.manage', 'audit.view'] },
];

/** Where a role starts (docs/USAGE.md §1): the desk on Today, analysts on Insights, auditors on the trail. */
const homeFor = (permissions: Array<Permission>) =>
  permissions.includes('bookings.manage')
    ? '/t/$org'
    : permissions.includes('analytics.view')
      ? '/t/$org/insights'
      : '/t/$org/audit';

// Only the first entry into a workspace is redirected, so Today stays reachable.
const landed = new Set<string>();

const groups = (): Array<[NavGroup, string | null]> => [
  ['operate', null],
  ['setup', tr('shell.groupSetup')],
  ['money', tr('shell.groupMoney')],
  ['admin', tr('shell.groupAdmin')],
];

function TenantLayout() {
  return (
    <Errored
      fallback={(error) => (
        <main class="gateway">
          <Boundary error={error()} />
        </main>
      )}
    >
      <Loading fallback={<ShellSkeleton />}>
        <Shell />
      </Loading>
    </Errored>
  );
}

function Shell() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const me = useQuery(currentUserQuery);
  const workspaces = useQuery(workspacesQuery);
  const navigate = useNavigate();

  const [paletteOpen, setPaletteOpen] = createSignal(false, { name: 'paletteOpen' });
  const [navOpen, setNavOpen] = createSignal(false, { name: 'navOpen' });

  const signOut = useMutation(() => ({
    mutationFn: () => logout(),
    onSuccess: () => navigate({ to: '/' }),
  }));

  const visiblePages = () =>
    pagesFor(ctx.data.tenant.template).filter((p) => p.needs.some((n) => ctx.data.role.permissions.includes(n)));

  // Land each role on the page for its job, once per workspace visit.
  const location = useLocation();
  createEffect(
    () => ({ path: location().pathname, home: homeFor(ctx.data.role.permissions), slug: org() }),
    ({ path, home, slug }) => {
      if (landed.has(slug)) return;
      landed.add(slug);
      if (home !== '/t/$org' && path.replace(/\/$/, '') === `/t/${slug}`) {
        void navigate({ to: home as '/t/$org', params: { org: slug }, search: searchFor(), replace: true });
      }
    },
  );
  const searchFor = () => (scope() ? { scope: scope() } : {});
  const NavLink = (p: { page: NavPage }) => (
    <Link
      to={p.page.to as '/t/$org'}
      params={{ org: org() }}
      search={searchFor()}
      activeOptions={{ exact: p.page.exact, includeSearch: false }}
      onClick={() => setNavOpen(false)}
    >
      <Icon name={p.page.icon} />
      {p.page.label}
    </Link>
  );
  // Ancestors above the viewer's home scope show in the lens but can't be opened.
  const reachable = (id: string) => ctx.data.nodes.find((n) => n.id === id)?.reachable ?? false;

  return (
    <div
      class={['shell', { 'nav-open': navOpen() }]}
      style={{ '--hue': String(ctx.data.tenant.hue) }}
    >
      <aside class="rail">
        <div class="rail-head">
          <a href="/" class="brand" aria-label={tr('shell.allWorkspaces')}>
            <Mark />
          </a>
          <button type="button" class="tenant-switch" onClick={() => setPaletteOpen(true)}>
            <Show when={ctx.data.tenant.logoUrl}>
              {(src) => <img class="tenant-logo" src={src()} alt="" width="28" height="28" />}
            </Show>
            <span class="tenant-name">{ctx.data.tenant.name}</span>
            <span class="tenant-meta">
              {ctx.data.tenant.industry ? `${ctx.data.tenant.industry} · ` : ''}
              {ctx.data.tenant.plan}
            </span>
            <Icon name="swap" size={16} />
          </button>
        </div>

        <nav class="rail-nav" aria-label={tr('shell.navLabel')}>
          <For each={groups()}>
            {([group, label]) => (
              <Show when={visiblePages().some((p) => p.group === group)}>
                <Show when={label}>
                  <p class="rail-label nav-group">{label}</p>
                </Show>
                <For each={visiblePages().filter((p) => p.group === group)}>{(page) => <NavLink page={page} />}</For>
              </Show>
            )}
          </For>
        </nav>

        <div class="rail-section">
          <p class="rail-label">{tr('shell.scope')}</p>
          <ScopeRail
            nodes={ctx.data.nodes}
            scopeId={ctx.data.scopeId}
            pathIds={ctx.data.path.map((n) => n.id)}
            onPick={() => setNavOpen(false)}
          />
        </div>

        <div class="isolation" title={tr('shell.isolationTitle')}>
          <Icon name="shield" size={16} />
          <dl>
            <dt>{tr('shell.tenantKey')}</dt>
            <dd class="mono">{ctx.data.tenant.tenantKey}</dd>
            <dt>{tr('shell.residency')}</dt>
            <dd class="mono">{ctx.data.tenant.residency}</dd>
            <dt>{tr('shell.identity')}</dt>
            <dd>{ctx.data.tenant.idp}</dd>
          </dl>
        </div>
      </aside>

      <div class="stage" data-tenant={ctx.data.tenant.name}>
        <header class="topbar">
          <button
            type="button"
            class="icon-btn menu-btn"
            aria-label={tr('shell.toggleNav')}
            aria-expanded={navOpen() ? 'true' : 'false'}
            onClick={() => setNavOpen((v) => !v)}
          >
            <Icon name="structure" />
          </button>

          <ol class="lens" aria-label={tr('shell.currentScope')}>
            <For each={ctx.data.path}>
              {(node, i) => (
                <li>
                  <Show
                    when={i() < ctx.data.path.length - 1 && reachable(node.id)}
                    fallback={
                      <span class={['lens-step', { current: i() === ctx.data.path.length - 1 }]}>
                        <KindGlyph kind={node.kind} />
                        <span class="lens-kind">{kindLabel(ctx.data.tenant.template, node)}</span>
                        <span class="lens-name">{node.name}</span>
                      </span>
                    }
                  >
                    <Link to="." search={{ scope: node.id }} class="lens-step" title={tr('shell.widenTo', { name: node.name })}>
                      <KindGlyph kind={node.kind} />
                      <span class="lens-kind">{kindLabel(ctx.data.tenant.template, node)}</span>
                      <span class="lens-name">{node.name}</span>
                    </Link>
                  </Show>
                </li>
              )}
            </For>
          </ol>

          <button type="button" class="search-btn" onClick={() => setPaletteOpen(true)}>
            <Icon name="search" size={16} />
            <span>{tr('shell.jumpTo')}</span>
            <kbd>⌘K</kbd>
          </button>

          <LanguageSwitch />

          <Loading fallback={<span class="avatar ghost" />}>
            <Show when={me.data}>
              {(viewer) => (
                <div class="who">
                  <span class="avatar" title={viewer()?.email}>
                    {viewer()?.initials}
                  </span>
                  <span class="who-main">
                    <strong>{viewer()?.name}</strong>
                    <RoleChip role={ctx.data.role.id} label={ctx.data.role.label} />
                  </span>
                  <button
                    type="button"
                    class="icon-btn"
                    aria-label={tr('shell.signOut')}
                    title={tr('shell.signOut')}
                    disabled={signOut.isPending}
                    onClick={() => signOut.mutate()}
                  >
                    <Icon name="logout" />
                  </button>
                </div>
              )}
            </Show>
          </Loading>
        </header>

        {/* One boundary pair for every page. A page that hit its access
            boundary resets when you navigate away (PageBoundary), rather than
            remounting the boundaries per path — remounting them under a
            router transition could leave the next page hidden. */}
        <Errored fallback={(error, reset) => <PageBoundary error={error()} reset={reset} />}>
          <Loading fallback={<div class="page"><Skeleton rows={4} height={88} /></div>}>
            <Outlet />
          </Loading>
        </Errored>
      </div>

      <Toaster />

      <Loading fallback={null}>
        <CommandBar
          org={org()}
          pages={visiblePages()}
          nodes={ctx.data.nodes}
          workspaces={workspaces.data ?? []}
          open={paletteOpen()}
          onOpen={() => setPaletteOpen(true)}
          onClose={() => setPaletteOpen(false)}
        />
      </Loading>
    </div>
  );
}

/** The page-level error view; clears itself as soon as the path changes. */
function PageBoundary(props: { error: unknown; reset: () => void }) {
  const location = useLocation();
  createEffect(
    () => location().pathname,
    () => props.reset(),
    { defer: true },
  );
  return <Boundary error={props.error} reset={props.reset} />;
}

function ShellSkeleton() {
  return (
    <div class="shell">
      <aside class="rail">
        <Skeleton rows={8} height={28} />
      </aside>
      <div class="stage">
        <div class="page">
          <Skeleton rows={4} height={88} />
        </div>
      </div>
    </div>
  );
}

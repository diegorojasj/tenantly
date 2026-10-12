import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { For, Loading, Show } from 'solid-js';

import Icon from '../components/Icon';
import LanguageSwitch from '../components/LanguageSwitch';
import { Mark, RoleChip, Skeleton } from '../components/ui';
import { acceptInvite, logout, signIn } from '../lib/auth';
import { t } from '../lib/i18n';
import { currentUserQuery, workspacesQuery } from '../lib/queries';

// The gateway: sign in, then open a workspace. There's no sign-up and no
// "create a business": Tenantly admins create owners with their businesses,
// and owners create their team's accounts. Accounts and businesses live in
// the identity service; nothing here is demo data.
export const Route = createFileRoute('/')({
  // `?invite=` comes from an invite link; signing in with it joins that business.
  validateSearch: (search: Record<string, unknown>): { invite?: string } =>
    typeof search.invite === 'string' && search.invite ? { invite: search.invite } : {},
  head: () => ({ meta: [{ title: `${t('gateway.headTitle')} · Tenantly` }] }),
  component: Gateway,
});

function Gateway() {
  const me = useQuery(currentUserQuery);

  return (
    <main class="gateway">
      <div class="gateway-mark">
        <Mark /> <span>Tenantly</span>
      </div>
      <Loading
        fallback={
          <div class="gateway-card">
            <Skeleton rows={4} />
          </div>
        }
      >
        <Show when={me.data} fallback={<Account />}>
          {(viewer) => <Workspaces name={viewer()?.name ?? ''} />}
        </Show>
      </Loading>
      <p class="gateway-foot">{t('gateway.foot')}</p>
      <LanguageSwitch />
    </main>
  );
}

function Account() {
  const search = Route.useSearch();
  const enter = useMutation(() => ({
    mutationFn: (input: { email: string; password: string }) => {
      // Server function args must be strictly JSON-safe: an `invite: undefined`
      // key is rejected, so only include it when the link carried one.
      const invite = search().invite;
      return signIn({ ...input, ...(invite ? { invite } : {}) });
    },
  }));

  return (
    <section class="gateway-card narrow-form">
      <p class="eyebrow">{t('gateway.welcomeBack')}</p>
      <h1>{t('gateway.signIn')}</h1>
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
          <input type="email" name="email" autocomplete="email" required />
        </label>
        <label>
          <span class="form-label">{t('gateway.password')}</span>
          <input type="password" name="password" autocomplete="current-password" required />
        </label>
        <Show when={enter.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={enter.isPending}>
          {t('gateway.signIn')}
        </button>
      </form>
      <p class="muted hint">{search().invite ? t('gateway.inviteHint') : t('gateway.noAccountHint')}</p>
    </section>
  );
}

function Workspaces(props: { name: string }) {
  const search = Route.useSearch();
  const workspaces = useQuery(workspacesQuery);
  const join = useMutation(() => ({ mutationFn: (invite: string) => acceptInvite(invite) }));
  const signOut = useMutation(() => ({ mutationFn: () => logout() }));

  return (
    <section class="gateway-card">
      <p class="eyebrow">{t('gateway.greeting', { name: props.name.split(' ')[0] })}</p>
      <Show when={search().invite && !join.isSuccess && search().invite}>
        {(invite) => (
          <div class="form">
            <p>{t('gateway.invited')}</p>
            <Show when={join.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
            <button type="button" class="btn" disabled={join.isPending} onClick={() => join.mutate(invite())}>
              {t('gateway.acceptInvite')}
            </button>
          </div>
        )}
      </Show>
      <Show
        when={workspaces.data.length}
        fallback={
          <>
            <h1>{t('gateway.noWorkspaceTitle')}</h1>
            <p class="lede">{t('gateway.noWorkspaceLede')}</p>
          </>
        }
      >
        <h1>{t('gateway.pickWorkspace')}</h1>
        <ul class="workspace-list">
          <For each={workspaces.data}>
            {(ws) => (
              <li>
                <Link
                  to="/t/$org"
                  params={{ org: ws.tenant.slug }}
                  class="workspace"
                  style={{ '--hue': String(ws.tenant.hue) }}
                >
                  <span class="workspace-badge">
                    {ws.tenant.name
                      .split(' ')
                      .map((word) => word[0])
                      .join('')
                      .slice(0, 3)}
                  </span>
                  <span class="workspace-main">
                    <strong>{ws.tenant.name}</strong>
                    <Show when={ws.tenant.industry}>
                      <span>{ws.tenant.industry}</span>
                    </Show>
                  </span>
                  <span class="workspace-scope">
                    <RoleChip role={ws.role} label={ws.roleLabel} />
                    <span>{ws.scopeName}</span>
                  </span>
                  <Icon name="chevron" />
                </Link>
              </li>
            )}
          </For>
        </ul>
      </Show>
      <button type="button" class="link-btn signout" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
        <Icon name="logout" size={14} /> {t('gateway.signOut')}
      </button>
    </section>
  );
}

import { useMutation, useQuery } from '@tanstack/solid-query';
import { Link, createFileRoute } from '@tanstack/solid-router';
import { createSignal, For, Loading, Show } from 'solid-js';

import Icon from '../components/Icon';
import LanguageSwitch from '../components/LanguageSwitch';
import { Mark, RoleChip, Skeleton } from '../components/ui';
import { acceptInvite, createWorkspace, logout, signIn, signUp } from '../lib/auth';
import { t } from '../lib/i18n';
import { currentUserQuery, workspacesQuery } from '../lib/queries';

// The gateway: sign in (or create an account), then open a workspace — or
// create the first one. Accounts and businesses live in the identity
// service; nothing here is demo data.
export const Route = createFileRoute('/')({
  // `?invite=` comes from an invite link; signing in or up with it joins that business.
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
  const [mode, setMode] = createSignal<'in' | 'up'>(search().invite ? 'up' : 'in', { name: 'accountMode' });
  const enter = useMutation(() => ({
    mutationFn: (input: { name: string; email: string; password: string }) => {
      // Server function args must be strictly JSON-safe: an `invite: undefined`
      // key is rejected, so only include it when the link carried one.
      const invite = search().invite;
      const extra = invite ? { invite } : {};
      return mode() === 'up'
        ? signUp({ ...input, ...extra })
        : signIn({ email: input.email, password: input.password, ...extra });
    },
  }));

  return (
    <section class="gateway-card narrow-form">
      <p class="eyebrow">{mode() === 'in' ? t('gateway.welcomeBack') : t('gateway.getStarted')}</p>
      <h1>{mode() === 'in' ? t('gateway.signIn') : t('gateway.createYourAccount')}</h1>
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          enter.mutate({
            name: String(d.get('name') ?? ''),
            email: String(d.get('email')),
            password: String(d.get('password')),
          });
        }}
      >
        <Show when={mode() === 'up'}>
          <label>
            <span class="form-label">{t('gateway.yourName')}</span>
            <input type="text" name="name" autocomplete="name" required minlength="2" />
          </label>
        </Show>
        <label>
          <span class="form-label">{t('gateway.email')}</span>
          <input type="email" name="email" autocomplete="email" required />
        </label>
        <label>
          <span class="form-label">{t('gateway.password')}</span>
          <input
            type="password"
            name="password"
            autocomplete={mode() === 'up' ? 'new-password' : 'current-password'}
            required
            minlength={mode() === 'up' ? 8 : 1}
          />
          <Show when={mode() === 'up'}>
            <span class="muted hint">{t('gateway.passwordHint')}</span>
          </Show>
        </label>
        <Show when={enter.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={enter.isPending}>
          {mode() === 'in' ? t('gateway.signIn') : t('gateway.createAccount')}
        </button>
      </form>
      <p class="switch-mode">
        {mode() === 'in' ? t('gateway.newHere') : t('gateway.haveAccount')}{' '}
        <button type="button" class="link-btn" onClick={() => setMode(mode() === 'in' ? 'up' : 'in')}>
          {mode() === 'in' ? t('gateway.createAnAccount') : t('gateway.signIn')}
        </button>
      </p>
      <p class="muted hint">
        {search().invite
          ? t('gateway.inviteHint')
          : t('gateway.invitedHint')}
      </p>
    </section>
  );
}

function Workspaces(props: { name: string }) {
  const search = Route.useSearch();
  const workspaces = useQuery(workspacesQuery);
  const join = useMutation(() => ({ mutationFn: (invite: string) => acceptInvite(invite) }));
  const signOut = useMutation(() => ({ mutationFn: () => logout() }));
  const [creating, setCreating] = createSignal(false, { name: 'creatingWorkspace' });

  return (
    <section class="gateway-card">
      <Show
        when={!creating()}
        fallback={<CreateBusiness onCancel={workspaces.data.length ? () => setCreating(false) : undefined} />}
      >
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
              <h1>{t('gateway.setUpTitle')}</h1>
              <p class="lede">{t('gateway.setUpLede')}</p>
              <CreateBusiness />
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
          <button type="button" class="btn ghost" onClick={() => setCreating(true)}>
            <Icon name="plus" size={16} /> {t('gateway.createAnother')}
          </button>
        </Show>
      </Show>
      <button type="button" class="link-btn signout" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
        <Icon name="logout" size={14} /> {t('gateway.signOut')}
      </button>
    </section>
  );
}

function CreateBusiness(props: { onCancel?: () => void }) {
  const create = useMutation(() => ({
    mutationFn: (input: { name: string; industry: string; locationName: string }) => createWorkspace(input),
    // A full load into the new workspace: it happens once per business, and
    // it starts the shell from a clean slate instead of morphing the gateway
    // (a client-side hop here could stall in the router's transition).
    onSuccess: (tenant) => window.location.assign(`/t/${tenant.slug}`),
  }));

  // Every business starts from the same template: what it sells (appointments,
  // classes, rentals, visits, plans) is chosen later, one offering at a time.
  return (
    <form
      class="form create-business"
      onSubmit={(event) => {
        event.preventDefault();
        const d = new FormData(event.currentTarget);
        create.mutate({
          name: String(d.get('name')),
          industry: String(d.get('industry') ?? ''),
          locationName: String(d.get('location')),
        });
      }}
    >
      <label>
        <span class="form-label">{t('gateway.businessName')}</span>
        <input type="text" name="name" required minlength="2" placeholder={t('gateway.businessNamePlaceholder')} />
      </label>
      <label>
        <span class="form-label">{t('gateway.industry')}</span>
        <input type="text" name="industry" placeholder={t('gateway.industryPlaceholder')} />
      </label>
      <label>
        <span class="form-label">{t('gateway.firstLocation')}</span>
        <input type="text" name="location" required minlength="2" placeholder={t('gateway.firstLocationPlaceholder')} />
        <span class="muted hint">{t('gateway.moreLocationsLater')}</span>
      </label>
      <Show when={create.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      <div class="row start">
        <button type="submit" class="btn" disabled={create.isPending}>
          {t('gateway.createBusiness')}
        </button>
        <Show when={props.onCancel}>
          <button type="button" class="btn ghost" onClick={() => props.onCancel!()}>
            {t('gateway.cancel')}
          </button>
        </Show>
      </div>
    </form>
  );
}

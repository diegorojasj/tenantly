import { useMutation, useQuery } from '@tanstack/solid-query';
import { createFileRoute } from '@tanstack/solid-router';
import { createMemo, createSignal, For, Show } from 'solid-js';

import ConfirmButton from '../components/ConfirmButton';
import Icon from '../components/Icon';
import { PageHead, Panel, RoleChip } from '../components/ui';
import { fmtAgo } from '../lib/format';
import { t } from '../lib/i18n';
import { membersQuery, prefetch, rolesQuery, tenantQuery } from '../lib/queries';
import { useTenantScope } from '../lib/scope';
import { notify } from '../lib/toast';
import { changeRole, createRole, deleteRole, inviteMember, updateRole } from '../lib/tenancy';
import { placeLabel } from '../lib/tree';
import type { Member, Permission, Role, RoleId, ScopeNode, Template } from '../lib/types';

export const Route = createFileRoute('/t/$org/access')({
  loaderDeps: ({ search }) => ({ scope: search.scope ?? '' }),
  loader: ({ context, params, deps }) => {
    prefetch(context.queryClient, membersQuery(params.org, deps.scope));
    prefetch(context.queryClient, rolesQuery(params.org));
  },
  head: () => ({ meta: [{ title: t('access.pageTitle') }] }),
  component: AccessPage,
});

function AccessPage() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  const members = useQuery(() => membersQuery(org(), scope()));
  const catalog = useQuery(() => rolesQuery(org()));
  const [inviting, setInviting] = createSignal(false, { name: 'inviting' });
  /** The role being edited: a key, or 'new'. */
  const [editing, setEditing] = createSignal<RoleId | null>(null, { name: 'editingRole' });
  const mine = () => ctx.data.role.permissions;
  const labelOf = (id: RoleId) => catalog.data.roles.find((r) => r.id === id)?.label;
  // Nobody edits the owner role, their own role, or a role that can do more than theirs (identity enforces the same).
  const editable = (role: Role) =>
    catalog.data.canEdit && role.id !== 'owner' && role.id !== ctx.data.role.id && role.permissions.every((p) => mine().includes(p));

  const [filter, setFilter] = createSignal('', { name: 'memberFilter' });
  const visible = createMemo(() => {
    const q = filter().trim().toLowerCase();
    const rows = members.data.direct;
    return q
      ? rows.filter((m) => `${m.name} ${m.email} ${m.role} ${m.scopePath}`.toLowerCase().includes(q))
      : rows;
  });

  const assign = useMutation(() => ({
    mutationFn: (input: { memberId: string; role: RoleId }) => changeRole({ org: org(), ...input }),
    onSuccess: (_r, input) => {
      const who = members.data.direct.find((m) => m.id === input.memberId)?.name ?? t('access.memberFallback');
      notify(t('access.toastAssigned', { who, role: catalog.data.roles.find((r) => r.id === input.role)?.label ?? input.role }));
    },
  }));

  return (
    <div class="page">
      <PageHead
        eyebrow={t('access.eyebrow', { place: ctx.data.path.at(-1)!.name })}
        title={t('access.title')}
        lede={t('access.lede')}
      >
        <div class="posture">
          <span>
            <strong>{members.data.seats}</strong> {t('access.seats', { count: members.data.seats })}
          </span>
        </div>
        <Show when={members.data.canInvite}>
          <button type="button" class="btn" onClick={() => setInviting(true)}>
            <Icon name="plus" size={16} /> {t('access.inviteButton')}
          </button>
        </Show>
      </PageHead>

      <Panel
        title={t('access.assignedHere', { count: members.data.direct.length })}
        icon="access"
        aside={
          <label class="filter">
            <Icon name="search" size={15} />
            <input
              type="search"
              placeholder={t('access.filterPlaceholder')}
              value={filter()}
              onInput={(event) => setFilter(event.currentTarget.value)}
            />
          </label>
        }
      >
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>{t('access.colMember')}</th>
                <th>{t('access.colRole')}</th>
                <th>{t('access.colScope')}</th>
                <th>{t('access.colStatus')}</th>
                <th>{t('access.colLastSeen')}</th>
              </tr>
            </thead>
            <tbody>
              <For each={visible()} fallback={<tr><td colspan="5" class="muted">{t('access.noMatches')}</td></tr>}>
                {(m) => (
                  <MemberRow
                    member={m}
                    editable={members.data.canAssign && m.userId !== members.data.viewerId}
                    roles={catalog.data.roles.map((r) => ({ id: r.id, label: r.label }))}
                    pending={assign.isPending && assign.variables?.memberId === m.id}
                    onAssign={(role) => assign.mutate({ memberId: m.id, role })}
                  />
                )}
              </For>
            </tbody>
          </table>
        </div>
        <Show when={assign.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
      </Panel>

      <Show when={members.data.inherited.length}>
        <Panel title={t('access.inheritedTitle')} icon="structure">
          <ul class="inherited">
            <For each={members.data.inherited}>
              {(m) => (
                <li>
                  <span class="avatar sm">{m.name.split(' ').map((p) => p[0]).join('')}</span>
                  <span>{m.name}</span>
                  <RoleChip role={m.role} label={labelOf(m.role)} />
                  <span class="muted">{t('access.via', { path: m.scopePath })}</span>
                </li>
              )}
            </For>
          </ul>
        </Panel>
      </Show>

      <Panel
        title={t('access.matrixTitle')}
        icon="shield"
        aside={
          <Show when={catalog.data.canEdit} fallback={<span class="muted">{t('access.yourRoleHighlighted')}</span>}>
            <button type="button" class="btn small" onClick={() => setEditing('new')}>
              <Icon name="plus" size={14} /> {t('access.newRole')}
            </button>
          </Show>
        }
      >
        <div class="table-wrap">
          <table class="matrix">
            <thead>
              <tr>
                <th>{t('access.colPermission')}</th>
                <For each={catalog.data.roles}>
                  {(role) => (
                    <th class={{ mine: role.id === ctx.data.role.id }} title={role.summary}>
                      {role.label}
                      <Show when={!role.builtin}>
                        <span class="muted block">{t('access.custom')}</span>
                      </Show>
                      <Show when={editable(role)}>
                        <button type="button" class="btn small ghost" onClick={() => setEditing(role.id)}>
                          {t('access.edit')}
                        </button>
                      </Show>
                    </th>
                  )}
                </For>
              </tr>
            </thead>
            <tbody>
              <For each={catalog.data.permissions}>
                {([perm, label]) => (
                  <tr>
                    <th scope="row">
                      {label} <code>{perm}</code>
                    </th>
                    <For each={catalog.data.roles}>
                      {(role) => (
                        <td class={{ mine: role.id === ctx.data.role.id }}>
                          <Show when={role.permissions.includes(perm)} fallback={<span class="no">·</span>}>
                            <span class="yes">
                              <Icon name="check" size={15} label={t('access.granted')} />
                            </span>
                          </Show>
                        </td>
                      )}
                    </For>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Panel>
      <Show when={editing()}>
        {(key) => (
          <RoleEditor
            org={org()}
            role={catalog.data.roles.find((r) => r.id === key())}
            permissions={catalog.data.permissions}
            mine={mine().filter((p) => !catalog.data.ownerOnly.includes(p))}
            onClose={() => setEditing(null)}
          />
        )}
      </Show>
      <Show when={inviting()}>
        <InviteDrawer
          org={org()}
          template={ctx.data.tenant.template}
          roles={catalog.data.roles.filter((r) => r.id !== 'owner' || ctx.data.role.id === 'owner')}
          places={ctx.data.nodes.filter((n) => n.reachable)}
          defaultScope={ctx.data.scopeId}
          canCreateAccounts={members.data.canCreateAccounts}
          onClose={() => setInviting(false)}
        />
      </Show>
    </div>
  );
}

function MemberRow(props: {
  member: Member;
  editable: boolean;
  roles: Array<{ id: RoleId; label: string }>;
  pending: boolean;
  onAssign: (role: RoleId) => void;
}) {
  return (
    <tr class={{ dim: props.member.status !== 'active' }}>
      <td>
        <div class="person">
          <span class="avatar sm">{props.member.name.split(' ').map((p) => p[0]).join('')}</span>
          <span>
            <strong>{props.member.name}</strong>
            <span class="muted block">{props.member.email}</span>
          </span>
          <Show when={props.member.status !== 'active'}>
            <span class="pill neutral">{t(`access.state_${props.member.status}`)}</span>
          </Show>
        </div>
      </td>
      <td>
        <Show
          when={props.editable}
          fallback={<RoleChip role={props.member.role} label={props.roles.find((r) => r.id === props.member.role)?.label} />}
        >
          <select
            class="role-select"
            aria-label={t('access.roleFor', { name: props.member.name })}
            value={props.member.role}
            disabled={props.pending}
            onChange={(event) => props.onAssign(event.currentTarget.value as RoleId)}
          >
            <For each={props.roles}>{(r) => <option value={r.id}>{r.label}</option>}</For>
          </select>
        </Show>
      </td>
      <td class="muted">{props.member.scopePath}</td>
      <td>
        <span class={['pill', props.member.status === 'active' ? 'ok' : 'warn']}>
          {props.member.status === 'invited'
            ? t('access.statusInvited')
            : props.member.status === 'active'
              ? t('access.statusActive')
              : t('access.statusSuspended')}
        </span>
      </td>
      <td class="muted">{props.member.lastSeen ? fmtAgo(props.member.lastSeen) : t('access.notYet')}</td>
    </tr>
  );
}

/**
 * Adds someone to the team. An existing Tenantly account gets an invite link; anyone else gets an
 * account the owner creates here (name and first password), on the team at once and under the
 * business's plan. Only the owner sees those fields: nobody else creates accounts.
 */
function InviteDrawer(props: {
  org: string;
  template: Template;
  roles: Array<{ id: RoleId; label: string; summary: string }>;
  places: Array<ScopeNode>;
  defaultScope: string;
  canCreateAccounts: boolean;
  onClose: () => void;
}) {
  // The desk lead when the business still has that role; else its least powerful listed one.
  const [roleId, setRoleId] = createSignal<RoleId>(
    () => props.roles.find((r) => r.id === 'location_manager')?.id ?? props.roles.at(-1)?.id ?? '',
    { name: 'inviteRole' },
  );
  const [done, setDone] = createSignal<{ email: string; url: string | null } | null>(null, { name: 'inviteDone' });
  const invite = useMutation(() => ({
    // `respond()` sends its value as the body, so the envelope's value is what arrives here.
    mutationFn: (input: { email: string; role: RoleId; scopeId: string; name?: string; password?: string }) =>
      inviteMember({ org: props.org, ...input }) as unknown as Promise<{ invite?: string; account?: string }>,
    onSuccess: (result, input) => {
      if (result.invite) {
        // No email delivery yet: the inviter hands the link over themselves.
        setDone({ email: input.email, url: `${location.origin}/?invite=${encodeURIComponent(result.invite)}` });
        notify(t('access.toastInviteCreated', { email: input.email }));
      } else {
        setDone({ email: input.email, url: null });
        notify(t('access.toastAccountCreated', { email: input.email }));
      }
    },
  }));
  return (
    <aside class="drawer" aria-label={t('access.inviteButton')}>
      <header class="drawer-head">
        <h2>{t('access.inviteButton')}</h2>
        <button type="button" class="icon-btn" aria-label={t('access.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>
      <Show when={done()}>
        {(sent) => (
          <div class="form">
            <Show
              when={sent().url}
              fallback={
                <p>
                  {t('access.accountCreatedBefore')} <strong>{sent().email}</strong>
                  {t('access.accountCreatedAfter', { address: location.origin })}
                </p>
              }
            >
              {(url) => (
                <>
                  <p>
                    {t('access.inviteSentBefore')} <strong>{sent().email}</strong>
                    {t('access.inviteSentAfter')}
                  </p>
                  <input type="text" readonly value={url()} aria-label={t('access.inviteLink')} onFocus={(e) => e.currentTarget.select()} />
                  <button
                    type="button"
                    class="btn"
                    onClick={() => navigator.clipboard.writeText(url()).then(() => notify(t('access.toastLinkCopied')))}
                  >
                    {t('access.copyLink')}
                  </button>
                </>
              )}
            </Show>
            <button type="button" class="btn ghost" onClick={() => props.onClose()}>
              {t('access.done')}
            </button>
          </div>
        )}
      </Show>
      <form
        class="form"
        hidden={!!done()}
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          const name = String(d.get('name') ?? '').trim();
          const password = String(d.get('password') ?? '');
          // Server function args must be JSON-safe: only send the account fields when given.
          invite.mutate({
            email: String(d.get('email')),
            role: roleId(),
            scopeId: String(d.get('scope')),
            ...(name ? { name } : {}),
            ...(password ? { password } : {}),
          });
        }}
      >
        <label>
          <span class="form-label">{t('access.email')}</span>
          <input type="email" name="email" required />
        </label>
        <Show when={props.canCreateAccounts} fallback={<p class="muted hint">{t('access.inviteOnlyHint')}</p>}>
          <fieldset class="form">
            <legend class="form-label">{t('access.newAccount')}</legend>
            <label>
              <span class="form-label">{t('access.name')}</span>
              <input type="text" name="name" autocomplete="off" maxlength="120" />
            </label>
            <label>
              <span class="form-label">{t('access.firstPassword')}</span>
              <input type="password" name="password" autocomplete="new-password" minlength="8" />
            </label>
            <span class="muted hint">{t('access.newAccountHint')}</span>
          </fieldset>
        </Show>
        <label>
          <span class="form-label">{t('access.role')}</span>
          <select value={roleId()} onChange={(event) => setRoleId(event.currentTarget.value as RoleId)}>
            <For each={props.roles}>{(r) => <option value={r.id}>{r.label}</option>}</For>
          </select>
          <span class="muted hint">{props.roles.find((r) => r.id === roleId())?.summary}</span>
        </label>
        <label>
          <span class="form-label">{t('access.whereTheyWork')}</span>
          <select name="scope" value={props.defaultScope}>
            <For each={props.places}>
              {(n) => (
                <option value={n.id}>{placeLabel(props.template, n)}</option>
              )}
            </For>
          </select>
          <span class="muted hint">{t('access.whereHint')}</span>
        </label>
        <Show when={invite.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={invite.isPending}>
          {t('access.sendInvite')}
        </button>
      </form>
    </aside>
  );
}

/** Create or edit a role of the business. Only permissions the editor holds can be granted. */
function RoleEditor(props: {
  org: string;
  role: Role | undefined;
  permissions: Array<[Permission, string]>;
  mine: Array<Permission>;
  onClose: () => void;
}) {
  const save = useMutation(() => ({
    mutationFn: (input: { label: string; summary: string; permissions: Array<Permission> }) =>
      props.role ? updateRole({ org: props.org, key: props.role.id, ...input }) : createRole({ org: props.org, ...input }),
    onSuccess: (_r, input) => {
      notify(t(props.role ? 'access.toastRoleSaved' : 'access.toastRoleAdded', { name: input.label }));
      props.onClose();
    },
  }));
  const remove = useMutation(() => ({
    mutationFn: () => deleteRole({ org: props.org, key: props.role!.id }),
    onSuccess: () => {
      notify(t('access.toastRoleRemoved', { name: props.role!.label }));
      props.onClose();
    },
  }));
  return (
    <aside class="drawer role-editor" aria-label={props.role ? t('access.editRole', { name: props.role.label }) : t('access.newRole')}>
      <header class="drawer-head">
        <h2>{props.role ? t('access.editRole', { name: props.role.label }) : t('access.newRole')}</h2>
        <button type="button" class="icon-btn" aria-label={t('access.close')} onClick={() => props.onClose()}>
          <Icon name="x" />
        </button>
      </header>
      <form
        class="form"
        onSubmit={(event) => {
          event.preventDefault();
          const d = new FormData(event.currentTarget);
          save.mutate({
            label: String(d.get('label')),
            summary: String(d.get('summary') ?? ''),
            permissions: d.getAll('perm').map(String) as Array<Permission>,
          });
        }}
      >
        <label>
          <span class="form-label">{t('access.roleName')}</span>
          <input type="text" name="label" required minlength="2" maxlength="60" value={props.role?.label ?? ''} />
        </label>
        <label>
          <span class="form-label">{t('access.roleSummary')}</span>
          <input type="text" name="summary" maxlength="200" value={props.role?.summary ?? ''} />
        </label>
        <fieldset class="perm-list">
          <legend class="form-label">{t('access.can')}</legend>
          <For each={props.permissions}>
            {([perm, label]) => (
              <label>
                <input
                  type="checkbox"
                  name="perm"
                  value={perm}
                  checked={props.role?.permissions.includes(perm) ?? false}
                  disabled={!props.mine.includes(perm)}
                />
                <span>
                  {label} <code>{perm}</code>
                </span>
              </label>
            )}
          </For>
          <span class="muted hint">{t('access.grantHint')}</span>
        </fieldset>
        <Show when={save.error ?? remove.error}>{(error) => <p role="alert" class="error">{error()?.message}</p>}</Show>
        <button type="submit" class="btn" disabled={save.isPending}>
          {props.role ? t('access.saveRole') : t('access.addRole')}
        </button>
        <Show when={props.role}>
          {(role) => (
            <Show
              when={!role().members}
              fallback={<span class="muted hint">{t('access.roleHeld', { count: role().members ?? 0 })}</span>}
            >
              <ConfirmButton class="ghost" label={t('access.removeRole')} confirm={t('access.removeConfirm')} onConfirm={() => remove.mutate()} />
            </Show>
          )}
        </Show>
      </form>
    </aside>
  );
}

// Accounts and workspaces, backed by the identity service. The browser keeps
// only a signed cookie holding the identity session token; the password never
// touches anything but the identity service. There's no sign-up or "create a
// business" here: Tenantly admins create owners and their businesses (lib/admin.ts),
// and owners create their team's accounts (lib/tenancy.ts inviteMember).
import { reload } from '@solidjs/web';
import { GET } from '@solidjs/web/server-functions';

import { refuse } from '../server/access';
import { api } from '../server/api';
import { t } from './i18n';
import { clearSession, getSession, setSession } from '../server/session';
import type { Viewer, Workspace } from './types';

export const getCurrentUser = GET(async (): Promise<Viewer | null> => {
  'use server';
  const token = (await getSession())?.token;
  if (!token) return null;
  try {
    return await api<Viewer>('identity', '/me', { token });
  } catch {
    // An expired or revoked session reads as signed out.
    return null;
  }
});

export const getWorkspaces = GET(async (): Promise<Array<Workspace>> => {
  'use server';
  const token = (await getSession())?.token;
  if (!token) return [];
  try {
    return await api<Array<Workspace>>('identity', '/me/workspaces', { token });
  } catch {
    return [];
  }
});

export async function signIn(input: { email: string; password: string; invite?: string }) {
  'use server';
  const { token } = await api<{ token: string }>('identity', '/auth/login', { body: input });
  await setSession({ token });
  return reload({ revalidate: ['current-user', 'workspaces'] });
}

/** Join a business from an invite link while already signed in. */
export async function acceptInvite(invite: string) {
  'use server';
  const token = (await getSession())?.token;
  if (!token) throw refuse(t('common.signInToContinue'));
  const { joined } = await api<{ joined: boolean }>('identity', '/me/invites', { token, body: { invite } });
  if (!joined) throw refuse(t('common.inviteUnusable'));
  return reload({ revalidate: ['workspaces'] });
}

export async function logout() {
  'use server';
  const token = (await getSession())?.token;
  if (token) {
    // Revoke server-side too; a failure here must not keep someone signed in.
    await api('identity', '/auth/logout', { method: 'POST', token }).catch(() => undefined);
  }
  await clearSession();
  return reload({ revalidate: ['current-user', 'workspaces'] });
}

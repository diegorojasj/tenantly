// Signed cookie sessions: `@remix-run/cookie` (signed HMAC-SHA256 on pure
// WebCrypto — node/deno/bun/workerd — with secret rotation built in)
// composed over @solidjs/web's request event. There is no Solid session API
// on purpose: cookies are a web standard, so sessions compose from a
// standard cookie library instead of a framework opinion.
//
// Reads come off `event.request`; writes append to the `event.response`
// stub and ride whatever response leaves, thrown redirects included (the
// set-session-then-`throw redirect()` login flow works by construction).
//
// Signed, NOT encrypted: the payload is tamper-proof but client-readable.
// Never put secrets in it. (The virtual:env/server import is also the
// server-only boundary: pulling this module into client code fails the
// build, naming the importer.)
import { getRequestEvent } from '@solidjs/web';
import type { RequestEvent, ResponseStub } from '@solidjs/web';
import { createCookie } from '@remix-run/cookie';
import { env } from 'virtual:env/server';

import { isAdminRequest } from './host';

/** Augment with whatever the app stores; keep it small (cookies cap at ~4KB). */
export interface SessionData {
  /** The identity service session token (opaque; the service stores only its hash). */
  token?: string;
}

/** The Tenantly admin console's session: an admin token, which dies with the admin's access window. */
export interface AdminSessionData {
  token?: string;
  /** When the access window closes (ISO); the console signs out then. */
  activeUntil?: string | null;
}

const MAX_AGE = 60 * 60 * 24 * 7; // seconds — drives cookie Max-Age AND the enforced expiry
// Admin windows are minutes long; identity refuses the token once one closes anyway.
const ADMIN_MAX_AGE = 60 * 30;

// Rotation: SESSION_SECRET is comma-separated, newest first — the first
// entry signs, every entry verifies. To rotate, prepend the new secret
// (`SESSION_SECRET="new,old"`) and drop the old one after a MAX_AGE
// window. Dropping every old secret logs every outstanding session out.
const secrets = (env.SESSION_SECRET ?? '')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);
if (secrets.length === 0) {
  throw new Error(
    'session: SESSION_SECRET is not set — generate one with `openssl rand -base64 32`',
  );
}

const cookie = createCookie('session', {
  secrets,
  httpOnly: true, // explicit: @remix-run/cookie defaults httpOnly to FALSE
  // `secure` is decided per request (see isHttps): browsers silently drop a
  // Secure cookie set over plain http on any host but localhost, so a fixed
  // `secure: true` breaks sign-in at http://192.168.x.x or any LAN/public IP.
  sameSite: 'Lax',
  maxAge: MAX_AGE,
});

// The admin console's own cookie: another name, host-only (no Domain), Strict, and only
// ever read or written on the admin host — the tenant session never works there, nor
// this one on the app's host.
const adminCookie = createCookie('tenantly_admin', {
  secrets,
  httpOnly: true,
  sameSite: 'Strict',
  maxAge: ADMIN_MAX_AGE,
});

function event(): RequestEvent & { response: ResponseStub } {
  const e = getRequestEvent();
  if (!e) {
    throw new Error(
      'session: no request event — call within a server function, SSR handler, or middleware',
    );
  }
  return e as RequestEvent & { response: ResponseStub };
}

/**
 * Whether the browser reached us over https. Behind the proxy (or any TLS
 * terminator) the request arrives as http, so X-Forwarded-Proto wins; the
 * first entry is the client-facing hop.
 */
function isHttps(request: Request): boolean {
  const forwarded = request.headers.get('x-forwarded-proto');
  if (forwarded) return forwarded.split(',')[0].trim().toLowerCase() === 'https';
  return new URL(request.url).protocol === 'https:';
}

/** A cookie's signed payload, or `null` when absent, tampered, rotated out or expired. */
async function read<T>(jar: typeof cookie): Promise<T | null> {
  const raw = await jar.parse(event().request.headers.get('cookie'));
  if (!raw) return null;
  try {
    const { data, exp } = JSON.parse(raw) as { data: T; exp: number };
    // Expiry is enforced HERE, server-side: the signed format carries no
    // expiry of its own (the MAC covers the value only), and cookie
    // Max-Age is browser hygiene a client is free to ignore.
    return typeof exp === 'number' && Date.now() < exp * 1000 ? data : null;
  } catch {
    return null;
  }
}

async function write(jar: typeof cookie, data: unknown, maxAge: number): Promise<void> {
  const exp = Math.floor(Date.now() / 1000) + maxAge;
  const e = event();
  e.response.headers.append(
    'set-cookie',
    await jar.serialize(JSON.stringify({ data, exp }), { secure: isHttps(e.request) }),
  );
}

async function clear(jar: typeof cookie): Promise<void> {
  const e = event();
  e.response.headers.append('set-cookie', await jar.serialize('', { maxAge: 0, secure: isHttps(e.request) }));
}

/**
 * The current session, or `null` — absent, tampered, signed by a
 * rotated-out secret, expired, and asked for on the admin host all read
 * the same. Reads the REQUEST's cookie only: a `setSession` in the same
 * request does not read back (the request is what arrived; the response
 * is what you're building).
 */
export async function getSession(): Promise<SessionData | null> {
  if (isAdminRequest(event().request)) return null;
  return read<SessionData>(cookie);
}

/** Replaces the session (whole-payload write) on the outgoing response. */
export async function setSession(data: SessionData): Promise<void> {
  if (isAdminRequest(event().request)) throw new Error('session: no workspace session on the admin host');
  await write(cookie, data, MAX_AGE);
}

/** Expires the session cookie on the outgoing response. */
export async function clearSession(): Promise<void> {
  await clear(cookie);
}

/** The admin console's session; `null` anywhere but the admin host. */
export async function getAdminSession(): Promise<AdminSessionData | null> {
  if (!isAdminRequest(event().request)) return null;
  return read<AdminSessionData>(adminCookie);
}

export async function setAdminSession(data: AdminSessionData): Promise<void> {
  if (!isAdminRequest(event().request)) throw new Error('session: the admin session lives on the admin host only');
  await write(adminCookie, data, ADMIN_MAX_AGE);
}

export async function clearAdminSession(): Promise<void> {
  await clear(adminCookie);
}

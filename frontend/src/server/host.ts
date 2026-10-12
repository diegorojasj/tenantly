// Which side of Tenantly a request is on. The admin console has a host of its own
// (ADMIN_HOST, e.g. admin.localhost): there the app serves the console and nothing
// tenant, and the console is served nowhere else. The proxy enforces the same split
// (containers/proxy); this is the app's own check, for pages, server functions and
// sessions alike, so neither side's cookie or RPCs work on the other.
import { getRequestEvent } from '@solidjs/web';
import { env } from 'virtual:env/server';

function adminHost(): string {
  return (env.ADMIN_HOST ?? 'admin.localhost').toLowerCase();
}

/** The request's host name, without the port. */
export function hostOf(request: Request): string {
  const raw = request.headers.get('host') ?? new URL(request.url).host;
  return raw.toLowerCase().replace(/:\d+$/, '');
}

export function isAdminRequest(request: Request): boolean {
  return hostOf(request) === adminHost();
}

/** Whether the current request (server function, SSR or middleware) came to the admin host. */
export function onAdminHost(): boolean {
  const event = getRequestEvent();
  return event ? isAdminRequest(event.request) : false;
}

/** Paths that belong to the console's pages. */
export function isAdminPath(pathname: string): boolean {
  return pathname === '/admin' || pathname.startsWith('/admin/');
}

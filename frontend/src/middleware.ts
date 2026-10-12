// The server middleware chain (wired via `start.middleware` in
// vite.config.ts). Each function is `(event, next) => Response`: the request
// is `event.request`, and `next()` takes no arguments — assign
// `event.request` before calling it to hand a different request downstream.
// Per-request render inputs (`event.nonce`, `event.renderMode`) go on the
// event before `next()` too, since the page render runs inside it. The chain
// fronts every request the server dispatches — page renders, server function
// calls, and API routes alike — and runs inside the request-event scope, so
// getRequestEvent() and the session helpers work here exactly as in
// application code.
import type { StartMiddleware } from '@solidjs/vite-plugin';
import { createAPIHandler } from 'filesystem-routing/api';
import routes from 'virtual:file-routes';

import { isAdminPath, isAdminRequest } from './server/host';

// createAPIHandler serves the GET/POST/... exports of the modules under
// src/api (mounted at /api — see the fileRoutes config in vite.config.ts)
// and passes everything else down the chain. It still speaks the previous
// (request, next) shape and calls next() with no arguments, so adapt it
// onto the event.
const api = createAPIHandler(routes);

const handleAPI: StartMiddleware = (event, next) => api(event.request, next);

const notFound = () => new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain' } });

// The admin console and the workspaces never share a host (src/server/host.ts). On the
// admin host only the console's pages render ("/" goes to it, workspace pages are 404);
// on any other host the console is 404. Server functions check their side themselves.
const hostGate: StartMiddleware = (event, next) => {
  const { pathname } = new URL(event.request.url);
  if (isAdminRequest(event.request)) {
    if (pathname === '/') return new Response(null, { status: 302, headers: { location: '/admin' } });
    if (pathname === '/t' || pathname.startsWith('/t/') || pathname.startsWith('/api/')) return notFound();
  } else if (isAdminPath(pathname)) {
    return notFound();
  }
  return next();
};

export default [hostGate, handleAPI];

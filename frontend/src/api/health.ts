// A liveness probe for containers and load balancers (GET /api/health).
// Deliberately tenant-agnostic: it reveals nothing about who runs here.
import type { APIHandler } from 'filesystem-routing/api';

export const GET: APIHandler = () =>
  Response.json({ status: 'ok' }, { headers: { 'cache-control': 'no-store' } });

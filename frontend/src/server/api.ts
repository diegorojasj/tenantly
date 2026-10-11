// The only way the frontend talks to the services: through the proxy's /api
// prefix, server-side, with the caller's token. Service errors already carry a
// sentence written for the user (`{"detail": ...}`), so they pass straight
// through as safe errors; anything else becomes a generic, honest message.
import 'server-only';

import { markSafeError } from '@solidjs/web';
import { env } from 'virtual:env/server';

import { locale, t } from '../lib/i18n';

export type Service = 'identity' | 'operations' | 'billing';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = 'ApiError';
    markSafeError(this);
  }
}

const TIMEOUT_MS = 10_000;

function base() {
  return (env.API_URL ?? 'http://localhost:8080/api').replace(/\/$/, '');
}

type Query = Record<string, string | number | null | undefined>;

export async function api<T>(
  service: Service,
  path: string,
  options: { method?: string; token?: string; body?: unknown; query?: Query } = {},
): Promise<T> {
  const url = new URL(`${base()}/${service}${path}`);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  }
  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? (options.body === undefined ? 'GET' : 'POST'),
      headers: {
        accept: 'application/json',
        // The services answer (errors, template wording) in the viewer's language.
        'accept-language': locale(),
        ...(options.body === undefined ? {} : { 'content-type': 'application/json' }),
        ...(options.token ? { authorization: `Bearer ${options.token}` } : {}),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    throw new ApiError(t('common.serviceUnreachable', { service }), 503, 'unavailable');
  }
  const text = await response.text();
  const data = text ? safeJson(text) : null;
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? String(data.detail) : null;
    const code = data && typeof data === 'object' && 'code' in data ? String(data.code) : 'error';
    throw new ApiError(detail ?? t('common.serviceFailed', { service, status: response.status }), response.status, code);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

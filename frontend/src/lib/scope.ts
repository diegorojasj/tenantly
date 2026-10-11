// The tenant + scope pair every workspace page reads. Both live in the URL —
// `/t/<org>?scope=<node>` — so a focused view is shareable, survives reloads,
// renders server-side, and keys its own cache entries.
import { useQuery } from '@tanstack/solid-query';
import { getRouteApi } from '@tanstack/solid-router';

import { tenantQuery } from './queries';

const tenantRoute = getRouteApi('/t/$org');

export function useTenantScope() {
  const params = tenantRoute.useParams();
  const search = tenantRoute.useSearch();
  return {
    org: () => params().org,
    scope: () => search().scope ?? '',
  };
}

/** The business's currency (ISO 4217), from the shell's tenant context. */
export function useCurrency() {
  const { org, scope } = useTenantScope();
  const ctx = useQuery(() => tenantQuery(org(), scope()));
  return () => ctx.data?.tenant.currency ?? 'USD';
}

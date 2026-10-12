// The Query layer: every read the app makes, declared once as typed
// queryOptions wrapping a Solid server function. Route loaders prefetch
// these, components read them with useQuery, and the single-flight
// machinery (src/server-config.ts) refreshes them by key — three consumers,
// one definition.
import type { FetchQueryOptions } from '@tanstack/solid-query';
import { QueryClient, queryOptions } from '@tanstack/solid-query';

import { flightGateSkips, serverQueryFn } from './flight';
import {
  getAdminAudit,
  getAdminOwners,
  getAdminPlans,
  getAdminPolicy,
  getAdminSubscription,
  getAdminViewer,
} from './admin';
import { getCurrentUser, getWorkspaces } from './auth';
import {
  getAudit,
  getBilling,
  getBillingHistory,
  getCountedCustomers,
  getPlanInvoice,
  getConfig,
  getMembers,
  getRoles,
  getSettings,
  getTenantContext,
} from './tenancy';
import {
  getAccounts,
  getAvailability,
  getBookingCharges,
  getBookingOptions,
  getBookings,
  getCalendar,
  getCatalog,
  getCustomer,
  getCustomers,
  getInsights,
  getInvoice,
  getInvoices,
  getPayments,
  getResources,
  getToday,
} from './ops';
import { isRefusal } from './refusal';
import type { BookingRange } from './types';

// Tenant reads are keyed `[resource, org, scope]`: the first segment is what
// mutations name in `reload({ revalidate })`, and the org segment keeps every
// tenant's data in its own cache slot — switching workspaces can never show
// a neighbour's rows, even for a frame.

// Session-shaped reads are component-owned (shell state, not page data), so
// they declare their fetch as a recipe (`serverQueryFn`, src/lib/flight.ts):
// when sign-in/out names their keys, the server re-executes them and ships
// the fresh values on the mutation's own response.
export const currentUserQuery = () =>
  queryOptions({ queryKey: ['current-user'], ...serverQueryFn(getCurrentUser) });

export const workspacesQuery = () =>
  queryOptions({ queryKey: ['workspaces'], ...serverQueryFn(getWorkspaces) });

export const tenantQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['tenant', org, scope], queryFn: () => getTenantContext(org, scope) });

export const todayQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['today', org, scope], queryFn: () => getToday(org, scope) });

export const calendarQuery = (org: string, scope = '', day = '') =>
  queryOptions({ queryKey: ['calendar', org, scope, day], queryFn: () => getCalendar(org, scope, day) });

export const bookingsQuery = (org: string, scope: string, range: BookingRange) =>
  queryOptions({ queryKey: ['bookings', org, scope, range], queryFn: () => getBookings(org, scope, range) });

export const bookingOptionsQuery = (org: string, locationId: string) =>
  queryOptions({
    queryKey: ['booking-options', org, locationId],
    queryFn: () => getBookingOptions(org, locationId),
    // Always fresh when the drawer opens (it isn't swept by mutations).
    staleTime: 0,
  });

/** `picks`: the chosen resource ids, comma-separated. */
export const availabilityQuery = (org: string, site: string, offering: string, picks: string, day: string, minutes: number, units = 1) =>
  queryOptions({
    queryKey: ['availability', org, site, offering, picks, day, minutes, units],
    queryFn: () => getAvailability(org, site, offering, picks, day, minutes, units),
    staleTime: 0,
  });

export const customersQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['customers', org, scope], queryFn: () => getCustomers(org, scope) });

export const customerQuery = (org: string, id: string) =>
  queryOptions({ queryKey: ['customer', org, id], queryFn: () => getCustomer(org, id) });

export const accountsQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['accounts', org, scope], queryFn: () => getAccounts(org, scope) });

export const catalogQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['catalog', org, scope], queryFn: () => getCatalog(org, scope) });

export const resourcesQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['resources', org, scope], queryFn: () => getResources(org, scope) });

export const paymentsQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['payments', org, scope], queryFn: () => getPayments(org, scope) });

/** Keyed under `payments` so every money mutation refreshes the open booking panel too. */
export const bookingChargesQuery = (org: string, bookingId: string) =>
  queryOptions({ queryKey: ['payments', org, 'booking', bookingId], ...serverQueryFn(getBookingCharges, org, bookingId) });

export const invoicesQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['invoices', org, scope], queryFn: () => getInvoices(org, scope) });

/** Keyed under `invoices`: paying or voiding it refreshes the open view. */
export const invoiceQuery = (org: string, id: string) =>
  queryOptions({ queryKey: ['invoices', org, 'one', id], queryFn: () => getInvoice(org, id) });

export const insightsQuery = (org: string, scope: string, days: number) =>
  queryOptions({ queryKey: ['insights', org, scope, days], queryFn: () => getInsights(org, scope, days) });

export const membersQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['members', org, scope], queryFn: () => getMembers(org, scope) });

export const rolesQuery = (org: string) =>
  queryOptions({ queryKey: ['roles', org], queryFn: () => getRoles(org) });

export const settingsQuery = (org: string) =>
  queryOptions({ queryKey: ['settings', org], queryFn: () => getSettings(org) });

export const configQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['config', org, scope], queryFn: () => getConfig(org, scope) });

export const auditQuery = (org: string, scope = '') =>
  queryOptions({ queryKey: ['audit', org, scope], queryFn: () => getAudit(org, scope) });

export const billingQuery = (org: string) =>
  queryOptions({ queryKey: ['billing', org], queryFn: () => getBilling(org) });

export const billingHistoryQuery = (org: string) =>
  queryOptions({ queryKey: ['billing-history', org], queryFn: () => getBillingHistory(org) });

/** `period` 0: the open one. */
export const countedCustomersQuery = (org: string, period: number, offset: number) =>
  queryOptions({ queryKey: ['billing', org, 'customers', period, offset], queryFn: () => getCountedCustomers(org, period, offset) });

export const planInvoiceQuery = (org: string, invoiceId: string) =>
  queryOptions({ queryKey: ['billing-history', org, 'invoice', invoiceId], queryFn: () => getPlanInvoice(org, invoiceId) });

// The Tenantly admin console, on the admin host only; identity refuses anyone but an
// admin inside their access window.
export const adminViewerQuery = () => queryOptions({ queryKey: ['admin-viewer'], ...serverQueryFn(getAdminViewer) });

export const adminPlansQuery = () => queryOptions({ queryKey: ['admin-plans'], ...serverQueryFn(getAdminPlans) });

export const adminPolicyQuery = () => queryOptions({ queryKey: ['admin-policy'], ...serverQueryFn(getAdminPolicy) });

export const adminAuditQuery = (offset: number) =>
  queryOptions({ queryKey: ['admin-audit', offset], queryFn: () => getAdminAudit(offset) });

export const adminOwnersQuery = (q: string, offset: number) =>
  queryOptions({ queryKey: ['admin-owners', q, offset], queryFn: () => getAdminOwners(q, offset) });

export const adminSubscriptionQuery = (tenantId: string) =>
  queryOptions({ queryKey: ['admin-subscription', tenantId], queryFn: () => getAdminSubscription(tenantId) });

// One factory for every side that needs a cache: the client boot
// (src/App.tsx, one for the session), the per-request SSR setup
// (src/setup.tsx), and the single-flight collector (src/server-config.ts).
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Data the server just rendered (or a mutation just refreshed) is
        // fresh — without this, every observer would kick off a refetch the
        // moment it mounts, defeating both SSR hydration and single-flight.
        staleTime: 30_000,
        // Access errors are answers, not blips: don't hammer the boundary.
        retry: (count, error) => !isRefusal(error) && count < 2,
      },
    },
  });
}

// The loaders' prefetch hint. Fire-and-forget on every side: loaders
// *start* their queries as navigation begins (and on hover preloads)
// without blocking the router — the navigation commits immediately and
// components pick the data up at the read point. On the server this is
// what lets SSR stream each Loading boundary as its query settles instead
// of collapsing TTFB to the slowest fetch. No hydration exception: the
// client never runs a boot load pass (createRouter primes matches from the
// server's registry entries), so the first time a loader runs client-side
// is a real navigation. During single-flight collection the gate
// (src/lib/flight.ts) can answer that the mutation's client already holds
// this query and didn't declare it stale — then the prefetch is skipped and
// the response ships without it.
export function prefetch(
  queryClient: QueryClient,
  options: FetchQueryOptions<any, any, any, any>,
) {
  if (flightGateSkips(queryClient, options.queryKey)) return;
  void queryClient.prefetchQuery(options);
}

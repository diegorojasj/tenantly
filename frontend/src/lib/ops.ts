// Operations RPCs: Today, Calendar, Bookings, Customers, Catalog, Resources,
// Payments and Insights. Each forwards the tenant token to the service that
// owns the data (operations or billing); the services authorize, scope,
// validate and audit. Mutations name the query keys they refresh.
import { reload } from '@solidjs/web';
import { GET } from '@solidjs/web/server-functions';

import { enterTenant } from '../server/access';
import { api } from '../server/api';
import { t } from './i18n';
import type {
  Account,
  AttributeValue,
  Booking,
  BookingRange,
  BookingStatus,
  Charge,
  Customer,
  DocumentLevel,
  DocumentType,
  FieldDef,
  Insights,
  Invoice,
  Money,
  Offering,
  OfferingKind,
  PartyType,
  Requirement,
  Resource,
  ScopeNode,
  Subject,
  Today,
} from './types';

/** Reads run against the scope the identity service resolved (clamped to the member's reach). */
async function read<T>(slug: string, scope: string, service: 'operations' | 'billing', path: string, query = {}) {
  const access = await enterTenant(slug, scope || undefined);
  return api<T>(service, path, { token: access.jwt, query: { scope: access.scopeId, ...query } });
}

async function write(org: string, service: 'operations' | 'billing', path: string, body?: unknown, method?: string) {
  const access = await enterTenant(org);
  return api<unknown>(service, path, { token: access.jwt, body: body ?? {}, method: method ?? 'POST' });
}

// ------------------------------------------------------------------ today --

export const getToday = GET(async (slug: string, scope: string): Promise<Today> => {
  'use server';
  return read(slug, scope, 'operations', '/today');
});

// --------------------------------------------------------------- calendar --

export const getCalendar = GET(async (slug: string, scope: string, day: string) => {
  'use server';
  return read<{
    date: string;
    today: string;
    open: number;
    close: number;
    /** Zone the day and hours are in (the location's, or UTC across zones). */
    tz: string;
    board: { resources: Array<Resource>; bookings: Array<Booking> } | null;
    sites: Array<{ node: ScopeNode; bookings: number; utilization: number }>;
  }>(slug, scope, 'operations', '/calendar', { day });
});

// --------------------------------------------------------------- bookings --

export const getBookings = GET(async (slug: string, scope: string, range: BookingRange) => {
  'use server';
  return read<{ from: string; to: string; canManage: boolean; bookings: Array<Booking> }>(
    slug,
    scope,
    'operations',
    '/bookings',
    { range },
  );
});

export const getBookingOptions = GET(async (slug: string, locationId: string) => {
  'use server';
  const access = await enterTenant(slug);
  return api<{
    locationId: string;
    tz: string;
    hours: [number, number];
    approval: boolean;
    offerings: Array<Offering>;
    classes: Array<Offering>;
    /** Everything in service here; each `pick` requirement offers the ones that match it. */
    resources: Array<Resource>;
    /** Each customer's subjects (their own and their account's), for offerings that serve one. */
    customers: Array<{ id: string; name: string; detail: string; subjects: Array<{ id: string; type: string; name: string }> }>;
    sessions: Array<Booking>;
    subjectTypes: Array<PartyType>;
    /** The template's booking fields. */
    bookingFields: Array<FieldDef>;
  }>('operations', '/booking-options', { token: access.jwt, query: { location: locationId } });
});

export const getAvailability = GET(
  async (slug: string, locationId: string, offeringId: string, picks: string, date: string, minutes: number, units = 1) => {
    'use server';
    // Nothing chosen yet (e.g. an empty catalog): answer without a round trip.
    if (!offeringId || !locationId) return { slots: [], reason: t('payments.availabilityPickFirst') };
    const access = await enterTenant(slug);
    return api<{ slots: Array<string>; reason: string }>('operations', '/availability', {
      token: access.jwt,
      query: { location: locationId, offering: offeringId, resources: picks, day: date, minutes, units },
    });
  },
);

// The booking drawer's own queries (booking-options, availability) are not
// listed: the drawer closes as the mutation lands, and refreshing a query
// whose only reader is unmounting left the router's transition unsettled.
// The drawer fetches them fresh every time it opens instead (staleTime 0).
const BOOKING_KEYS = ['calendar', 'bookings', 'today', 'customers', 'customer', 'audit'];

export async function createBooking(input: {
  org: string;
  locationId: string;
  offeringId: string;
  customerId: string;
  start: string;
  minutes?: number;
  /** Day / night / month offerings: how many. */
  units?: number;
  /** The resources picked for the offering's `pick` requirements. */
  resourceIds?: Array<string>;
  /** What it's for, when the offering serves a subject. */
  subjectId?: string;
  fields?: Record<string, AttributeValue>;
}) {
  'use server';
  const { org, ...body } = input;
  await write(org, 'operations', '/bookings', body);
  return reload({ revalidate: BOOKING_KEYS });
}

export async function scheduleSession(input: {
  org: string;
  locationId: string;
  offeringId: string;
  resourceIds: Array<string>;
  start: string;
  repeatWeeks: number;
}) {
  'use server';
  const { org, ...body } = input;
  await write(org, 'operations', '/sessions', body);
  return reload({ revalidate: BOOKING_KEYS });
}

export async function joinSession(input: { org: string; bookingId: string; customerId: string }) {
  'use server';
  await write(input.org, 'operations', `/bookings/${input.bookingId}/attendees`, { customerId: input.customerId });
  return reload({ revalidate: [...BOOKING_KEYS, 'payments'] });
}

export async function setBookingStatus(input: { org: string; bookingId: string; status: BookingStatus }) {
  'use server';
  await write(input.org, 'operations', `/bookings/${input.bookingId}/status`, { status: input.status });
  return reload({ revalidate: [...BOOKING_KEYS, 'payments', 'insights'] });
}

// -------------------------------------------------------------- customers --

export const getCustomers = GET(async (slug: string, scope: string): Promise<Array<Customer>> => {
  'use server';
  return read(slug, scope, 'operations', '/customers');
});

export const getCustomer = GET(async (slug: string, id: string) => {
  'use server';
  const access = await enterTenant(slug);
  return api<{
    customer: Customer;
    /** Every document type, with how much the policy at the customer's location asks for it. */
    documentTypes: Array<DocumentType & { level: DocumentLevel }>;
    subjects: Array<Subject>;
    /** Subject id → labels of subject documents the policy asks for that it lacks. */
    subjectMissing: Record<string, Array<string>>;
    /** Other members of the customer's account. */
    contacts: Array<{ id: string; name: string; role: string }>;
    history: Array<Booking>;
    charges: Array<Charge>;
    plans: Array<Offering>;
    canBook: boolean;
    canCollect: boolean;
  }>('operations', `/customers/${id}`, { token: access.jwt });
});

export async function createCustomer(input: {
  org: string;
  locationId: string;
  name: string;
  phone: string;
  email: string;
  fields: Record<string, AttributeValue>;
  /** Join an existing account, or open a new one (type + name). */
  accountId?: string;
  accountType?: string;
  accountName?: string;
  accountRole?: string;
}) {
  'use server';
  const { org, ...body } = input;
  await write(org, 'operations', '/customers', body);
  return reload({ revalidate: ['customers', 'accounts', 'today', 'audit'] });
}

export const getAccounts = GET(async (slug: string, scope: string): Promise<Array<Account>> => {
  'use server';
  return read(slug, scope, 'operations', '/accounts');
});

export async function createSubject(input: {
  org: string;
  type: string;
  name: string;
  customerId?: string;
  accountId?: string;
  fields: Record<string, AttributeValue>;
}) {
  'use server';
  const { org, ...body } = input;
  await write(org, 'operations', '/subjects', body);
  return reload({ revalidate: ['customer', 'audit'] });
}

export async function sellPlan(input: { org: string; customerId: string; offeringId: string }) {
  'use server';
  await write(input.org, 'operations', `/customers/${input.customerId}/plan`, { offeringId: input.offeringId });
  return reload({ revalidate: ['customers', 'customer', 'payments', 'catalog', 'audit'] });
}

export async function cancelPlan(input: { org: string; customerId: string; subscriptionId: string }) {
  'use server';
  await write(input.org, 'operations', `/customers/${input.customerId}/subscriptions/${input.subscriptionId}/cancel`);
  return reload({ revalidate: ['customers', 'customer', 'catalog', 'audit'] });
}

export async function recordDocument(input: {
  org: string;
  customerId: string;
  type: string;
  subjectId?: string;
  /** `YYYY-MM-DD`; today when left out. */
  issued?: string;
  /** Defaults to the type's validity after `issued`. */
  expires?: string;
  reference?: string;
}) {
  'use server';
  const { org, customerId, ...body } = input;
  await write(org, 'operations', `/customers/${customerId}/documents`, body);
  return reload({ revalidate: ['customers', 'customer', 'today', 'audit'] });
}

// ---------------------------------------------------------------- catalog --

export const getCatalog = GET(async (slug: string, scope: string) => {
  'use server';
  return read<{
    canEdit: boolean;
    /** Categories in use per resource type, to suggest when naming a requirement. */
    roles: Record<string, Array<string>>;
    offerings: Array<{
      offering: Offering;
      bookings: number;
      revenue: Money;
      fill: number | null;
      subscribers: number | null;
    }>;
  }>(slug, scope, 'operations', '/catalog');
});

export async function createOffering(input: {
  org: string;
  kind: OfferingKind;
  name: string;
  category: string;
  minutes: number;
  /** A decimal string as typed (`"12.10"`); the service keeps it exact. */
  price: Money;
  capacity?: number;
  credits?: number;
  unit?: Offering['unit'];
  place?: Offering['place'];
  requires?: Array<Requirement>;
  /** The subject type each booking names; '' for the customer themselves. */
  subjectType?: string;
  fields?: Record<string, AttributeValue>;
}) {
  'use server';
  const { org, ...body } = input;
  await write(org, 'operations', '/offerings', body);
  return reload({ revalidate: ['catalog', 'today', 'audit'] });
}

export async function toggleOffering(input: { org: string; offeringId: string }) {
  'use server';
  await write(input.org, 'operations', `/offerings/${input.offeringId}/toggle`);
  return reload({ revalidate: ['catalog', 'audit'] });
}

// -------------------------------------------------------------- resources --

export const getResources = GET(async (slug: string, scope: string) => {
  'use server';
  return read<{
    canEdit: boolean;
    locations: Array<ScopeNode>;
    resources: Array<{ resource: Resource; locationName: string; utilization: number; next: string | null }>;
  }>(slug, scope, 'operations', '/resources');
});

export async function createResource(input: {
  org: string;
  locationId: string;
  type: Resource['type'];
  name: string;
  role: string;
  attributes?: Resource['attributes'];
  parentId?: string;
}) {
  'use server';
  const { org, ...body } = input;
  await write(org, 'operations', '/resources', body);
  return reload({ revalidate: ['resources', 'calendar', 'today', 'catalog', 'audit'] });
}

export async function setResourceStatus(input: { org: string; resourceId: string; status: Resource['status'] }) {
  'use server';
  await write(input.org, 'operations', `/resources/${input.resourceId}/status`, { status: input.status });
  return reload({ revalidate: ['resources', 'calendar', 'today', 'audit'] });
}

// --------------------------------------------------------------- payments --

export const getPayments = GET(async (slug: string, scope: string) => {
  'use server';
  return read<{
    canCollect: boolean;
    currency: string;
    summary: { collected30: Money; due: Money; overdue: Money; refunded30: Money };
    charges: Array<Charge>;
  }>(slug, scope, 'billing', '/payments');
});

export const getInvoices = GET(async (slug: string, scope: string) => {
  'use server';
  return read<{ canIssue: boolean; invoices: Array<Invoice> }>(slug, scope, 'billing', '/invoices');
});

/** Gather a customer's open charges onto one invoice, with tax per the business's settings. */
export async function issueInvoice(input: { org: string; customerId: string }) {
  'use server';
  await write(input.org, 'billing', '/invoices', { customerId: input.customerId });
  return reload({ revalidate: ['invoices', 'payments', 'audit'] });
}

export async function settleInvoice(input: { org: string; invoiceId: string; action: 'pay' | 'void' }) {
  'use server';
  await write(input.org, 'billing', `/invoices/${input.invoiceId}/${input.action}`);
  return reload({ revalidate: ['invoices', 'payments', 'customers', 'customer', 'today', 'insights', 'audit'] });
}

export async function settleCharge(input: { org: string; chargeId: string; action: 'collect' | 'refund' }) {
  'use server';
  await write(input.org, 'billing', `/charges/${input.chargeId}/${input.action}`);
  return reload({ revalidate: ['payments', 'customers', 'customer', 'today', 'insights', 'audit'] });
}

// --------------------------------------------------------------- insights --

export const getInsights = GET(async (slug: string, scope: string, days: number): Promise<Insights> => {
  'use server';
  return read(slug, scope, 'operations', '/insights', { days });
});

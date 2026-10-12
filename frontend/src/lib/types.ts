// Shared shapes for everything that crosses the server-function boundary.
// Type-only on purpose: client code imports these without pulling any
// server module (src/server/*) into the bundle.

/** `region` is any group between the business and its locations; its `level` says which (area, franchisee…). */
export type NodeKind = 'org' | 'region' | 'location';

/** An amount as the services send it: a decimal string with two places (`"12.50"`), never a float. */
export type Money = string;
export type NodeStatus = 'active' | 'degraded' | 'paused';

export interface ScopeNode {
  id: string;
  orgId: string;
  parentId: string | null;
  kind: NodeKind;
  /** Groups: the template level key (`area`, `franchisee`…); empty for the business and locations. */
  level?: string;
  name: string;
  code: string;
  status: NodeStatus;
  /** Locations: IANA zone their wall clock runs in (`UTC` unless set). */
  tz?: string;
  /** Locations: own opening hours `[open, close]`, minutes from local midnight; null = the template's. */
  hours?: [number, number] | null;
  /** Locations: street address (empty until set). */
  address?: string;
  /** Locations: map pin `[lat, lng]` (WGS84); null = not on the map yet. */
  pin?: [number, number] | null;
  headcount: number;
  /** False when the node sits outside the viewer's assigned scope. */
  reachable?: boolean;
}

/** A role key of the business: its template's defaults (`owner`, `admin`, …) or one it added. */
export type RoleId = string;

export type Permission =
  | 'bookings.manage'
  | 'payments.collect'
  | 'tenant.manage'
  | 'members.invite'
  | 'roles.assign'
  | 'config.write'
  | 'pricing.write'
  | 'billing.view'
  | 'billing.manage'
  | 'audit.view'
  | 'analytics.view';

export interface Role {
  id: RoleId;
  label: string;
  summary: string;
  permissions: Array<Permission>;
  /** Came from the template (false: the business added it). */
  builtin?: boolean;
  /** Team members holding it (role listing only). */
  members?: number;
}

/** A named group level of the location tree (area; region → franchisee…). */
export interface TreeLevel {
  key: string;
  label: string;
  plural: string;
}

// --------------------------------------------------------- templates --

/** The template preset an offering started from (`appointment`, `class`, `rental`, …). Only names it: the rules decide how it books. */
export type OfferingKind = string;

/** How an offering uses time: a fixed length, a window picked by the hour, whole days / nights / months, or not booked at all (plans). */
export type FulfilmentTime = 'slot' | 'window' | 'span' | 'none';

/** Where the work happens. */
export type FulfilmentPlace = 'on_site' | 'at_customer';

/** What a booking takes: `quantity` resources of a type. Picked ones the desk chooses; the rest are assigned free. */
export interface Requirement {
  type: string;
  quantity: number;
  /** The desk chooses which ones (unset in a preset: team members are picked, things assigned). */
  pick?: boolean;
  /** Only resources of this category (Kayak, Hygienist). */
  role?: string | null;
  /** Only resources whose attributes equal these values. */
  where?: Record<string, AttributeValue>;
  /** Presets: the category must be named when an offering is created. */
  named?: boolean;
}

/** A starting point for offerings — the old fixed kinds are presets of the templates that use them. */
export interface Preset {
  key: string;
  label: string;
  plural: string;
  intro?: string;
  /** Customers per booking: 1 books a slot, more makes a session people join; null for plans. */
  capacity: number | null;
  time: FulfilmentTime;
  /** What the price can buy; the first is the default. */
  units: Array<Offering['unit']>;
  place: FulfilmentPlace;
  requires: Array<Requirement>;
  /** The subject type every booking must name (a pet, a vehicle). */
  subject?: string;
}

export type AttributeValue = string | number | boolean;

/** A typed custom field (docs/PLATFORM.md gap 6): on customers, accounts, subjects, offerings, bookings and resources. */
export interface FieldDef {
  key: string;
  label: string;
  type: 'text' | 'number' | 'bool' | 'choice' | 'date';
  options?: Array<string>;
  required?: boolean;
  /** Personal data: only roles that serve customers see it. */
  pii?: boolean;
  /** A `date` that is a validity limit ("vaccinated until"): flagged once it has passed. */
  expires?: boolean;
}

/** Resource attributes are typed fields too. */
export type AttributeDef = FieldDef;

/** Entities with template-defined fields (subjects and resources carry theirs on their type). */
export type FieldEntity = 'customer' | 'account' | 'offering' | 'booking';

/** Who customers can belong to (a company, a household), or what the business serves (a pet, a vehicle). */
export interface PartyType {
  key: string;
  label: string;
  plural: string;
  fields?: Array<FieldDef>;
}

/** A document a customer (or one of their subjects) keeps on file; `docs.require.<key>` says if it's needed. */
export interface DocumentType {
  key: string;
  label: string;
  appliesTo: 'customer' | 'subject';
  subjectType?: string;
  /** Days a document stays valid after it's issued; none = for good. */
  validDays?: number | null;
}

/** How much the policy at a location asks for a document type. */
export type DocumentLevel = 'Not needed' | 'Remind' | 'Required to book';

/** What delivers the work, as the template defines it (team members, rooms, units, chairs…). */
export interface ResourceType {
  key: string;
  label: string;
  plural: string;
  /** Team members: chosen by the desk and counted as staff. */
  people: boolean;
  /** What the free-text category is called (Specialty, Type). */
  roleLabel?: string;
  attributes?: Array<AttributeDef>;
}

/** One lifecycle for every business; templates only rename the states. */
export type BookingStatus = 'requested' | 'confirmed' | 'checked_in' | 'completed' | 'no_show' | 'cancelled';

/** A template's id in identity's registry; every new business starts on `general`. */
export type TemplateId = string;

/** Which slice of time the Bookings list shows. */
export type BookingRange = 'today' | 'upcoming' | 'past';

/** Every search param a workspace URL can carry (validated by the /t/$org route). */
export interface WorkspaceSearch {
  scope?: string;
  day?: string;
  range?: Exclude<BookingRange, 'today'>;
  days?: 7;
  tab?: 'assets';
  customer?: string;
}

/**
 * A business template: stored data served by identity, not code. It names
 * things, defines resource types and fulfilment presets, defines what must be known about a customer,
 * sets opening hours, the booking lifecycle and the policies a business starts with.
 */
export interface Template {
  id: TemplateId;
  /** Bumped whenever identity edits the template. */
  version: number;
  label: string;
  description: string;
  /** Default tint for businesses created from this template. */
  hue: number;
  /** Fulfilment presets offerings start from. */
  presets: Array<Preset>;
  /** Resource types that deliver the work. */
  resourceTypes: Array<ResourceType>;
  /** Open map of word → label; these keys are always present. */
  terms: Record<string, string> & {
    customer: string;
    customers: string;
    booking: string;
    bookings: string;
    staff: string;
    staffPlural: string;
    asset: string;
    assets: string;
    location: string;
    locations: string;
  };
  status: Record<BookingStatus, string>;
  /** The lifecycle: the statuses a booking may move to from each status (the server enforces the same table). */
  transitions: Partial<Record<BookingStatus, Array<BookingStatus>>>;
  /** Typed custom fields per entity. */
  fields: Partial<Record<FieldEntity, Array<FieldDef>>>;
  /** Accounts customers can belong to: companies with contacts, households. */
  accountTypes: Array<PartyType>;
  /** What the business serves for a customer: pets, children, vehicles, properties. */
  subjectTypes: Array<PartyType>;
  /** Documents with expiry (waivers, vaccinations); policies decide which are required. */
  documents: Array<DocumentType>;
  /** Named group levels between the business and its locations, top to bottom. */
  levels: Array<TreeLevel>;
  /** Roles a new business starts with (it keeps its own editable copy). */
  roles: Array<Role>;
  /** Default opening hours, minutes from local midnight; a location may set its own. */
  open: number;
  close: number;
  /** Policy key → starting value; keys not listed use the platform default. */
  policyDefaults: Record<string, boolean | number | string>;
}

export interface Tenant {
  id: string;
  slug: string;
  name: string;
  industry: string;
  template: Template;
  /** OKLCH hue that tints the whole workspace while it is open. */
  hue: number;
  idp: string;
  residency: string;
  tenantKey: string;
  /** ISO 4217 code every amount of this business is in. */
  currency: string;
  /** Percent, as a decimal string. */
  taxRate: Money;
  taxLabel: string;
  /** True: prices already contain the tax; false: invoices add it on top. */
  pricesIncludeTax: boolean;
  /** White-label branding (empty when unset). */
  logoUrl: string;
  customDomain: string;
}

/** Single sign-on settings: stored only, never active yet. */
export interface SsoSettings {
  protocol: 'none' | 'saml' | 'oidc';
  issuer: string;
  metadataUrl: string;
  clientId: string;
  enforced: false;
  status: 'not_connected';
}

export interface BusinessSettings {
  money: Pick<Tenant, 'currency' | 'taxRate' | 'taxLabel' | 'pricesIncludeTax'>;
  branding: Pick<Tenant, 'logoUrl' | 'customDomain'>;
  sso: SsoSettings;
  /** ISO 4217 codes a business may pick. */
  currencies: Array<string>;
}

export interface Viewer {
  id: string;
  name: string;
  email: string;
  title: string;
  initials: string;
  /** Tenantly restricted the account: it signs in and reads, and changes nothing. */
  restricted?: boolean;
}

export interface Workspace {
  tenant: Tenant;
  role: RoleId;
  roleLabel: string;
  scopeId: string;
  scopeName: string;
}

export interface TenantContext {
  tenant: Tenant;
  role: Role;
  /** The node the viewer is assigned to — the widest scope they can open. */
  homeScopeId: string;
  /** The node currently in focus (validated against homeScopeId). */
  scopeId: string;
  /** Root → focus, for the lens strip. */
  path: Array<ScopeNode>;
  nodes: Array<ScopeNode>;
  /** Team members holding a seat (active or invited). */
  seats: number;
  /** The Tenantly plan's name and payment standing (billing's word, carried by identity). */
  billing: { plan: string | null; status: Standing };
  /** Tenantly restricted the viewer's account: every service refuses their changes. */
  restricted?: boolean;
}

export interface Member {
  /** Membership id (what role changes address). */
  id: string;
  /** Null until an invited person signs up. */
  userId: string | null;
  name: string;
  email: string;
  role: RoleId;
  scopeId: string;
  scopePath: string;
  mfa: boolean;
  sso: boolean;
  lastSeen: string | null;
  status: 'active' | 'invited' | 'suspended';
}

export type SettingValue = boolean | number | string;

export interface SettingDef {
  key: string;
  label: string;
  hint: string;
  /** Group heading, translated to the request language; groups render in served order. */
  group: string;
  type: 'bool' | 'number' | 'enum' | 'text';
  unit?: string;
  options?: Array<string>;
  /** Enum only: stored value → label translated to the request language. */
  optionLabels?: Record<string, string>;
  /** Permission needed to override this setting. */
  guard: Permission;
}

export interface CascadeStep {
  nodeId: string | null;
  label: string;
  kind: NodeKind | 'platform';
  value: SettingValue | undefined;
}

export interface ResolvedSetting {
  def: SettingDef;
  value: SettingValue;
  /** Index in `trail` that supplies the effective value. */
  source: number;
  trail: Array<CascadeStep>;
  editable: boolean;
}

export interface AuditEvent {
  id: string;
  at: string;
  actor: string;
  actorId: string;
  action: string;
  category: 'access' | 'config' | 'billing' | 'integration' | 'security';
  target: string;
  scopeId: string;
  scopeName: string;
  ip: string;
  hash: string;
  prevHash: string;
}

// ------------------------------------------------------ service model --

export interface Offering {
  id: string;
  kind: OfferingKind;
  name: string;
  category: string;
  /** Session length; for rentals the default window. 0 for plans. */
  minutes: number;
  price: Money;
  /** What the price buys: a session, an hour / day / night / month of hire, a month or pack of a plan… */
  unit: 'session' | 'hour' | 'day' | 'night' | 'month' | 'pack';
  /** Customers per booking: 1 books a slot, more makes a session; null for plans. */
  capacity: number | null;
  /** Class packs: how many classes the pack holds. */
  credits?: number;
  time: FulfilmentTime;
  place: FulfilmentPlace;
  /** What every booking takes. */
  requires: Array<Requirement & { pick: boolean }>;
  /** The subject type each booking names (a pet, a vehicle); null when it serves the customer. */
  subjectType: string | null;
  fields: Record<string, AttributeValue>;
  active: boolean;
}

export interface Resource {
  id: string;
  locationId: string;
  /** One of the template's resource type keys. */
  type: string;
  name: string;
  /** Free-text category (a specialty, Kayak, Room) that requirements match on. */
  role: string;
  /** Typed fields defined by its resource type. */
  attributes: Record<string, AttributeValue>;
  /** The resource it sits inside (property → unit); booking either blocks the other. */
  parentId: string | null;
  status: 'available' | 'out_of_service';
}

export interface Booking {
  id: string;
  locationId: string;
  locationName: string;
  offeringId: string;
  offeringName: string;
  kind: OfferingKind;
  /** Single-customer bookings. Classes use `attendees` instead. */
  customerId: string | null;
  customerName: string;
  attendees: Array<{ id: string; name: string }>;
  /** What it's for, when the offering serves a subject. */
  subjectId: string | null;
  subjectName: string | null;
  fields: Record<string, AttributeValue>;
  capacity: number;
  place: FulfilmentPlace;
  resourceIds: Array<string>;
  resourceNames: Array<string>;
  /** Wall-clock `YYYY-MM-DDTHH:MM` in the location's zone (`tz`). */
  start: string;
  end: string;
  tz: string;
  status: BookingStatus;
  price: Money;
  currency: string;
  paid: boolean;
}

/** A plan a customer holds; they may hold several. */
export interface Subscription {
  id: string;
  offeringId: string;
  name: string;
  unit: Offering['unit'];
  started: string;
  /** Monthly plans: `YYYY-MM-DD` it runs until. */
  renews: string | null;
  /** Packs: classes left. */
  credits: number | null;
  status: 'active' | 'cancelled';
}

export interface CustomerDocument {
  id: string;
  type: string;
  label: string;
  subjectId: string | null;
  issued: string;
  expires: string | null;
  reference: string;
  /** Valid today. */
  valid: boolean;
}

export interface Subject {
  id: string;
  type: string;
  typeLabel: string;
  name: string;
  customerId: string | null;
  accountId: string | null;
  fields: Record<string, AttributeValue>;
  expiredFields: Array<string>;
  active: boolean;
}

export interface Account {
  id: string;
  type: string;
  typeLabel: string;
  name: string;
  locationId: string;
  locationName: string;
  fields: Record<string, AttributeValue>;
  contacts: Array<{ id: string; name: string; role: string }>;
}

export interface Customer {
  id: string;
  locationId: string;
  locationName: string;
  name: string;
  phone: string;
  email: string;
  since: string;
  fields: Record<string, AttributeValue>;
  /** Keys of `expires` date fields that have passed. */
  expiredFields: Array<string>;
  account: { id: string; name: string; typeLabel: string; role: string } | null;
  /** Active plans. */
  subscriptions: Array<Subscription>;
  documents: Array<CustomerDocument>;
  /** Documents the policy here asks for with none valid today. */
  missingDocuments: Array<{ key: string; label: string }>;
  balance: Money;
  visits: number;
  spend: Money;
  lastVisit: string | null;
}

export type ChargeStatus = 'paid' | 'due' | 'overdue' | 'refunded';

export interface Charge {
  id: string;
  customerId: string;
  customerName: string;
  locationId: string;
  description: string;
  source: 'booking' | 'plan';
  amount: Money;
  /** The business's currency when it was raised. */
  currency: string;
  /** `YYYY-MM-DD` the charge was raised. */
  date: string;
  status: ChargeStatus;
  /** Set while it sits on an invoice. */
  invoiceId: string | null;
  /** The booking that raised it (its price, a drop-in seat, a fee); null for plans. */
  bookingId: string | null;
}

/** A customer invoice: open charges under one number, with tax per the business's settings when issued. */
export interface Invoice {
  id: string;
  /** `INV-0001`. */
  number: string;
  customerId: string;
  customerName: string;
  locationId: string;
  currency: string;
  taxLabel: string;
  taxRate: Money;
  pricesIncludeTax: boolean;
  subtotal: Money;
  tax: Money;
  total: Money;
  status: 'open' | 'paid' | 'void';
  issuedOn: string;
  paidOn: string | null;
  lines?: Array<{ id: string; description: string; date: string; amount: Money }>;
}

export interface Alert {
  id: string;
  tone: 'warn' | 'bad' | 'info';
  title: string;
  detail: string;
  /** Where the fix happens. */
  to: 'bookings' | 'customers' | 'payments' | 'calendar' | 'resources';
}

export interface Today {
  day: string;
  kpis: {
    bookings: number;
    checkedIn: number;
    expected: number;
    revenue: Money;
    utilization: number;
  };
  arrivals: Array<Booking>;
  inProgress: Array<Booking>;
  alerts: Array<Alert>;
  /** First-run checklist for a new business (docs/USAGE.md §6). */
  setup: {
    done: boolean;
    steps: { catalog: boolean; team: boolean; customers: boolean; policies: boolean; bookings: boolean };
  };
}

export interface Insights {
  days: number;
  revenue: { total: Money; previous: Money; series: Array<Money> };
  utilization: { staff: number; assets: number; previousStaff: number; previousAssets: number };
  noShowRate: { value: number; previous: number };
  /** Share of the previous period's customers who came back; `previous` is null when history is too short. */
  retention: { value: number; previous: number | null };
  newCustomers: { value: number; previous: number };
  topOfferings: Array<{ name: string; kind: OfferingKind; revenue: Money; bookings: number }>;
  locations: Array<{ id: string; name: string; revenue: Money; utilization: number }>;
}

/** Where a business stands with its Tenantly invoices (docs/BILLING.md §5.1). */
export type Standing = 'active' | 'past_due' | 'limited' | 'restricted' | 'canceled';

/** One priced edition of a Tenantly plan; prices are USD decimal strings. */
export interface PlanVersion {
  id: string;
  code: string;
  name: string;
  version: number;
  /** Honoured for this business, no longer offered. */
  legacy: boolean;
  /** A Custom plan agreed with Tenantly for this business only. */
  custom: boolean;
  currency: string;
  price: Money;
  /** Active customers the price covers each month; null: no limit. */
  included: number | null;
  /** Per active customer past `included`; null: no overage. */
  overagePrice: Money | null;
  /** A month never costs more than this (the next plan's price); null: the spend cap applies. */
  cap: Money | null;
  rank: number;
}

export type InvoiceLineKind = 'base' | 'overage' | 'cap' | 'discount' | 'credit';

export interface PlanLine {
  kind: InvoiceLineKind;
  amount: Money;
  quantity: number;
  unitPrice: Money | null;
  /** base: plan, version, from, until, prorated · overage: allowance, used · cap: cap · discount: percent */
  detail: Record<string, string | number | boolean | null>;
}

export type BillingNoticeKind =
  | 'threshold'
  | 'cap'
  | 'invoice'
  | 'paid'
  | 'plan_repriced'
  | 'card_failed'
  | 'overdue'
  | 'limit_warning'
  | 'limited'
  | 'restrict_warning'
  | 'restricted'
  | 'cancel_warning'
  | 'canceled';

export interface BillingNotice {
  id: number;
  kind: BillingNoticeKind;
  params: Record<string, string | number | null>;
  createdAt: string;
  read: boolean;
}

export interface BillingStanding {
  status: Standing;
  invoice: { id: string; number: string; dueOn: string; total: Money } | null;
  balance: Money;
  overdueDays: number;
  disputed: boolean;
  limitsOn: string | null;
  restrictsOn: string | null;
  cancelsOn: string | null;
  extensionAvailable: boolean;
  retentionUntil: string | null;
}

/** The Tenantly plan page in one read: every number is billing's, the page prices nothing. */
export interface Billing {
  currency: string;
  plan: PlanVersion;
  /** A downgrade waiting for the renewal. */
  scheduled: PlanVersion | null;
  status: 'active' | 'canceled';
  cancelAtPeriodEnd: boolean;
  standing: BillingStanding;
  /** Sent back with every change, so two people can't overwrite each other. */
  revision: number;
  canManage: boolean;
  payment: { method: 'manual' | 'stripe'; card: boolean; cardsAvailable: boolean };
  /** The billing policy's numbers the page quotes. */
  policy: { paymentTermsDays: number; extensionDays: number };
  alertThresholds: Array<number>;
  spendCap: { editable: boolean; value: Money | null; default: Money };
  /** `[start, end)`, ISO datetimes in UTC. */
  period: { id: number; start: string; end: string; status: 'open' | 'closing' | 'invoiced' | 'held' };
  usage: {
    metric: string;
    used: number;
    allowance: number | null;
    remaining: number | null;
    percent: number | null;
    /** Where the month lands at this pace; null early in the month. */
    projected: number | null;
    /** Customers newly counted per day of the period. */
    series: Array<number>;
  };
  estimate: { lines: Array<PlanLine>; total: Money; cap: Money | null; projectedTotal: Money | null };
  /** Shown for context, never billed. */
  informational: { bookings: number; payments: number; collected: { amount: Money; currency: string } };
  /** The public price list, each with what this period would cost on it. */
  plans: Array<PlanVersion & { thisPeriod: Money }>;
  notices: Array<BillingNotice>;
}

export interface PlanInvoice {
  id: string;
  number: string;
  periodStart: string;
  periodEnd: string;
  currency: string;
  total: Money;
  status: 'open' | 'paid' | 'void';
  issuedOn: string;
  dueOn: string;
  paidOn: string | null;
  paidVia: string | null;
  lines?: Array<PlanLine>;
}

export interface BillingHistory {
  periods: Array<{
    id: number;
    start: string;
    end: string;
    status: string;
    plan: string;
    used: number;
    allowance: number | null;
    invoice: PlanInvoice | null;
  }>;
  changes: Array<{
    kind: string;
    from: string | null;
    to: string | null;
    at: string;
    by: string;
    detail: Record<string, unknown>;
  }>;
}

/** Who was counted in a period, and why: the answer to "where does this number come from?". */
export interface CountedCustomers {
  periodId: number | null;
  start?: string;
  end?: string;
  total: number;
  customers: Array<{ customerId: string; name: string; firstSeenAt: string; source: string; reference: string }>;
}

// ------------------------------------------------------------ Tenantly admin --

/** A business's plan at a glance, from billing; null when billing is down or it isn't subscribed yet. */
export interface AdminBillingSummary {
  plan: string;
  currency: string;
  price: Money;
  status: Standing;
  used: number;
  allowance: number | null;
  periodEnd: string | null;
  openBalance: Money;
}

export interface AdminBusiness {
  id: string;
  slug: string;
  name: string;
  createdAt: string;
  members: number;
  billing: AdminBillingSummary | null;
}

/** Someone who owns at least one business; employees are never listed. */
export interface AdminOwner {
  id: string;
  name: string;
  email: string;
  createdAt: string;
  /** Restricted: signs in and reads only. Suspended: can't sign in. */
  status: OwnerStatus;
  statusChangedAt: string | null;
  businesses: Array<AdminBusiness>;
}

export type OwnerStatus = 'active' | 'restricted' | 'suspended';

/** The public tiers a business can start on; Custom terms are set afterwards on its subscription. */
export type StartingPlan = 'starter' | 'growth' | 'enterprise';

/** What the console sends to open a business for an owner. */
export interface NewBusiness {
  name: string;
  industry: string;
  locationName: string;
  currency: string;
}

/** A business the console just opened; `billingPending` when billing will set its plan on first use. */
export interface OpenedBusiness {
  id: string;
  slug: string;
  name: string;
  plan: StartingPlan;
  billingPending: boolean;
}

export interface AdminOwners {
  owners: Array<AdminOwner>;
  total: number;
  offset: number;
  limit: number;
  /** False when billing couldn't be reached: every `billing` is null for that reason. */
  billingAvailable: boolean;
}

export type GrantKind = 'extra_allowance' | 'discount_pct' | 'waive_overage' | 'extend_grace' | 'dispute';

export interface PlanGrant {
  id: number;
  kind: GrantKind;
  metric: string;
  value: string;
  validFrom: string;
  validUntil: string;
  reason: string;
  approvedBy: string;
}

/** One business's subscription as Tenantly staff see it. */
export interface AdminSubscription {
  tenantId: string;
  currency: string;
  plan: PlanVersion;
  scheduled: PlanVersion | null;
  status: 'active' | 'canceled';
  cancelAtPeriodEnd: boolean;
  standing: BillingStanding;
  revision: number;
  paymentMethod: 'manual' | 'stripe';
  period: { start: string; end: string; status: string } | null;
  usage: { used: number; allowance: number | null; projected: number | null };
  estimate: { lines: Array<PlanLine>; total: Money; cap: Money | null; projectedTotal: Money | null } | null;
  invoices: Array<PlanInvoice>;
  grants: Array<PlanGrant>;
  changes: BillingHistory['changes'];
  /** The public tiers offered. */
  plans: Array<PlanVersion>;
}

/** The signed-in Tenantly admin and what's left of their access window. */
export interface AdminViewer {
  id: string;
  name: string;
  email: string;
  activeUntil: string | null;
  remainingSeconds: number;
}

/** A public plan version with who's on it and this period's usage. */
export interface AdminPlan extends PlanVersion {
  status: 'active' | 'legacy' | 'draft';
  effectiveFrom: string;
  subscribers: number;
  /** Businesses scheduled to move onto it at their next renewal. */
  scheduledIn: number;
  usage: { used: number; over: number };
}

export interface AdminPlans {
  plans: Array<AdminPlan>;
  customSubscribers: number;
}

/** One version of the billing policy (billing's `BillingPolicy`). */
export interface BillingPolicy {
  version: number;
  limitAfterDays: number;
  restrictAfterDays: number;
  cancelAfterDays: number;
  paymentTermsDays: number;
  smallBalance: Money;
  extensionDays: number;
  extensionEveryDays: number;
  retentionDays: number;
  usageGraceHours: number;
  spendCapMultiple: string;
  alertThresholds: Array<number>;
  effectiveAt: string | null;
  editedBy: string;
  reason: string;
}

export interface AdminPolicy {
  current: BillingPolicy;
  history: Array<BillingPolicy>;
}

export type PolicyFields = Omit<BillingPolicy, 'version' | 'effectiveAt' | 'editedBy' | 'reason'>;

export interface AdminAuditEvent {
  id: number;
  at: string;
  kind: 'created' | 'activated' | 'login' | 'login_denied' | 'expired' | 'blocked' | 'action';
  action: string;
  admin: { id: string; name: string; email: string } | null;
  targetType: string;
  targetId: string;
  before: unknown;
  after: unknown;
  ip: string;
}

export interface AdminAudit {
  events: Array<AdminAuditEvent>;
  total: number;
  offset: number;
  limit: number;
}

# Tenantly — Plans, Usage and Billing

> Status: **implemented** (2026-10-12). It replaces the old tier-jump plan. § 12 maps the
> design to the code and lists where the code differs from the design.
> Related: [ARCHITECTURE.md](./ARCHITECTURE.md) · [PRODUCT.md](./PRODUCT.md) · [PLATFORM.md](./PLATFORM.md)

Labels used throughout:

- **[FACT]**: seen in the repository, with a file reference.
- **[ASSUMPTION]**: not in the repository; needs confirmation.
- **[REC]**: a recommendation.

Naming: in this codebase a *plan* or *subscription* is already **a tenant's customer's plan**
(operations `Subscription`, offerings with `time = none`). To keep the two apart, this document
says **Tenantly plan** and **tenant subscription** for what Tenantly sells to a business. The
code uses `PlanVersion` and `TenantSubscription`.

---

## 1. Existing architecture (what the repository has today)

| Area | Fact | Where |
|---|---|---|
| Services | Three Django services (identity, operations, billing), each with **its own Postgres DB**, behind nginx. SolidStart frontend calls them through the proxy. | `docs/ARCHITECTURE.md`, `compose.yml` |
| Tenant identity | `Tenant` row in identity. Every row in operations and billing carries `tenant_id`; every query filters by it. | `identity-service/src/models/tenant.py` |
| Tenant isolation | 5-minute HS256 tenant JWT; services take `tenant_id` **only from the token** and check permissions there (`claims.demand`). `/internal/*` routes need `X-Internal-Token`; the proxy 404s them. | `common/auth.py`, `common/internal.py` |
| Permissions | `billing.view` and `billing.manage` exist ("View / Manage Tenantly plan"). There is **no endpoint that uses `billing.manage`**. | `identity-service/src/types/roles.py:24` |
| Current Tenantly plan | `Tenant.plan` (`Starter`/`Growth`/`Enterprise`/`Custom`) plus `Tenant.plan_terms` JSON for Custom. Set only by Tenantly via `PUT /internal/tenants/{id}/plan` or `manage.py set_plan`, audited as `plan.changed`. | `identity-service/src/services/plan.py`, migration `0014_usage_plans.py` |
| Prices and limits | Constants in code: Starter $29 (50 customers / 500 payments), Growth $49 (100 / 1,000), Enterprise $89 (200 / 2,000), USD. | `billing-service/src/services/plans.py` |
| Usage | **Computed live on every page load** from `Charge` rows since the 1st of the month: distinct `customer_id` and count of charges. Nothing is stored. | `billing-service/src/services/charges.py:month_usage` |
| Overage rule | A month past its tier's limits is "billed on the smallest tier that fits". Past Enterprise it shows "ask for Custom". | `plans.billed_tier` |
| Tenant invoices | None. `nextInvoice.estimate` is the tier price. No Tenantly invoice, payment, or period record exists. | `plans.usage` |
| Customer billing | `Charge` (due/paid/refunded, idempotent on `(tenant_id, key)`) and customer `Invoice`. This is the tenant billing **its** customers, unrelated to Tenantly billing the tenant. | `billing-service/src/models/` |
| Reliable cross-service writes | Operations writes `MoneyEvent` rows **in the same transaction** as the booking change and sends them after commit, in order per tenant, keyed `ops-<id>`. The `operations-outbox` container retries every 30 s. `MoneyEvent` is generic (`path` + `body`). | `operations-service/src/models/outbox.py`, `services/money.py`, `compose.yml` |
| Audit | Hash-chained per tenant in identity. Operations and billing write it inside their transaction and roll back if it fails. | `common/internal.py:audit`, `identity-service/src/services/ledger.py` |
| Frontend | `/t/$org/billing` renders `GET /billing/plan` as two meters (customers, payments) and a tier table. Read-only. | `frontend/src/routes/t.$org.billing.tsx`, `frontend/src/lib/tenancy.ts:getBilling` |
| Not present | Payment provider, email/SMS delivery, notifications, background scheduler (other than the outbox loop), public API, file storage (documents are metadata rows only). | `docs/ARCHITECTURE.md` § Known limits |

### Operations that cost Tenantly something

[FACT] Every write is a Postgres row in a shared deployment. No third-party paid calls exist
(no payments, email, SMS or file storage). Cost therefore grows with **request and row volume**,
which tracks how many customers a business serves and how many bookings it handles.
[ASSUMPTION] There are no large fixed costs per tenant beyond hosting.

---

## 2. Problems and opportunities found

| # | Problem (fact) | Consequence |
|---|---|---|
| P1 | `month_usage` counts **every** charge since the 1st: refunded ones, no-show/late fees and plan sales included. | A refund or a fee raises the tenant's usage. Hard to explain. |
| P2 | Cancelling a booking **deletes** its due charges (`refund_booking`). | Usage can **go down** during the month. It isn't monotonic, so it can't be audited. |
| P3 | $0 bookings never raise a charge, so they never count. | Usage doesn't reflect the work done. Free trial sessions are invisible. |
| P4 | Usage is derived from `Charge.date`, a business date that operations sets in the location's time zone. The month boundary uses billing's UTC `today()`. | Events near midnight on the 1st can fall in either month. A back-dated charge changes a past month. |
| P5 | No stored usage, periods or Tenantly invoices. | There's no history, no evidence in a dispute and no "what you were billed and why". |
| P6 | Tier cliff: 51 customers on Starter bills Growth (+$20) for one extra customer. | This is the classic source of complaints about surprise bills. |
| P7 | Prices are code constants with no version or effective date. Custom terms are untyped JSON in another service. | A price change in code retroactively changes the current month's estimate. |
| P8 | The plan name lives in identity and the prices in billing, so every page load makes a cross-service call. | Split ownership and an extra point of failure. |
| P9 | `collectedThisMonth` sums due and refunded charges too. | It's labelled "collected" but isn't. |
| P10 | No self-serve plan change, period, subscription state, alerts or payment integration. | Everything is manual. Customers can't anticipate their bill. |

Opportunity: the **outbox pattern, idempotent keys and per-tenant audit already exist** and are
exactly what reliable usage metering needs. The design reuses them instead of adding
infrastructure.

---

## 3. Usage metrics

### Candidates evaluated

| Candidate | Unit generated by | Reflects value? | Reflects cost? | Verdict |
|---|---|---|---|---|
| **Active customers / period** | First qualifying "served" event for a customer in the period | **High**: the business's revenue scales with the customers it serves | Good: rows and requests scale with customers | **Billable** |
| Completed bookings | Booking → `completed` | Medium: a gym's 30-a-month member is one customer but 30 bookings | Good | **Fair-use limit** and informational |
| Payments recorded (current meter) | Charge raised | Low: no processor, so a payment is just a row. Fees and refunds inflate it. | Low | **Informational only** |
| Revenue processed | Sum of charges | Medium | None: there's no processor cost | **Not billable**: feels like a tax and varies with currency |
| Team members (seats) | Membership | Low | Low | **Not billable** (product principle "never seats", `docs/ARCHITECTURE.md`) |
| Locations | `Node` of kind `location` | Medium | Low | **Informational**. Could become a plan limit later. |
| Storage / API / jobs | n/a | n/a | n/a | **Not applicable today**: no file storage, public API or tenant jobs exist |
| Messages sent (future) | Email/SMS delivered | High | **Direct third-party cost** | **Future, prepaid packs**, once delivery exists |

### Recommended billable metric: `active_customers`

[REC] **One billable metric.** A business pays for the number of distinct customers it actually
served or sold to in the billing period. "You served 63 customers this month" is a sentence
an owner can check against their own day.

| Question | Answer |
|---|---|
| 1. What generates a unit? | A customer becomes *active* in a period on their **first** qualifying event: (a) a booking of theirs moves to `checked_in` or `completed`; (b) they **join a class session** (an `Attendance` row); (c) a **plan is sold** to them (`parties.sell`). Later events for the same customer in the same period add nothing. |
| 2. When is it recorded? | In operations, **inside the same DB transaction** as the status change, join or sale, as an outbox row. Billing records it when the outbox delivers it, usually within seconds. |
| 3. Once or recurring? | Once per customer **per period**. The same customer counts again next period if served again. |
| 4. Failed / cancelled / retried / reversed? | Failed op: the transaction rolls back, so no event exists. Retried op: the outbox key `ops-<id>` makes delivery idempotent. **Operational reversal** (a class session is called off, so its attendances are void) sends a reversal event. The customer stops counting only if they have no other qualifying event in that still-open period. **Financial refunds don't reverse usage**, because the service was delivered. No-shows don't count (not served). Reversals after the period closed are recorded but don't change a closed invoice. |
| 5. Duplicate prevention | (i) Outbox key unique per tenant; (ii) `UsageRecord` unique on `(tenant_id, idempotency_key)`; (iii) `ActiveSubject` unique on `(period, metric, subject_key)`, so a customer can't be counted twice. |
| 6. Audit in a dispute | Every counted customer has `UsageRecord`s pointing at the source (`booking:<id>`, `attendance:<id>`, `sale:<subscription id>`) with timestamps. The tenant can download the list "customers counted this period, and why" and match it against their own bookings. |
| 7. Value / cost fit | It scales with the business's revenue and with platform load. It's insensitive to how often a loyal customer visits, which is the fair choice for gyms (P6, P1). |

[ASSUMPTION] Class sessions are confirmed when scheduled and attendees are known at join time. If
businesses rarely mark sessions completed, counting at join (with reversal) is more reliable
than counting at completion.

### Operational (fair-use) limit: `bookings`

Completed bookings per period. **Never billed and never blocks.** It's an abuse signal: for
example, more than 60 bookings per active customer averaged over a period alerts Tenantly
staff, not the tenant. It's recorded in the same pipeline.

### Informational metrics

Payments recorded, revenue collected (fixed: only `paid`, P9), locations, team members. They're
shown on the dashboard for context, computed on read, and not billed.

---

## 4. Commercial plans and billing strategy

### Strategies compared

| Strategy | Pros | Cons / risks |
|---|---|---|
| **Step up to the next tier** (today) | Simple. No per-unit maths. | Cliff (P6). One customer can cost $20 to $40. This is the top complaint driver. |
| **Hard cap at the allowance** | Fully predictable bill. | Blocks a business from serving a customer at the front desk, which is unacceptable for a booking product. |
| **Included allowance + per-unit overage** | Smooth. Pay for what you use. | Unbounded bill unless capped. Needs clear display. |
| **Prepaid usage packs** | Predictable. Cash up front. | Packs expire or run out. Suits pass-through costs (SMS) better than core usage. |
| **Upgrade the plan** | Raises revenue cleanly. | Only for sustained growth, never as a one-month penalty. |

### Recommended: allowance + overage, capped at the next tier ("never pay more than the next plan")

[REC] Each tier has a **base fee**, an **included allowance** of active customers and an
**overage price** per extra active customer. The overage for a period is **automatically
capped** so that the period total never exceeds the next tier's base fee. A business that grows
past its tier pays a little more for each extra customer, never a cliff. If growth is
sustained, the dashboard shows that upgrading is cheaper or equal.

Past the top published tier, overage continues at the top tier's rate, bounded by a
**tenant-set monthly spend cap** (default: 2× the Enterprise base). Once the cap is reached, the
business **keeps working**. Tenantly absorbs the excess for that period and contacts the owner
about a Custom plan (see Q2 in § 11).

### The price list (catalog v2, public from 2026-10-12)

| Tier | Base / month | Included active customers | Each one past that | Period total never passes |
|---|---|---|---|---|
| Starter | $29 | 75 | $0.40 | $59 (Growth's price), reached at 150 customers |
| Growth | $59 | 200 | $0.30 | $129 (Enterprise's price), reached at ≈434 customers |
| Enterprise | $129 | 500 | $0.25 | The business's spend cap (default $258, 2× the base) |
| Custom | Agreed | Agreed | Agreed, or none | Agreed |

Every feature is on every tier. Tiers differ only in how much usage they include and what it
costs per customer.

**Why these prices are fair.** They're assumptions to review with real data, and the usage
ledger now provides that data.

- **For the business: about 1% of what it takes in, falling as it grows.** At an assumed
  average of $30 a customer per month ([ASSUMPTION]), 75 customers bring in about $2,250, so
  Starter is 1.3% of that. Growth at 200 customers is about 1.0%, and Enterprise at 500 about
  0.9%. A solo practitioner serving 20 customers pays the same $29 with room to grow.
- **Per customer, it gets cheaper as you grow.** Included customers cost 39¢, 30¢ and 26¢ on the
  three tiers. Overage is priced at about the included rate (40¢, 30¢, 25¢), so going over the
  allowance is never a penalty, just pay-as-you-go.
- **Growing never costs more than upgrading.** Each tier's cap is the next tier's price. The cap
  is reached well before the next tier's allowance (150 < 200, ≈434 < 500), so the page can
  always say "Growth costs the same and includes more" before anyone pays more than Growth.
- **Against the market** ([ASSUMPTION]: typical list prices, verify before launch). Single-
  calendar booking tools usually cost about $10–$50 a month. Full studio and gym suites often
  cost $100–$400+ a month per location. Tenantly includes multiple locations, roles and an
  audit trail on every tier. It starts at the low end and stays well below per-location suites
  at scale.
- **For Tenantly:** the marginal cost of an active customer is a few database rows and requests
  in shared infrastructure, fractions of a cent ([ASSUMPTION]: no paid third-party calls exist
  yet). The margin covers support and development. Review these numbers after three
  invoiced periods.

**Businesses already subscribed keep their prices** (catalog v1, `legacy`: $29 for 50 customers,
$49 for 100, $89 for 200). The old cliff ("billed on the next tier") becomes per-customer
overage capped at that same next tier's price ($0.50 a customer on Starter, $0.40 on Growth).
Enterprise v1 never had overage and still doesn't, so **no one pays more than under the old
rules**. They move to v2 only by choosing to, or after a 30-day notice applied at a renewal
(not automated yet, see § 12).

Rules that prevent complaints:

- **No retroactive prices.** Every price lives in an immutable `PlanVersion`. A tenant stays on
  its version until it moves, or until a new version is announced at least 30 days in advance
  and applied at a renewal ([ASSUMPTION]: notice period).
- **Unused allowance doesn't roll over** (stated on the page). A rollover makes "how much do I
  have" ambiguous.
- **The estimate is always shown**: base, prorations, overage so far, cap, and a projection to
  the period end.

---

## 5. Business rules

| Scenario | Behaviour |
|---|---|
| **Within allowance** | Nothing visible beyond the meter. Estimate = base. |
| **80% of allowance** | One in-app notice and a dashboard banner per period (and an email once delivery exists). The notice shows the projection to period end and the overage price. Thresholds are configurable (§ 7). |
| **100% of allowance** | A notice: "From now on each new customer this month adds $0.40, up to $30 more ($59 total). Growth costs the same and includes 200." **Nothing is blocked.** |
| **Exceeds allowance** | Overage accrues per new active customer up to the cap. The meter turns amber, then shows "cap reached". The cap notice fires once. |
| **Reaches spend cap (top tier)** | Operations continue. Usage is still recorded and shown as "not billed (over your cap)". The owner and Tenantly staff are notified. |
| **Wants more capacity** | Upgrade (below). There are no separate add-on packs for active customers. Packs are reserved for future pass-through metrics. |
| **Upgrade** | **Immediate.** The base fee is prorated by days: old tier until the change, new tier after. Overage for the whole period is computed against the **new, larger allowance**, so upgrading never costs more than not upgrading. Recorded as a `SubscriptionChange`. |
| **Downgrade** | **Scheduled for the next renewal.** No refunds and no data loss. Before confirming, the page shows last period's usage priced on the lower tier. Usage above the new allowance becomes overage, never a block. The downgrade can be withdrawn until renewal. |
| **Renewal** | At `period_end`, a period-close job (1) freezes the counter after a **72-hour grace** for late outbox events, (2) issues the `PlanInvoice` from the frozen counter, (3) opens the next period on the current or scheduled version. The allowance resets and doesn't roll over. |
| **Cancellation** | Takes effect at period end (`cancel_at_period_end`). That period is billed normally. After it, the workspace becomes **read-only for 30 days** (export allowed), then follows the data-retention policy ([ASSUMPTION], Q5). It can be undone until it takes effect. |
| **Payment fails** | Graduated, see **§ 5.1**. `active → past_due` (full access) → `limited` at day 14 (no new customers) → `restricted` at day 30 (no new bookings) → `canceled` at day 45 (read-only for 90 days). Paying restores `active` immediately at any stage. |
| **Customer refund / reversal** (tenant refunds its own customer) | Doesn't change usage. The service was delivered. A **class session called off** reverses its attendances' usage while the period is open. |
| **Tenantly refund to a tenant** | A `PlanInvoiceLine` of kind `credit` on the next invoice, or a provider refund. Never an edit of an issued invoice. |
| **Concurrent requests** | Counting a customer is a unique insert plus an atomic counter update in one transaction (§ 8). Two simultaneous first bookings for the same customer count once. Two different customers both count. Only the transaction that crosses a threshold sends its notice. |
| **Duplicate / out-of-order provider events** | Stored in `ProviderEvent` unique on `(provider, event_id)`, so duplicates are ignored. Each event is applied only if it moves the invoice or subscription **forward** in its state machine, judged by the provider object's own timestamp. Stale events are stored and marked `skipped`. |
| **Mid-period plan change and usage** | Usage belongs to the **period**, not the plan. Changing plans never resets or loses usage. |
| **Historical data** | Periods, counters, usage records and invoices are kept and never rewritten. Closed periods are immutable. Corrections are credit lines. |
| **Commercial exceptions** | `EntitlementGrant` rows (extra allowance, discount, waived overage, extended grace). They're time-bounded, carry a reason and the approver, are audited, and are created only by Tenantly staff. Custom plans are private `PlanVersion`s (tenant-scoped), not JSON. |

### 5.1 Delinquency policy

> The numbers below are the **first version of the billing policy**. They're data now: a
> versioned `BillingPolicy` row (billing `models/policy.py`, `services/policy.py`) that Tenantly
> admins edit from the console, a new version each time with who and why. Days 14 / 30 / 45,
> 14-day terms, the $5 small balance, the 7-day extension once every 365 days, 90 days of
> retention, the 72-hour usage grace, the default spend cap (2 × the base price) and the default
> alert thresholds (80 %, 100 %) are read from the version in force; warnings go out 3, 5 and 5
> days before limiting, restricting and canceling.

**Day 0 is the invoice's due date, not its issue date**, and day 1 is the first day it's late.
For card payments (Stripe) the due date is the day the invoice is issued and charged. For manual
invoices it's the issue date plus 14 days' payment terms.

| Day | State | Access | Communication |
|---|---|---|---|
| 0–14 | `past_due` | **Full.** Stripe Smart Retries run. | Reminders on days 0, 3 and 7. Banner for every owner. On day 11: "On Oct 25 you won't be able to add new customers." |
| 14 | `limited` | Everything works except **adding new customers** and changing plans upward. Existing customers can still book. | Persistent banner. "Pay now" and "Update card" always available. |
| 30 | `restricted` | **New bookings are also refused.** Check-ins, completions, cancellations, collecting payments, exports and the billing page keep working. | Warning on day 25 with the exact date and what stops. |
| 45 | `canceled` | Workspace **read-only** with export. A final invoice is prorated to day 45. | Notice with the deletion date. |
| 45–135 | `canceled` (retention) | Read-only and export. **Paying the balance reactivates everything** without data loss or a reactivation fee. | Deletion warnings 30 and 7 days before. |
| 135 | Deleted | Tenant data deleted. Tenantly's own invoices to the tenant are kept as long as tax law requires. | Confirmation to owners. |

Fairness safeguards:

- **Disputes pause the clock.** Staff flag a disputed invoice (`EntitlementGrant` of kind
  `extend_grace`), and the escalation stops until it's resolved.
- **A self-serve 7-day extension**, once per 12 months, from the billing page.
- **Small balances never restrict**: below a threshold ([ASSUMPTION] $5), only reminders.
- **Paying restores access immediately.** Webhook or staff mark-paid moves the state to `active`
  in the same transaction. There's no wait for the next token: the frontend refreshes the token
  on the billing page after payment.
- Usage keeps being metered during delinquency so history stays complete. There are no late
  fees.

---

## 6. Data model

[REC] **Everything lives in the billing service's DB.** Billing already owns money and the plan
prices. Identity stops owning the plan name (P8). There's no new service: the volume is small (one
row per customer per period, plus a counter) and the existing outbox carries the events.

All tables carry `tenant_id` (UUID) except the global catalog. Every tenant-facing query filters
by the token's tenant.

### Catalog

**`PlanVersion`**: immutable once `active`.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| code | varchar(30) | `starter`, `growth`, `enterprise`, `custom-<slug>` |
| version | int | |
| name | varchar(60) | Display name |
| tenant_id | UUID null | Set for a **private** (Custom) plan |
| currency | char(3) | `USD` |
| base_price | decimal(10,2) | |
| included | jsonb | `{"active_customers": 50}` |
| overage_price | jsonb | `{"active_customers": "0.50"}`. A missing key means no overage. |
| overage_cap | decimal(10,2) null | Period total ceiling. Null means the tenant spend cap applies. |
| rank | smallint | Ordering for upgrade / downgrade |
| status | `draft` / `active` / `retired` | |
| effective_from | timestamptz | |

Constraints: `UNIQUE(code, version)`; `CHECK(base_price >= 0)`; an app-level guard refuses
updates to price fields when `status != 'draft'`. Index: `(status, tenant_id)`.

### Subscriptions

**`TenantSubscription`**: one current row per tenant.

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID | |
| plan_version | FK PlanVersion | |
| status | `trialing` / `active` / `past_due` / `limited` / `restricted` / `canceled` | See § 5.1 |
| payment_method | `manual` / `stripe` | |
| delinquent_since | date null | Due date of the oldest unpaid invoice; drives § 5.1 |
| current_period | FK BillingPeriod | |
| scheduled_plan_version | FK null | Pending downgrade |
| cancel_at_period_end | bool | |
| spend_cap | decimal(10,2) null | Set by the tenant (`billing.manage`) |
| alert_thresholds | int[] | Default `{80,100}` |
| provider_customer_ref | varchar null | |
| revision | int | Optimistic lock for changes |
| created_at, updated_at | timestamptz | |

Constraints: `UNIQUE(tenant_id) WHERE status <> 'canceled'` (partial).

**`SubscriptionChange`**: append-only history.
Fields: `subscription FK, kind (created/upgrade/downgrade_scheduled/downgrade_applied/cancel_scheduled/cancel_withdrawn/canceled/status_changed/grant_added), from_version, to_version, from_status, to_status, effective_at, actor_id, actor_name, reason, idempotency_key`.
`UNIQUE(subscription, idempotency_key)`; index `(subscription, effective_at)`.

**`EntitlementGrant`**: authorised exceptions.
Fields: `tenant_id, metric null, kind (extra_allowance/discount_pct/waive_overage/extend_grace), value decimal, valid_from, valid_until, reason, approved_by, created_at`.
`CHECK(valid_until > valid_from)`; index `(tenant_id, valid_from, valid_until)`.

### Usage

**`BillingPeriod`**

| Field | Notes |
|---|---|
| id, tenant_id, subscription FK | |
| starts_at, ends_at | timestamptz in UTC, `[start, end)` |
| status | `open` / `closing` / `closed` / `invoiced` |
| plan_snapshot | jsonb: the versions and prorations in effect (filled at close) |

Constraints: `UNIQUE(tenant_id, starts_at)`; exclusion constraint (Postgres
`btree_gist`) so no two periods of a tenant overlap; `CHECK(ends_at > starts_at)`.

**`UsageRecord`**: the append-only evidence ledger.

| Field | Notes |
|---|---|
| id (bigserial), tenant_id, period FK | |
| metric | `active_customers` / `bookings` |
| subject_key | Customer id (`active_customers`) or booking id |
| source | `booking.checked_in` / `booking.completed` / `attendance` / `plan.sold`, plus `reversal` |
| source_ref | e.g. `booking:<uuid>` |
| delta | +1 / −1 |
| occurred_at | When it happened in operations |
| recorded_at | When billing stored it |
| late | bool: arrived after the period closed |
| idempotency_key | `ops-<outbox id>` |

Constraints: `UNIQUE(tenant_id, idempotency_key)`; `CHECK(delta IN (-1, 1))`. Indexes:
`(period, metric, subject_key)` and `(tenant_id, occurred_at)`.

**`ActiveSubject`**: one row per counted subject per period. This is what makes a distinct count
safe under concurrency.
Fields: `period FK, metric, subject_key, sources int, first_seen_at`.
`UNIQUE(period, metric, subject_key)`; `CHECK(sources >= 0)`.

**`UsageCounter`**: the aggregate the dashboard and invoice read.
Fields: `period FK, tenant_id, metric, quantity int, notified int[]` (thresholds already sent), `updated_at`.
`UNIQUE(period, metric)`; `CHECK(quantity >= 0)`.

### Invoicing, payments, notifications

**`PlanInvoice`**: Tenantly → tenant. It's separate from the existing customer `Invoice`.
Fields: `tenant_id, period FK, number, currency, subtotal, total, status (draft/open/paid/void/uncollectible), issued_at, due_at, paid_at, provider_ref`.
`UNIQUE(period)`; `UNIQUE(number)` (global sequence, `TNT-000123`).

**`PlanInvoiceLine`**: `invoice FK, kind (base/proration/overage/cap_adjustment/credit/grant), description, quantity, unit_price, amount, plan_version FK null`.

**`ProviderEvent`**: the inbox for payment-provider webhooks.
`provider, event_id, type, object_ref, occurred_at, payload jsonb, status (applied/skipped/failed), received_at`.
`UNIQUE(provider, event_id)`.

**`BillingNotice`**: in-app notifications (with email later).
`tenant_id, period FK null, kind (threshold/cap/payment_failed/downgrade_scheduled/price_change…), threshold int null, body jsonb, created_at, read_at`.
`UNIQUE(period, kind, threshold)` so a threshold notice is sent once per period.

### Existing tables touched

- identity `Tenant.plan`, `Tenant.plan_terms`: migrated into `TenantSubscription` and a private
  `PlanVersion`, then dropped in a later release. `manage.py set_plan` moves to billing.
- operations `MoneyEvent`: **reused as is** for usage events (`path = /internal/usage`). It's
  already a generic, ordered and retried outbox. [REC] Renaming it to `OutboxEvent` is optional
  and cosmetic.

---

## 7. Workflows and pseudocode

### 7.1 Usage tracking: operation to meter

```
browser ─► operations (tenant JWT)
  1. claims = verify token                      # tenant_id only from the token
  2. validate the op (status move, join, sale)  # existing rules
  3. BEGIN
       apply the business change
       if billable(op):   outbox.add("/internal/usage", {customerId, source, sourceRef, occurredAt})
       money/audit as today
     COMMIT                                     # change and usage event commit together, or neither
  4. on_commit → dispatch()                     # existing outbox; retried every 30 s on failure

operations-outbox ─► billing POST /internal/usage   (X-Internal-Token, key = ops-<id>)
  5. record_usage(...)  (below)
  6. thresholds crossed → BillingNotice (+ email later)
  7. dashboard / invoice read UsageCounter; disputes read UsageRecord
```

If operations crashes after the commit but before sending, the event is still in the outbox and
is sent on the next loop. If it crashes before the commit, neither the change nor the usage
happened. **Usage can't be lost or invented separately from the business change.**

```python
# billing/services/usage.py
@transaction.atomic
def record_usage(tenant_id, metric, subject_key, source, source_ref, delta, occurred_at, key):
    if UsageRecord.objects.filter(tenant_id=tenant_id, idempotency_key=key).exists():
        return                                              # replay: already applied
    period = period_for(tenant_id, occurred_at)             # SELECT … FOR SHARE
    late = period.status != "open"
    rec = UsageRecord.objects.create(..., late=late)        # UNIQUE key: a concurrent replay fails here → rolled back, then treated as a replay
    if late:
        return                                              # evidence kept; closed invoices untouched
    subj, _ = ActiveSubject.objects.get_or_create(period, metric, subject_key)  # unique, race-safe with retry
    subj = ActiveSubject.objects.select_for_update().get(pk=subj.pk)
    before = subj.sources
    subj.sources = max(0, before + delta); subj.save()
    change = (+1 if before == 0 and subj.sources > 0 else -1 if before > 0 and subj.sources == 0 else 0)
    if change:
        old, new = UsageCounter.objects.filter(period=period, metric=metric) \
                     .update_returning(quantity=F("quantity") + change)   # one atomic UPDATE … RETURNING
        for t in crossed(old, new, allowance(period, metric), thresholds(tenant_id)):
            BillingNotice.objects.get_or_create(period=period, kind="threshold", threshold=t, ...)
```

### 7.2 Enforcement

There are no quota checks in operations for `active_customers`, because the limit is commercial,
not technical. Enforcement is limited to the **subscription status**, which is checked
synchronously:

```
identity, when issuing a tenant token:
    status = billing GET /internal/tenants/{id}/entitlements   # cached 60 s; fails open to "active"
    claims["billing"] = {"status": status}
operations, on create-booking / add-customer / sell-plan:
    if op == "add-customer" and status in ("limited", "restricted"): raise ForbiddenError(…)
    if op in ("create-booking", "sell-plan") and status == "restricted": raise ForbiddenError("Your Tenantly invoice is overdue …")
    if status == "canceled": every write refused (read-only)
```

The backend enforces it on every write, never the frontend alone. The ≤ 5-minute token lag is
acceptable for a state that escalates over days. A payment re-issues the token right away (§ 5.1). Billing failing open means a billing
outage never stops a front desk.

### 7.3 Plan change

```python
@transaction.atomic
def change_plan(claims, target_code, revision, idempotency_key):
    claims.demand("billing.manage")
    sub = TenantSubscription.objects.select_for_update().get(tenant_id=claims.tenant_id, status__in=LIVE)
    if done := SubscriptionChange.objects.filter(subscription=sub, idempotency_key=idempotency_key).first():
        return done                                           # double-click / retry
    if sub.revision != revision: raise ConflictError          # someone else changed it
    target = PlanVersion.current_public(target_code)          # server resolves price; client never sends one
    if target.rank > sub.plan_version.rank:  apply_upgrade_now(sub, target)   # proration recorded on the period
    elif target.rank < sub.plan_version.rank: sub.scheduled_plan_version = target
    sub.revision += 1; sub.save(); SubscriptionChange.create(...); audit(...)
```

### 7.4 Period close (daily job: `manage.py close_periods`, a container like `operations-outbox`)

```
for period in BillingPeriod.open where ends_at + 72h <= now:   # SELECT … FOR UPDATE SKIP LOCKED
    period.status = closing
    lines = base(prorated by versions) + overage(min(counter - allowance - grants, cap)) + credits
    PlanInvoice.create(period, lines)        # UNIQUE(period): a rerun can't double-invoice
    open next period on scheduled_plan_version or current; apply cancel_at_period_end
    period.status = invoiced
reconcile(period): assert counter.quantity == count(ActiveSubject where sources > 0)
                   and each ActiveSubject.sources == sum(UsageRecord.delta not late)
                   → mismatch: alert staff, invoice held in draft (never auto-"fixed")
```

### 7.5 Payment provider (only when one is chosen, Q3)

```
POST /billing/webhooks/<provider>   (public, signature verified, no tenant token)
  verify signature → INSERT ProviderEvent ON CONFLICT DO NOTHING → if duplicate: 200
  apply in a transaction with the invoice/subscription row locked;
  skip if event.occurred_at < row.last_provider_event_at (out of order)
```

---

## 8. Security, consistency and idempotency

| Threat | Control |
|---|---|
| Reading another tenant's usage | `tenant_id` comes only from the JWT (existing). Every query filters by it. Tests cover cross-tenant ids returning 404. |
| Raising own limits | There's no tenant-facing write to `PlanVersion`, `EntitlementGrant` or `UsageCounter`. Tenants can only pick a **public** plan code and set `spend_cap` / `alert_thresholds` (`billing.manage`, owner-only by default). Grants come from staff only, through the CLI or internal route, with a reason, and are audited. |
| Fraudulent usage events (inflating or deflating) | `/internal/usage` needs `X-Internal-Token`, and the proxy 404s `/internal/`. Only operations, from its own committed state, emits events. Tenants can't submit usage. |
| Bypassing tracking with concurrency | The usage event is in the **same transaction** as the change. Distinct counting relies on the unique `ActiveSubject` row plus a row lock. There's no "check, then write" window. |
| Replaying events for charges or credits | `UNIQUE(tenant_id, idempotency_key)` on usage. `UNIQUE(provider, event_id)` on webhooks. `UNIQUE(period)` on invoices. `UNIQUE(subscription, idempotency_key)` on changes. Credits only as staff-created invoice lines. |
| Manipulating subscription state from the frontend | State moves only server-side (`change_plan`, the close job, verified webhooks). The client sends a plan **code** and a revision, never prices or statuses. The frontend's display of status is cosmetic: operations re-checks the token claim. |
| Webhook spoofing | Signature verification, timestamp tolerance, and events applied by re-fetching the object from the provider when in doubt. |

Consistency summary: an outbox carries usage from operations to billing (at least once).
Idempotent keys make it effectively once. Closed periods are immutable. Reconciliation checks
before every invoice. The invoice is held when the numbers disagree.

---

## 9. Customer experience

Billing page (`/t/$org/billing`), top to bottom:

1. **Header**: current plan (version name), price, status pill (Active / Payment due / Restricted
   / Cancels on …), period `Oct 1 – Oct 31`, renews on `Nov 1`.
2. **This period**: one large meter, "63 of 50 active customers". Bands at 80% and 100%, then
   overage up to the cap marker. Below it: "**$35.50 so far** ($29 base + 13 × $0.50). Projected
   by Oct 31: $41 (cap $49)." Plus a single-sentence comparison when relevant: "Growth would cost
   $49 with 100 included."
3. **Who counted**: a paginated list of active customers this period with their first qualifying
   event and date, exportable as CSV. This is the dispute answer.
4. **History**: the last 12 periods (bar chart of active customers against the allowance) and
   their invoices with line items.
5. **Plan**: a table of public plans with allowance, overage and cap. Upgrade (immediate,
   showing the prorated amount before confirming) and downgrade (shown "from Nov 1").
   Cancel / undo.
6. **Alerts**: thresholds (default 80% and 100%, editable), spend cap (top tier and Custom), who
   receives them (owners by default).
7. **Informational**: bookings, payments recorded, revenue collected, locations. Labelled
   "not billed".

Notices are actionable sentences with the money impact and the choice: *"You've reached your 50
included customers. Each new customer this month adds $0.50, up to $20. [Upgrade to Growth] [Set
alerts]"*. Every price change is announced at least 30 days ahead and shown on the page until it
applies.

Complaint prevention: no cliffs, no blocks for usage, no retroactive prices, every number
traceable to named customers, invoices that itemise base, proration and overage, and a cap.

---

## 10. Implementation plan and testing

Each phase is shippable on its own and keeps the current page working until phase 7 replaces it.

| Phase | Work | Files / modules | Risks | Accepted when |
|---|---|---|---|---|
| **1. Decisions** | Answer § 11. Freeze the metric definition and illustrative prices. | This doc | Pricing unknowns | Q1–Q6 answered |
| **2. Rules** | Turn § 3–5 into a rules table in code docs and fixtures. | `docs/BILLING.md`, `billing-service/tests/fixtures` | Ambiguity in class counting | The rules table is reviewed |
| **3. Data model** | Billing models and migrations (§ 6). Seed public `PlanVersion`s. Data migration from identity `Tenant.plan`/`plan_terms`, read through the internal route, to `TenantSubscription` plus a private `PlanVersion` for Custom. Open the current period. | `billing-service/src/models/{plan,subscription,usage,plan_invoice}.py`, `migrations/0004_*`, `management/commands/import_plans.py` | Cross-DB migration (identity → billing) must run once and be repeatable | Every tenant has exactly one live subscription. Custom terms match. Tests pass on Postgres. |
| **4. Usage tracking** | Emit usage from `bookings.set_status` (`checked_in`/`completed`), `bookings.join`, session cancel (reversal), `parties.sell`. `POST /internal/usage` and `services/usage.py`. Backfill the current period from operations history. | `operations-service/src/services/{bookings,parties}.py`, new `services/usage.py` (thin, uses `money._enqueue`-style outbox), `billing-service/src/{controllers/internal.py,services/usage.py}` | Double counting during the backfill (handled by idempotency keys like `backfill-<booking>`) | Replays and concurrent events count once. Counter = reconciliation. |
| **5. Entitlements / enforcement** | `GET /internal/tenants/{id}/entitlements`. Identity adds the `billing` claim. Operations applies § 5.1: no new customers when `limited`, no new bookings or plan sales when `restricted`, read-only when `canceled`. Threshold notices. | `identity-service/src/services/tenants.py` (token), `common/auth.py` (claim accessor), `operations-service/src/services/{bookings,customers,parties}.py` | A billing outage must not block (fail open) | Each state blocks only its listed writes. Check-ins, completions and exports always work. |
| **6. Subscriptions and payments** | Plan change, cancel and spend-cap endpoints (`billing.manage`). `close_periods` and the daily delinquency job in one container. `PlanInvoice` generation. **Manual** path: `manage.py mark_paid TNT-000123 --ref …`. **Stripe** path: Checkout/SetupIntent for the card, invoice charge on issue, signed webhook into `ProviderEvent`. Both call `mark_paid`. | `billing-service/src/{controllers/tenant.py,services/subscriptions.py,services/periods.py,management/commands/close_periods.py}`, `compose.yml` | Proration rounding. Period boundaries. | The close job is idempotent (rerun = no-op). Invoices reconcile to records. |
| **7. Dashboard and notices** | Rebuild the billing route (§ 9). New queries and types. Spanish and English strings. Retire `plans.usage` and the identity plan route. | `frontend/src/routes/t.$org.billing.tsx`, `src/lib/{tenancy,queries,types}.ts`, `src/locales/billing.ts`, identity `services/plan.py`, `set_plan` | Old clients during deploy | Owners can see, explain and change everything in § 9 |
| **8. Release** | Run the new metering in **shadow** for one full period next to the old page, compare, publish the notice to tenants, switch. Drop `Tenant.plan`/`plan_terms` a release later. Update ARCHITECTURE.md. | docs, identity migration `0015_*` | Tenants whose bill changes | Shadow differences explained. No tenant billed more than under the old rules in the first period ([REC] grandfather guarantee). |

### Tests (pytest; SQLite for unit tests, **Postgres for concurrency**, as the repo already supports `DATABASE_URL`)

**Unit**
- Overage maths: under, at and over the allowance; cap reached; grants; zero-usage period.
- Proration: an upgrade on day 1, 15 and the last day; Decimal rounding to cents with totals that add up.
- Threshold crossing: `crossed(old, new)` for jumps over several thresholds at once.
- `PlanVersion` is immutable once active.

**Integration**
- Booking completed → outbox → `/internal/usage` → counter = 1. The same customer's second booking → still 1.
- No-show and cancelled bookings don't count. A $0 booking counts (P3 fixed).
- Customer refund → usage unchanged. Session called off → attendee reversed unless they had another event.
- Outbox delivered twice, and billing down then retried → counted once.
- Late event after close → stored `late`, invoice unchanged.
- Upgrade mid-period, downgrade scheduled then applied at renewal, downgrade withdrawn.
- Cancel at period end → read-only afterwards. Undo before the end.
- Payment failure → `past_due` → `limited` on day 14 (new customer refused) → `restricted` on day 30 (new booking refused, check-in allowed) → paid → `active`. A dispute pauses the clock. The extension is usable once per 12 months.
- Stripe and manual paths both end in `mark_paid`. A manual mark-paid racing a Stripe webhook → one payment, one state change.
- `close_periods` run twice → one invoice. A crash halfway → rerun completes.
- Webhook duplicate → ignored. Out of order (`paid` before `failed`) → final state `paid`.

**Concurrency (Postgres, threads with separate connections)**
- 20 parallel first bookings for the same customer → counter 1, one `ActiveSubject`.
- 20 parallel bookings for 20 customers crossing 80% → exactly one notice.
- A plan change racing with period close → serialised, consistent proration.
- The same `Idempotency-Key` plan change sent in parallel → one `SubscriptionChange`.

**Tenant isolation**
- Tenant A's token with tenant B's ids on every billing route → 404 or empty.
- `/internal/usage` from outside the proxy → 404. Without the internal token → 401.
- A role without `billing.manage` can't change plan, cap or alerts (403). `billing.view` can read.

**Reconciliation**
- A property test with random event streams (adds, reversals, duplicates, out-of-order delivery)
  → `UsageCounter` = distinct subjects with net positive sources = the value recomputed from
  `UsageRecord`.
- An injected mismatch → the invoice is held in draft and staff are alerted.

---

## 11. Decisions and open questions

Decided (2026-10-12):

1. **Billable metric: active customers per period.** Class joins count at join, with a reversal
   if the session is called off.
2. **Past the spend cap:** the tenant keeps working and Tenantly absorbs the excess for that
   period. Owner and staff are notified.
3. **Payments: both manual and Stripe.** A `payment_method` on `TenantSubscription` (`manual` /
   `stripe`). Manual invoices are issued with 14-day terms and marked paid by staff through the
   CLI or internal route, with a reference. Stripe charges the card on issue, and its webhooks
   go through `ProviderEvent` (§ 7.5). Both paths end in the same `mark_paid(invoice, source,
   ref)`.

4. **Prices:** catalog v2 in § 4, with the reasoning. Existing businesses keep v1.
5. **Delinquency:** § 5.1 as written (14 / 30 / 45 days, 90 days read-only, dispute pause,
   one 7-day extension a year, no escalation under $5).
6. **Billing period:** calendar month in UTC. A new business's first period starts when it
   signs up, prorated. There's no trial for now.

Still open: unit-cost and market figures to revisit prices after three invoiced periods; email
delivery for notices.

---

## 12. Implementation map and differences from the design

| Concern | Where |
|---|---|
| Catalog (versioned, immutable prices; v1 legacy + v2 public) | `billing-service/src/models/plan.py`, `migrations/0005_seed_plan_versions.py`, `services/catalog.py` |
| Subscriptions, changes, grants | `models/subscription.py`, `services/subscriptions.py` |
| Periods, renewal, grace, reconciliation | `models/usage.py`, `services/periods.py` |
| Usage ledger and distinct counting | `services/usage.py` (`POST /internal/usage`) |
| Pricing (estimate = invoice) | `services/pricing.py` |
| Tenantly invoices, `mark_paid`, history | `models/statement.py`, `services/statements.py` |
| Payment standing (derived) | `services/standing.py` |
| Stripe (Checkout setup, off-session charges, webhooks) | `services/stripe.py`, `controllers/webhooks.py` (`/api/billing/webhooks/stripe`) |
| Daily cycle | `services/cycle.py`, `manage.py billing_cycle` (the `billing-cycle` container) |
| Staff tools | billing `manage.py mark_paid TNT-000123 --ref …`, `manage.py grant <tenant-id> <kind> …`; identity `manage.py set_plan <slug> <plan> [--price --customers --overage]` |
| Admin console (Tenantly staff) | identity `models/admin.py` (`PlatformAdmin`, `AdminAuditEvent`), `services/admins.py` (windows, tokens, log), `controllers/admin.py`, `services/admin.py`; billing `services/console.py`, `services/grants.py` (shared with `manage.py grant`), `services/repricing.py`, `services/policy.py`; frontend `routes/admin.tsx`, `lib/admin.ts`, `server/host.ts` |
| Billing policy (versioned) | `models/policy.py` (`BillingPolicy`), `services/policy.py`, seeded by `migrations/0006_billing_policy.py` |
| Usage events from operations | `operations-service/src/services/usage.py`, called from `bookings.py` and `parties.py` |
| Enforcement | `common/auth.py` (`TenantClaims.allow`, read-only when canceled), billing claim issued by identity `services/tenants.py` |
| Tests | `billing-service/tests/test_plans.py` (the concurrency test runs on Postgres), `operations-service/tests/test_usage.py`, `identity-service/tests/test_platform.py` |

Where the code differs from §§ 5–7:

- **The stored subscription status is only `active` or `canceled`.** `past_due`, `limited` and
  `restricted` are derived on read from the oldest unpaid invoice (as "overdue" already is for
  customer charges), so they can't go stale. That's also why the stage in § 5.1 between past due
  and restricted is called `limited`.
- **Usage travels on the existing `MoneyEvent` outbox** (`path = /internal/usage`) instead of a
  new table. It inherits the outbox's per-tenant ordering: a failing event holds back that
  tenant's later events until it goes through.
- **There's no Postgres exclusion constraint on periods.** One open period per tenant
  (partial unique index), a unique start, and the subscription row lock keep periods from
  overlapping.
- **Notices are in-app only** (billing page and shell banner). Email waits for a delivery service.
- **Not built yet:** free trials; automatic data deletion when retention ends (the date is
  recorded and owners are warned, and deletion is a staff task); moving tenants on *older*
  legacy versions (v1) to the current price list (repricing moves only the edited version's
  subscribers); Stripe refunds (recorded as `skipped` webhooks and handled by
  staff with a credit).
- **Demo data:** a business's first period starts when it's created, so `seed_history`'s
  back-dated bookings aren't usage. The meter fills as bookings are served from then on.

### Tenantly admin console

Tenantly staff use a console on its own host (`http://admin.localhost:8080`, `ADMIN_HOST`), with
admin accounts that are not tenant accounts. See [ARCHITECTURE.md](./ARCHITECTURE.md#tenantly-admin-console)
for the host split and tokens.

- **Admin accounts** (`PlatformAdmin`: email, name, password hash, `dormant | active | blocked`,
  `active_until`, `activated_at`, `activated_by`, `last_login_at`) are never deleted. Access is a
  window of `ADMIN_WINDOW_MINUTES` (default 10), opened only from the server:

  ```bash
  podman compose exec identity python manage.py create_admin you@tenantly.dev --name "You"
  #   prints the generated password once (or --password, 12+ characters); opens a 10-minute window
  podman compose exec identity python manage.py activate_admin you@tenantly.dev   # a new window and a new password
  podman compose exec identity python manage.py block_admin you@tenantly.dev      # end it now
  podman compose exec identity python manage.py expire_admins                     # the sweep
  ```

  Sign-in and every admin request check the window; past it, the request gets a 401, the admin is
  flipped to `blocked` and the log says `expired`. Admin tokens last what's left of the window.
  The console counts it down and signs out at zero.
- **Admin log** (`AdminAuditEvent`, append-only): `created`, `activated`, `login`,
  `login_denied` (wrong password, unknown email, window closed), `expired`, `blocked`, and
  `action` for every change, with target, before and after, IP and time. Read-only in the
  console (`GET /admin/audit`).
- **Owners** (people holding an active `owner` membership; employees and invites are never
  listed): search, then `PUT /admin/owners/{id}/status` with a reason:
  - `restricted`: signs in and reads; their tenant tokens carry `access: restricted` and every
    service refuses writes (`common.auth.TenantAuth`). Reaches them within a token's 5 minutes.
  - `suspended`: no sign-in, sessions deleted. `active` undoes either.
  Their businesses keep running for their teams. Written to each owned business's trail
  (`security`) and to the admin log.
- **Subscriptions** (per business): the panel reads `GET /internal/tenants/{id}/subscription`;
  plan changes, grants and manual payments are forwarded to billing with the admin as `actor`
  (history and the business's trail read "Name (Tenantly)"), after identity checks the window
  again. Billing answers with the state before (`before`), which the admin log keeps.
- **Plans & usage** (`GET /admin/plans`): every public version (on sale and legacy) with its
  subscribers, those scheduled onto it, active customers this period and how many businesses are
  past their allowance. **Changing a price** (`POST /admin/plans/{version}/reprice`: price,
  included customers, overage price, cap, reason) never edits the version: billing publishes the
  next version of that plan, marks the old one `legacy` (no longer offered), and for every active
  subscription on it (or scheduled onto it) sets `scheduled_plan_version` to the new one
  (`reprice_scheduled` in its history), unless it's canceling or already moving to another tier,
  and sends a `plan_repriced` notice with the old and new price and the renewal date. At renewal
  the move is recorded as `reprice_applied`. Issued invoices never change.
- **Billing policy** (`GET` / `PUT /admin/policy`): the whole policy with a reason; billing
  validates it (1 ≤ limited < restricted < canceled ≤ 365 days, terms 0–90, extension 0–30 days
  every 1–730, retention 1–3650 days, grace 0–336 h, spend-cap multiple 1–10, alerts 1–100 %),
  refuses a no-op, and saves version n+1, in force at once for standing, notices, invoice terms,
  retention and the period grace. New subscriptions take its alert thresholds.
- **No request cycles:** billing never creates a subscription (nor asks identity anything but
  the audit entry) in a route identity calls. Summaries leave out, and the detail 404s, a
  business without a subscription. Assigning a plan to one starts its subscription on that
  plan from now, without importing identity's old `Tenant.plan`.

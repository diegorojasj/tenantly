# Tenantly — Product Plan

> **One line:** a multi-tenant platform that runs any business that sells **time, capacity or
> access** — gyms, rentals, salons, studios, field crews — from one deployment, each tenant
> configured by a *business template* instead of custom code.

---

## 1. The generic model

Every service business, whatever its niche, is the same five things:

| Primitive | Question it answers | e.g. a gym | e.g. a rental shop | e.g. a field crew |
|---|---|---|---|---|
| **Offering** | *What do we sell?* | Classes, PT sessions, memberships | Kayak/bike hire, guided tours | Maintenance visits, service plans |
| **Resource** | *What delivers it?* | Coaches, studios, racks | Boats, bikes, guides | Technicians, vans |
| **Customer** | *Who buys it?* | Members (and their families) | Renters (and their groups) | Accounts: companies with contacts, households, and the properties served |
| **Booking** | *Who gets which resource, when?* | Class spot, PT slot | Rental window + unit | Visit on a route |
| **Payment** | *How is it paid?* | Membership dues, drop-ins | Deposit + hire fee | Invoice, monthly plan |

### Offering presets (how an offering is fulfilled)

Each offering carries its own fulfilment rules (capacity, time, place, the resources it
takes, and optionally the *subject* it serves: a pet, a vehicle). A template offers
**presets** as starting points; the original five kinds are presets, and their rules can be
changed per offering (a three-seat appointment is a small-group session).

| Preset | Capacity rule | Time rule | Example |
|---|---|---|---|
| **Appointment** | 1 customer ↔ 1 staff | fixed duration | PT session, haircut |
| **Class** | N customers ↔ 1 staff (+ room) | fixed slot, recurring | Spin class, guided tour |
| **Rental** | 1 customer ↔ 1+ asset units | flexible window (hours/days) | Kayak, court, cabin |
| **Visit** | 1 account ↔ 1 staff, at the customer's address | duration + travel | Aquarium service, cleaning |
| **Plan** | recurring entitlement, not a time slot | billing cycle | Membership, 10-class pack, service contract |

### Booking lifecycle (generic, labels can be renamed by template)

`Requested → Confirmed → Checked in → Completed`, with side exits `No-show` and `Cancelled`.
Rentals add `Out` / `Returned` as their checked-in / completed labels; visits use
`En route` / `On site`. **Same states, different words**, so reporting stays comparable.

### One template for every business

There is no "what kind of business are you?" step. Every business starts from the same
**general** template (identity migration 0010), so a gym, a bike-hire shop and a cleaning
crew all get the same product with every preset available. A template is still data, not
code, and sets:

- **Vocabulary**: plain nouns — Customer, Booking, Team member, Location.
- **All five presets** (appointment, class or group, rental, visit, plan or membership)
  and two resource types (Team; Rooms & items).
- **Account types** (Company, Household) and a **Waiver** document, off by default
  (`docs.require.waiver` = Not needed) until the business turns it on in Policies.
- **Status labels** for the lifecycle above and **default policies**.

**Simple by default, grows with use.** Offering everything must not mean showing everything:

- Catalog groups, booking tabs ("Book a slot" vs "Join / Schedule a class"), plan columns
  and document sections appear only once the business sells or uses that kind of thing.
- "Add offering" asks one plain question (*What are you selling?*) with a one-line example
  per choice; category, place, capacity for one-to-one offerings and extra resources sit
  under **More options**.

Businesses created from the retired vertical templates (fitness, rentals & tours, field
service) keep theirs; unused ones were removed. The platform operator can still add
templates through the API (`templateId`), but the product never asks users to pick one.

---|---|---|
| **Ironworks Gym** | Fitness | Class, Appointment, Plan |
| **Tideline Rentals** | Rentals & tours | Rental, Class |
| **ClearTank Aquatics** | Field service | Visit, Plan |

---

## 2. Sections (each one has one job)

Navigation is split by **intent**: *Operate* (every day), *Set up* (when the business
changes), *Admin* (the multi-tenant platform itself). Nothing appears without a primary action.

### Operate

| Section | Purpose (the one job) | Primary actions | Who lives here |
|---|---|---|---|
| **Today** | Run the day at the front desk: who's arriving, what's happening now, what needs attention. | Check in · quick book · resolve alert | Front desk, site lead |
| **Calendar** | Plan and change time-based capacity across resources. | Book · move · block time | Front desk, managers |
| **Bookings** | Handle every reservation through its lifecycle, including the ones that aren't "today". | Confirm request · cancel / refund · mark no-show | Front desk |
| **Customers** | Know who you serve before you serve them. | Add customer · sell plan · view history | Everyone |

- **Today**: arrivals timeline (next 2h), live "in progress", alerts (unpaid, missing documents,
  overbooked class, rental overdue), KPIs for the day only.
- **Calendar**: rows = resources (staff *and* assets), columns = time. Classes show fill
  (`12/16`), rentals show the window per unit, visits show the route order.
- **Bookings**: a filterable list (status, offering, resource, date range) with bulk actions.
  Replaces the old "pipeline": a gym doesn't drag members across a kanban.
- **Customers**: profile with typed template fields, their account (company or household)
  and its other contacts, the subjects served for them, every active **plan and its
  credits**, documents on file with their expiry, balance and booking history.

### Set up

| Section | Purpose | Primary actions |
|---|---|---|
| **Catalog** | Define what you sell and how it's fulfilled. | Add offering · set price, duration, capacity, required resources |
| **Resources** | Define what delivers it, and see how busy it is. | Add staff/asset · set hours · see utilization |

- **Catalog**: offerings grouped by preset; each card states its rule ("16 spots · 45 min ·
  needs Studio A + 1 coach"). Plans live here too (price, cycle, what they include).
- **Resources**: two tabs, *Staff* (skills, working hours) and *Assets* (units, condition,
  out-of-service), each with a 7-day utilization bar.

### Money & insight

| Section | Purpose | Primary actions |
|---|---|---|
| **Payments** | Know what's owed and what's been paid. | Collect · refund · chase overdue |
| **Insights** | See whether the business is getting better: revenue, utilization, retention. | Change period · compare locations |

Today is about *now*, Insights about *trends*. They don't overlap.

### Admin (the multi-tenant platform)

| Section | Purpose |
|---|---|
| **Locations** | The org → region → location tree that scopes everything else. |
| **Team & roles** | Who can do what, where (RBAC + scope assignment, SSO/MFA posture). |
| **Policies** | Per-tenant rules with inheritance down the tree (deposits, cancellation, booking window, reminders). |
| **Audit trail** | Tamper-evident record of every change. |
| **Plan & usage** | The tenant's own Tenantly subscription and metered usage. |

---

## 3. Cross-cutting (already built, kept)

- **Tenant tint**: the whole UI takes the tenant's hue; the stage is framed with the tenant name.
- **Scope lens**: `?scope=` narrows every section to org / region / location; RBAC limits how
  wide you can go (enforced by the server functions, not just the UI).
- **Command bar** (⌘K): jump to pages, scopes and workspaces.
- **Template-aware copy**: no hardcoded "client" or "appointment" anywhere in the UI.

## 4. Frontend scope of this iteration

- The **template + fulfilment-rules** model above, persisted by the identity, operations and
  billing services (see ARCHITECTURE.md). Data starts empty; the tenants named in §1 are
  examples, not seed data. Next steps for the model: [PLATFORM.md](./PLATFORM.md).
- Build: Today, Calendar, Bookings, Customers, Catalog, Resources, Payments, Insights.
- Re-label Admin; keep Locations / Team / Policies / Audit / Plan & usage.
- Out of scope: real payments, customer-facing booking page, notifications delivery.

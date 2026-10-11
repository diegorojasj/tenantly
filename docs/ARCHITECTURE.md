# Tenantly — Architecture

> What runs where, how a request travels, and who owns which data.
> Product: [PRODUCT.md](./PRODUCT.md) · Usage: [USAGE.md](./USAGE.md)

```
 browser ──► proxy :8080 (nginx) ──►  /                → frontend   (SolidStart SSR, Node)
                                 ├──► /api/identity/   → identity   (Django) ─┐
                                 ├──► /api/operations/ → operations (Django) ─┼─► postgres (one DB each)
                                 └──► /api/billing/    → billing    (Django) ─┘
                                      /api/*/internal/ → 404 (never exposed)
```

The browser only ever talks to the frontend. The frontend's server functions
call the services **through the proxy** (`API_URL`, default
`http://localhost:8080/api`); services call each other directly on the
internal network for `/internal/*` routes.

## Services

| Service | Owns | Notes |
|---|---|---|
| **identity** | accounts, sessions, businesses (tenants) and their money, branding and SSO settings, the location tree, team & each business's roles, audit trail, the template registry | Issues tenant tokens. Business templates are stored rows (`Template` model, seeded by data migrations); permissions are code (`identity-service/src/types/roles.py`), roles are `Role` rows per business. |
| **operations** | catalog, resources, customers and their accounts, subjects, subscriptions and documents, bookings, class attendance, policies | Today, Calendar and Insights are read models here. Raises money through billing, writes audit through identity. |
| **billing** | charges (due / paid / refunded), customer invoices, revenue, the Tenantly plan's prices and usage | "Overdue" is derived on read from the age of a due charge. Reads the plan name (and a Custom plan's terms) from identity. |

Each service is its own Django project with its own database, using the same
layout: `config/` (settings, urls, wsgi) and `src/{models,schemas,services,controllers}`.
Only `services/` touches models; controllers are thin. Shared code lives in
`services/common` (settings, error shape, camelCase schemas, tenant-token auth,
internal calls).

## Authentication and tenant isolation

1. **Sign in** — identity checks the password and returns an opaque session
   token (only its SHA-256 is stored). The frontend keeps it in a signed,
   HTTP-only cookie.
2. **Enter a workspace** — the frontend trades the session token for a
   **tenant token** (`POST /tenants/{slug}/token`): a 5-minute HS256 JWT
   carrying the tenant id, the role's permissions, the member's home scope,
   the location tree, the rules of the business's template (see below) and its
   money settings (`money`: currency, tax rate and name, whether prices include tax).
   Identity refuses non-members.
   - **Invites** carry a one-time code (only its hash is stored). Joining
     needs the code *and* the invited email, since emails aren't verified.
     There's no email delivery yet, so the inviter copies the link
     (`/?invite=<code>`) and passes it on. Nobody can grant a role with
     permissions their own role lacks.
   - **Roles** belong to the business: copied from its template's `roles` when it is
     created, then added to, edited and removed on Team & roles (`roles.assign`). The same
     rule holds there: nobody creates, edits or removes a role that can do more than their
     own, or edits the role they hold. `owner` is fixed and always carries every
     permission. A role change reaches its holders with their next token (≤ 5 minutes).
3. **Every tenant request** carries that token. Each service verifies it
   locally (`JWT_SECRET`), takes the tenant id **only from the token**, checks
   the permission, and clamps the requested scope to the member's subtree.
4. **Service-to-service** calls use `X-Internal-Token` (`INTERNAL_TOKEN`). The
   proxy blanks that header on the way in and 404s every `/internal/` path.

Every row in operations and billing carries `tenant_id`; every query filters
by it. That's the row-level boundary: one database per service, tenants
separated by key, no cross-tenant reads possible through the API.

## Templates

A business template (every new business gets `general`; see PRODUCT.md §1) is data owned by identity: a
`Template` row with a string id, a `version`, vocabulary (`terms`, an open
key → label map), booking status labels, the booking lifecycle
(`transitions`: status → statuses it may move to), **resource types**
(`resourceTypes`: what delivers the work, with typed attributes), fulfilment
**presets** (`presets`: the starting rules for offerings — the old five kinds),
typed custom **fields** per entity, **account and subject types** (who customers belong
to, what is served for them), **document types**, the location tree's named **levels**,
the **default roles**, opening hours and `policyDefaults`. A tenant references its template
by id (`Tenant.template_id`).

- **Location tree** — `Node.kind` is `org` (the business), `region` (a group) or
  `location`. A group's `level` is one of `Template.levels` (top to bottom); a child group
  sits on a deeper level than its parent, locations hang under the business or any group.
  Services only ever walk parents, so scope clamping, policy inheritance and the token's
  node rows work at any depth; only the frontend reads the level names.

- **Fulfilment** — an offering stores its own rules (`capacity`, `time`, `place`,
  `requires`), copied from its preset and overridable; operations never branches on
  the preset's name (`services/fulfilment.py`). A booking takes every requirement at
  once: the desk's picks are checked, the rest are the first free matches by type,
  category and attributes, and all candidates (plus whatever they nest with) are locked
  before the clash check.

- **Parties** — a `Customer` may belong to an `Account` (company or household, typed by
  `accountTypes`); a `Subject` (pet, vehicle, property, typed by `subjectTypes`) belongs to a
  customer or an account; plans are `Subscription` rows, several per customer
  (`services/parties.py`). An offering's `subject_type` makes each booking name a subject.
- **Fields and documents** — every entity's custom values are a JSON map validated against
  the template's typed definitions (`services/fields.py`: type, required, options, `pii`
  hidden from roles without `bookings.manage`, `expires` dates). Documents are rows with an
  issue and expiry date; the `docs.require.<key>` policy (one per document type, generated
  from the template) decides whether a missing one is ignored, flagged, or refuses the
  booking (`services/documents.py`).

- **Frontend** gets the full template inside the tenant object
  (`GET /templates`, workspaces, `POST /tenants/{slug}/token` context) and
  offers only the moves listed in `template.transitions`.
- **Locations** carry their clock in the token too: each node row is
  `[id, parent, kind, name]`, plus `tz, [open, close]` when a location sets its own
  zone or hours (older four-item rows still decode, as UTC with the template's hours).
  Operations stores booking times as aware UTC and reads and writes them on the
  location's wall clock (`services/clock.py`); a booking's `start`/`end` on the wire are
  local `YYYY-MM-DDTHH:MM` with its `tz` alongside.
- **Other services** never hold a copy of the registry: identity puts
  `Template.rules()` (everything but id, description, hue and default roles, ~2 kB) into the
  tenant token's `rules` claim, read back as `TenantClaims.template`. Operations
  enforces the lifecycle (`claims.moves(status)`), hours, presets, resource
  types, custom fields, account / subject / document types and wording from it, and a policy's starting value is the template's
  `policyDefaults` entry, else the platform default. Since tokens live five
  minutes, a template edit reaches every service within five minutes.

## Money

- **Decimals end to end** — amounts are `Decimal` (two places) in every service and
  decimal strings on the wire (`"12.50"`, `common/money.py`); nothing is rounded through a
  float. The frontend adds and multiplies them on integer cents and formats them with the
  business's currency (`src/lib/format.ts`).
- **Currency and tax** — set per business in identity and carried in the token. Operations
  stamps the currency on every charge it raises; billing keeps it per charge, and an invoice
  snapshots currency, tax rate, tax name and inclusive/exclusive when issued.
- **Invoices** — billing gathers a customer's open charges (reachable locations, current
  currency) under the next number for the tenant. Tax is the share inside the total when
  prices include tax, else added on top. Paying collects every charge on it; voiding
  releases them; a charge dropped by a cancellation re-totals (or voids) its open invoice;
  an invoiced charge can only be collected through its invoice.
- **The Tenantly plan** — priced on consumption, never seats: customers charged and
  payments raised this month. Prices and limits are billing's (`services/plans.py`, in USD):
  Starter (50 customers / 500 payments), Growth (×2), Enterprise (×4), and Custom, agreed
  per business. A month past its tier's limits is billed on the smallest tier that fits
  (never below the chosen one) and starts over on the 1st; past Enterprise the page asks
  for a Custom plan. `GET /plan` asks identity (`/internal/tenants/{id}/plan`) for the
  chosen plan and a Custom plan's terms (price, optional limits). Tenantly sets them with
  `PUT` on that route or `manage.py set_plan <slug> Custom --price 250 [--customers N]
  [--payments N]` in identity; the change lands in the audit trail.

## Consistency

- **No double booking** — creating a booking locks the resources it needs
  (`SELECT … FOR UPDATE`, including nested parents and children) before checking
  for clashes.
- **Audit** — operations and billing write the audit entry inside the same
  transaction as the change; if identity can't record it, the change rolls
  back. Entries are hash-chained per tenant and the chain is re-verified on
  every read.
- **Money** — booking lifecycle changes raise or refund charges in billing
  (completed → charge; no-show / late cancel → fee per policy; cancel →
  refund; class drop-in → paid charge; pack plans spend and return credits).
  Charges are filed under the location that did the work.
- **Money outbox** — operations never calls billing mid-transaction. Charges
  and refunds are written as `MoneyEvent` rows in the same transaction as the
  booking change, sent after commit in order (per tenant), and keyed
  `ops-<event id>` so billing raises each charge once however often it's
  retried. Whatever billing doesn't accept stays pending; the
  `operations-outbox` container (`manage.py send_money --loop 30`) retries it.

## Running it

```bash
cp .env.example .env            # then replace every value (openssl rand -base64 32)
podman compose --profile DEV up --build    # or: docker compose …
# open http://localhost:8080 → create an account → create your business
```

`--profile PROD` builds and runs the production frontend instead of the dev
server. Data starts **empty**: no demo tenants, users or bookings.

Services locally (without containers):

```bash
cd services && uv venv --python 3.13 .venv && uv pip install -r pyproject.toml --group dev
cd identity-service && ../.venv/bin/python -m pytest      # SQLite by default
DATABASE_URL=postgres://user:pass@localhost:5432/db ../.venv/bin/python -m pytest   # real Postgres
```

## Known limits

- Amounts always have two decimal places; currencies with other minor units (JPY, KWD)
  aren't supported. Payments totals add charges whatever their currency, so a business that
  changes currency sees old and new amounts summed. One tax rate per business.
- Branding stores a logo URL, a custom domain and SSO settings; the domain isn't routed and
  SSO isn't connected (sign-in is email and password only).

- Time zones are per location (identity's `Node.tz`, default UTC). Pages that span
  locations in several zones (Today, Bookings, Insights across the business) pick "today"
  in UTC and file each booking under its own location's local day. Opening hours are one
  daily window per location (no weekday or holiday hours); there are no per-resource
  working hours yet. The audit ledger groups entries by UTC day.
- No real payment processor, email or SMS delivery, and no third-party integrations (not planned yet).
- Same-route search navigations that swap a query key stall the current
  TanStack Router 2.0 RC's transition; affected view state (date, range,
  period, tab, open profile) is kept in local state, seeded from the URL.

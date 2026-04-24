# Website Deployment Requirements

**Purpose**: Roadmap for transforming the stock screener from a local-only
Python app into a publicly accessible, multi-user subscription website.

**Current state**: Two-process local app (Dash 8050 + FastAPI 8000), SQLite,
no user accounts, single `user_id="default"` for all trades. Security
hardening done for admin endpoints (API key gate, rate limiting, input
validation) — see `docs/99_security/`.

---

## Table of Contents

1. [Why the current version cannot be deployed as-is](#1-why-the-current-version-cannot-be-deployed-as-is)
2. [Infrastructure requirements](#2-infrastructure-requirements)
3. [User authentication and account system](#3-user-authentication-and-account-system)
4. [Subscription and payment](#4-subscription-and-payment)
5. [Admin account setup and management](#5-admin-account-setup-and-management)
6. [Access control — free, paid, and complimentary](#6-access-control--free-paid-and-complimentary)
7. [Database migration (SQLite to PostgreSQL)](#7-database-migration-sqlite-to-postgresql)
8. [Frontend changes for multi-user](#8-frontend-changes-for-multi-user)
9. [Dev mode vs production mode](#9-dev-mode-vs-production-mode)
10. [Deployment checklist](#10-deployment-checklist)
11. [Estimated work breakdown](#11-estimated-work-breakdown)

---

## 1. Why the current version cannot be deployed as-is

| Gap | Impact | Difficulty |
|-----|--------|------------|
| No user accounts / authentication | Anyone can see and modify all data | Large |
| Single `user_id="default"` for trades | All users share one trade book | Large |
| SQLite — single-writer, no concurrency | Locks under concurrent users | Medium |
| Dash serves static assets directly | Not designed for high traffic | Medium |
| No HTTPS | Credentials sent in plaintext | Small (infra) |
| No password hashing / session management | Cannot identify users | Large |
| No subscription/payment integration | Cannot monetize | Large |
| No email verification or password reset | Poor user experience | Medium |
| No multi-tenancy isolation | Users could see each other's data | Large |

**Bottom line**: The app needs a full user-auth system, a real database,
HTTPS, and subscription logic before it can accept public sign-ups.

---

## Related documents

- **`ohlcv-server-mode.md`** — Separate plan for centralising OHLCV data
  storage and the intraday monitor on a dedicated server. This is an
  independent infrastructure concern that can be deployed before or after
  the user-auth system described here.

---

## 2. Infrastructure requirements

### Minimum production stack

```
                    Internet
                       │
               ┌───────▼────────┐
               │  Reverse Proxy  │   Caddy / nginx / Cloudflare Tunnel
               │  (HTTPS + TLS) │
               └──┬──────────┬──┘
                  │          │
          ┌───────▼───┐  ┌──▼──────────┐
          │  Dash UI   │  │  FastAPI    │
          │  (Gunicorn │  │  (Uvicorn   │
          │   workers) │  │   workers)  │
          └───────┬───┘  └──┬──────────┘
                  │         │
              ┌───▼─────────▼───┐
              │   PostgreSQL     │   (or managed: Supabase, RDS, etc.)
              └──────┬──────────┘
                     │
              ┌──────▼──────────┐
              │  Redis (optional)│   sessions, rate-limit counters, cache
              └─────────────────┘
```

### Hosting options (budget-friendly)

| Option | Cost estimate | Notes |
|--------|---------------|-------|
| Single VPS (DigitalOcean, Hetzner, Linode) | $6-24/mo | Simplest; run everything on one box |
| Railway / Render | $7-25/mo | PaaS; managed Postgres add-on |
| AWS Lightsail / EC2 t3.micro + RDS | $15-40/mo | Scalable; free tier eligible |
| Fly.io | $0-10/mo (small scale) | Edge deployment; built-in Postgres |

### DNS and TLS

- Register a domain (Cloudflare, Namecheap, etc.)
- Use Caddy (auto-TLS) or Cloudflare Tunnel for HTTPS
- Point `app.yourdomain.com` at the server

---

## 3. User authentication and account system

### What needs to be built

#### 3a. User model

```
users
  id              UUID (PK)
  email           TEXT UNIQUE NOT NULL
  password_hash   TEXT NOT NULL
  display_name    TEXT
  role            ENUM('user', 'admin', 'superadmin')
  tier            ENUM('free', 'basic', 'premium')
  is_active       BOOLEAN DEFAULT true
  email_verified  BOOLEAN DEFAULT false
  created_at      TIMESTAMP
  updated_at      TIMESTAMP
```

#### 3b. Auth endpoints (new router: `src/api/routers/auth.py`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/auth/register` | Create account (email + password) |
| POST | `/auth/login` | Return JWT access + refresh tokens |
| POST | `/auth/refresh` | Refresh expired access token |
| POST | `/auth/logout` | Invalidate refresh token |
| POST | `/auth/forgot-password` | Send password-reset email |
| POST | `/auth/reset-password` | Set new password with reset token |
| GET  | `/auth/verify-email/{token}` | Confirm email address |
| GET  | `/auth/me` | Return current user profile |
| PUT  | `/auth/me` | Update profile (display name, password) |

#### 3c. Libraries to add

| Library | Purpose |
|---------|---------|
| `python-jose[cryptography]` | JWT token creation/validation |
| `passlib[bcrypt]` | Password hashing |
| `python-multipart` | Form data parsing for login |
| `itsdangerous` | Signed tokens for email verification / password reset |

#### 3d. Password policy

- Minimum 8 characters
- Hash with bcrypt (cost factor 12)
- Never store or log plaintext passwords
- Rate-limit login attempts (5/minute per IP)

#### 3e. Session / token strategy

- **Access token**: JWT, 15-minute expiry, contains `user_id`, `role`, `tier`
- **Refresh token**: opaque token stored in DB, 7-day expiry
- Frontend stores tokens in httpOnly cookies (not localStorage)
- On each API call, middleware extracts user from token and injects `current_user`

---

## 4. Subscription and payment

### Tier structure (example)

| Tier | Price | Features |
|------|-------|----------|
| Free | $0 | Screener (read-only), limited to 10 tickers, no trade tracker |
| Basic | $9/mo | Full screener, trade tracker, scanner, 50 tickers |
| Premium | $19/mo | Everything + priority data refresh, unlimited tickers, brokerage import |

### Payment integration (Stripe recommended)

#### New endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/billing/create-checkout` | Create Stripe Checkout session |
| POST | `/billing/webhook` | Receive Stripe webhook events |
| GET  | `/billing/portal` | Redirect to Stripe Customer Portal |
| GET  | `/billing/status` | Return current subscription status |

#### Stripe webhook events to handle

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Activate subscription, set user tier |
| `invoice.paid` | Renew subscription |
| `invoice.payment_failed` | Mark subscription as past-due |
| `customer.subscription.deleted` | Downgrade user to free tier |

#### New tables

```
subscriptions
  id              UUID (PK)
  user_id         UUID FK → users
  stripe_customer_id    TEXT
  stripe_subscription_id TEXT
  tier            ENUM('free', 'basic', 'premium')
  status          ENUM('active', 'past_due', 'canceled', 'trialing')
  current_period_start  TIMESTAMP
  current_period_end    TIMESTAMP
  created_at      TIMESTAMP
```

#### Libraries to add

| Library | Purpose |
|---------|---------|
| `stripe` | Stripe Python SDK |

---

## 5. Admin account setup and management

### Initial superadmin creation

On first deployment, create the superadmin via a CLI command (not through
the web UI, to prevent unauthorized admin creation):

```bash
# Create superadmin account
python scripts/create_admin.py \
  --email admin@yourdomain.com \
  --password <strong-password> \
  --role superadmin

# Or via environment variable for automated deploys
SUPERADMIN_EMAIL=admin@yourdomain.com
SUPERADMIN_PASSWORD=<strong-password>
# App creates the account on first startup if it doesn't exist
```

### Admin dashboard (new Dash page: `frontend/pages/admin_dashboard.py`)

Features:
- View all registered users (email, tier, status, created date)
- Change a user's tier (free/basic/premium)
- Grant complimentary access (see Section 6)
- Deactivate / reactivate accounts
- View subscription revenue summary
- Trigger data refresh operations (existing admin endpoints)
- View rate-limit and error logs

### Admin roles

| Role | Can do |
|------|--------|
| `user` | Normal user — access based on their tier |
| `admin` | Manage users, grant access, trigger data ops |
| `superadmin` | Everything + manage other admins, billing config |

### Admin API endpoints (extend `src/api/routers/admin.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/users` | List all users (paginated) |
| GET | `/admin/users/{id}` | Get user details |
| PUT | `/admin/users/{id}/tier` | Change user tier |
| PUT | `/admin/users/{id}/role` | Change user role (superadmin only) |
| PUT | `/admin/users/{id}/active` | Activate / deactivate account |
| POST | `/admin/users/{id}/grant-access` | Grant complimentary access |
| DELETE | `/admin/users/{id}` | Delete account and all associated data |

---

## 6. Access control — free, paid, and complimentary

### Tier enforcement middleware

Every API endpoint gets a `require_tier(minimum_tier)` dependency:

```python
# Example usage in router
@router.get("/api/trades/")
async def list_trades(
    user: User = Depends(get_current_user),
    _: None = Depends(require_tier("basic")),
):
    ...
```

### Feature gates

| Feature | Free | Basic | Premium |
|---------|------|-------|---------|
| Screener (view) | 10 tickers | 50 tickers | Unlimited |
| Screener filters | Basic only | All | All |
| Trade tracker | No | Yes | Yes |
| Brokerage import | No | No | Yes |
| Strategy scanner | No | Yes | Yes |
| Technical charts | 3/day | 20/day | Unlimited |
| Data refresh | Manual only | Scheduled | Priority |
| Zombie detection | View only | Full | Full |
| Macro dashboard | Yes | Yes | Yes |
| Metals dashboard | Yes | Yes | Yes |

### Granting complimentary access

Admins can grant free premium access to specific accounts:

```
complimentary_access
  id          UUID (PK)
  user_id     UUID FK → users
  tier        ENUM('basic', 'premium')
  reason      TEXT          -- "beta tester", "friend & family", etc.
  granted_by  UUID FK → users (the admin)
  expires_at  TIMESTAMP NULL  -- NULL = never expires
  created_at  TIMESTAMP
```

The tier-check middleware should evaluate: `max(subscription_tier, complimentary_tier)`.

Admin grants access via:
- Admin dashboard UI: select user → "Grant Access" → choose tier + expiry
- API: `POST /admin/users/{id}/grant-access` with `{tier, reason, expires_at}`

---

## 7. Database migration (SQLite to PostgreSQL)

### Why migrate

- SQLite allows only one writer at a time — concurrent users will hit locks
- No built-in user/role system
- Limited full-text search and JSON capabilities
- Cannot run on a separate server from the app

### Migration steps

1. **Install PostgreSQL** (or use a managed service: Supabase, RDS, Neon)
2. **Update `DATABASE_URL`** in `.env`:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/stock_screener
   ```
3. **Add `psycopg2-binary`** (or `asyncpg`) to requirements
4. **Replace SQLite-specific SQL** (e.g., `PRAGMA` statements in `database.py`)
5. **Use Alembic for schema migrations** instead of the current `_migrate_columns()` hack:
   ```bash
   pip install alembic
   alembic init alembic
   alembic revision --autogenerate -m "initial schema"
   alembic upgrade head
   ```
6. **Data migration script**: Export SQLite data → import into PostgreSQL
7. **Test thoroughly** — SQLAlchemy abstracts most differences, but date
   handling and type casting may differ

### Alembic setup

```
alembic/
  env.py
  versions/
    001_initial_schema.py
    002_add_users_table.py
    003_add_subscriptions.py
    004_add_complimentary_access.py
```

---

## 8. Frontend changes for multi-user

### Login / registration pages

New Dash pages:
- `frontend/pages/login.py` — email + password form
- `frontend/pages/register.py` — registration form
- `frontend/pages/forgot_password.py` — password reset request
- `frontend/pages/reset_password.py` — set new password (from email link)
- `frontend/pages/account.py` — profile, subscription status, billing portal link

### Session management in Dash

- Store JWT in a secure httpOnly cookie
- Add a `get_current_user()` utility that reads the cookie on each page load
- Redirect unauthenticated users to `/login`
- Show/hide navigation items based on user tier

### API client changes (`frontend/api_client.py`)

- Attach JWT token to every API request (via `Authorization: Bearer` header)
- Handle 401 responses by redirecting to login
- Handle 403 responses by showing "upgrade required" message

---

## 9. Dev mode vs production mode

### Running in dev mode (current behavior, preserved)

```bash
# .env (or no .env at all — defaults are fine)
DEV_MODE=true    # default

python scripts/run_server.py
```

- No login required — app works as it does today
- All endpoints open, Swagger UI available
- SQLite, single user, no subscription checks
- Ideal for local development and personal use

### Running in production mode

```bash
# .env
DEV_MODE=false
SECRET_KEY=<64-char-hex>
ADMIN_API_KEY=<64-char-hex>
DATABASE_URL=postgresql://user:pass@db:5432/stock_screener
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@yourdomain.com
SMTP_PASSWORD=<app-password>

# First-time setup
python scripts/create_admin.py --email admin@yourdomain.com --password <pw>
alembic upgrade head

# Run with Gunicorn (Dash) + Uvicorn (FastAPI)
gunicorn frontend.app:server -w 4 -b 0.0.0.0:8050 &
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 4 &
```

### Environment variable reference (production)

| Variable | Required | Purpose |
|----------|----------|---------|
| `DEV_MODE` | No (default `true`) | Toggle dev/prod behavior |
| `SECRET_KEY` | Yes (prod) | JWT signing key |
| `ADMIN_API_KEY` | Yes (prod) | Admin endpoint authentication |
| `DATABASE_URL` | Yes (prod) | PostgreSQL connection string |
| `STRIPE_SECRET_KEY` | Yes (if billing) | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | Yes (if billing) | Stripe webhook signature verification |
| `SMTP_HOST` | Yes (prod) | Email server for verification/reset |
| `SMTP_PORT` | Yes (prod) | Email server port |
| `SMTP_USER` | Yes (prod) | Email sender address |
| `SMTP_PASSWORD` | Yes (prod) | Email sender password |
| `FRED_API_KEY` | Optional | FRED macro data |
| `ALLOWED_ORIGINS` | Recommended | CORS origins (comma-separated) |

---

## 10. Deployment checklist

### Phase 1 — Auth foundation (must-have before going live)

- [ ] Create `users` table with Alembic migration
- [ ] Implement password hashing (bcrypt via passlib)
- [ ] Build `/auth/*` endpoints (register, login, refresh, logout)
- [ ] Add `get_current_user` dependency to all endpoints
- [ ] Scope trade data by `user_id` from JWT (fixes security finding B10)
- [ ] Build login/register Dash pages
- [ ] Update `api_client.py` to send JWT tokens
- [ ] Email verification flow
- [ ] Password reset flow
- [ ] Admin CLI script for creating superadmin

### Phase 2 — Subscription and payment

- [ ] Create `subscriptions` table
- [ ] Integrate Stripe Checkout
- [ ] Handle Stripe webhooks (subscribe, renew, cancel)
- [ ] Implement `require_tier()` middleware
- [ ] Build account/billing Dash page
- [ ] Enforce feature gates per tier
- [ ] Admin dashboard for user management

### Phase 3 — Infrastructure

- [ ] Migrate from SQLite to PostgreSQL
- [ ] Set up Alembic for all schema migrations
- [ ] Configure reverse proxy with HTTPS (Caddy or nginx)
- [ ] Set up SMTP for transactional emails
- [ ] Container packaging (Docker/docker-compose)
- [ ] CI/CD pipeline (GitHub Actions → deploy)
- [ ] Monitoring and alerting (uptime, error rates)
- [ ] Automated database backups

### Phase 4 — Polish

- [ ] Complimentary access system for admin-granted free tiers
- [ ] Usage analytics (which features are used, by tier)
- [ ] Onboarding flow for new users
- [ ] Terms of service and privacy policy pages
- [ ] Cookie consent banner (if required by jurisdiction)
- [ ] Rate limiting tuned per tier

---

## 11. Estimated work breakdown

| Phase | Scope | Complexity |
|-------|-------|------------|
| Phase 1 — Auth | User model, JWT, login/register, email flows, user scoping | Large |
| Phase 2 — Billing | Stripe integration, tier enforcement, admin dashboard | Large |
| Phase 3 — Infra | PostgreSQL, HTTPS, Docker, CI/CD, monitoring | Medium |
| Phase 4 — Polish | Complimentary access, analytics, legal pages | Small-Medium |

### Recommended implementation order

1. **PostgreSQL migration first** — this unblocks concurrent users and is needed by auth
2. **Auth system** — user model, JWT, login/register pages
3. **Trade scoping** — fix the `user_id="default"` issue with real user IDs
4. **Stripe integration** — only after auth is working
5. **Admin dashboard** — manage users, grant access
6. **Infrastructure** — Docker, HTTPS, CI/CD
7. **Polish** — complimentary access, analytics, legal

---

## Appendix A: Unresolved security items from the audit

These items from `docs/99_security/2026-04-21_security-audit.md` are
**intentionally deferred** because they require the full deployment stack
described above. They cannot be resolved in the current local-Python setup:

| Audit Item | Why it's deferred | Resolved by |
|------------|-------------------|-------------|
| B10 — Trade data not user-scoped | Requires user auth system | Phase 1 |
| HTTPS termination | Infrastructure concern | Phase 3 |
| Git history rewrite (BFG) | Destructive; needs coordination | Pre-launch one-time task |
| Container/process isolation | Deployment-time concern | Phase 3 |
| Structured logging with PII filtering | Needs user data to filter | Phase 4 |
| Dependency vulnerability scanning | CI/CD pipeline concern | Phase 3 |

**None of these can be fixed by changing Python code alone** — they all
require infrastructure, a user system, or a one-time git operation.

---

## Appendix B: Quick reference — admin account management

### Create admin (CLI)

```bash
python scripts/create_admin.py --email admin@example.com --password <pw> --role superadmin
```

### Grant complimentary access (API)

```bash
curl -X POST http://localhost:8000/admin/users/<user-id>/grant-access \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"tier": "premium", "reason": "beta tester", "expires_at": null}'
```

### Change user tier (API)

```bash
curl -X PUT http://localhost:8000/admin/users/<user-id>/tier \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"tier": "basic"}'
```

### Deactivate user (API)

```bash
curl -X PUT http://localhost:8000/admin/users/<user-id>/active \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

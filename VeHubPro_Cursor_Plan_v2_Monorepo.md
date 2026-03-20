# VeHubPro — Cursor AI Master Development Plan

> **Product**: VeHubPro — Multi-Tenant SaaS Vehicle Service & Marketplace Platform  
> **Stack**: Turborepo Monorepo · React.js (Web) · React Native (Mobile — future) · Django REST Framework (Backend) · PostgreSQL · AWS S3  
> **Monorepo Tool**: Turborepo + pnpm workspaces  
> **Compliance**: DPDP Act 2023 · GDPR · ISO 27001 · GST India  
> **Document Version**: v1.0.0

---

## ⚙️ CURSOR RULES FILE (`.cursorrules`)

> **Create this file at the root of your project before writing any code.**  
> Cursor will read this on every prompt and apply these rules globally.

```
You are building VeHubPro — a multi-tenant SaaS platform for vehicle service centers and pre-owned vehicle dealers.

MONOREPO STRUCTURE (Turborepo + pnpm workspaces):
- Root: vehubpro/ with pnpm-workspace.yaml and turbo.json
- apps/web-super-admin     → React.js 18, Super Admin portal (Vite)
- apps/web-tenant          → React.js 18, Tenant portal (Vite)
- apps/web-public          → React.js 18, Public portfolio pages (Vite)
- apps/mobile              → React Native (Expo) — scaffold only, built in future phase
- apps/backend             → Python Django 4.2 + DRF (NOT a JS workspace — managed separately under apps/backend/)
- packages/ui              → Shared React component library (shadcn/ui base, used by all web apps)
- packages/shared-types    → Shared TypeScript types/interfaces used by web apps + future mobile
- packages/api-client      → Shared Axios API client + hooks used by web + mobile
- packages/utils           → Shared JS utilities: FY calc, GST formatter, date helpers, validators
- packages/constants       → Shared enums: roles, statuses, vehicle types, fuel types

STACK:
- Web Frontend: React.js 18, Vite, React Router v6, Redux Toolkit, TailwindCSS, shadcn/ui
- Mobile (future): React Native with Expo, consumes packages/api-client and packages/shared-types
- Backend: Python Django 4.2 + Django REST Framework (DRF), Celery + Redis for async tasks
- Database: PostgreSQL 15 with Row-Level Security (RLS) per tenant
- Storage: AWS S3 (boto3) for images and invoice PDFs
- Auth: DRF SimpleJWT (access + refresh tokens), RBAC middleware
- Cache: Redis for sessions, rate limiting, entitlement cache
- Monorepo: Turborepo for task orchestration, pnpm workspaces for package management

MULTI-TENANCY RULES:
- Every DB model that is tenant-scoped MUST have a `tenant` ForeignKey(Tenant)
- Every DRF ViewSet MUST filter queryset by `request.user.tenant` before any other filter
- Never expose data across tenants — test this with a separate tenant in every test
- Tenant context is always resolved from the authenticated user, never from URL params

SECURITY RULES (DPDP 2023 + GDPR + ISO 27001):
- ALL PII fields (name, email, mobile, address, IP, VIN, registration_no) MUST be encrypted using AES-256-GCM before saving to DB
- Use django-encrypted-fields or a custom EncryptedField using cryptography.fernet or pycryptodome AES-GCM
- Store a separate HMAC-SHA256 blind index column for any encrypted field that needs search (email, mobile, registration_no)
- NEVER log PII fields. Strip them in DRF exception handler before writing to log sinks
- Password hashing: use Django's default PBKDF2-SHA256 (minimum 480000 iterations) or argon2
- consent_given must be True before any customer/user PII is persisted — enforce at serializer level
- consent_timestamp is set once, never updated — use editable=False in model
- Soft-delete only for customers, vehicles, users — never hard delete PII
- All API responses: never return encrypted raw bytes — always decrypt in serializer before returning

GST RULES:
- Invoice number format: INV/{FY}/{6-digit-sequence} e.g. INV/25-26/000001
- FY = April 1 to March 31. If month >= 4: fy = f"{yr%100}-{(yr+1)%100:02d}" else f"{(yr-1)%100}-{yr%100:02d}"
- Sequence is per-tenant per-FY. Use SELECT ... FOR UPDATE or Redis INCR for concurrency safety
- CGST + SGST for intra-state, IGST for inter-state based on tenant.state == customer.state

S3 RULES:
- Never store S3 URLs in DB. Store the S3 object key only
- Generate pre-signed URLs at response time (expiry: 900 seconds / 15 minutes)
- All S3 buckets: enable SSE-S3 server-side encryption
- Compress images before upload using Pillow (max 1920px wide, 80% quality JPEG)
- Invoice PDFs stored in s3://vehubpro-invoices/{tenant_id}/{fy}/{invoice_number}.pdf

CODE QUALITY:
- Type hints on all Python functions
- Zod-style validation in React using react-hook-form + Yup
- All API errors: { "success": false, "error": { "code": "...", "message": "...", "field": "..." } }
- All API success: { "success": true, "data": {...}, "meta": { "page": 1, "total": 100 } }
- Write docstrings on all Django model classes and ViewSet classes
- Every model: created_at, updated_at auto fields. Soft-delete: is_active BooleanField default=True

AUDIT LOGGING:
- Every CREATE, UPDATE, DELETE on PII-bearing models writes to AuditLog: (actor, action, entity_type, entity_id, ip_address, old_value_hash, new_value_hash, timestamp)
- old_value and new_value stored as HMAC hash only — never store plaintext PII in audit logs
```

---

## 📁 MONOREPO FOLDER STRUCTURE

```
vehubpro/                              ← Monorepo root
├── .cursorrules                       ← Cursor AI global rules
├── turbo.json                         ← Turborepo pipeline config
├── pnpm-workspace.yaml                ← pnpm workspaces declaration
├── package.json                       ← Root package.json (dev scripts only)
│
├── apps/
│   ├── web-super-admin/               ← React 18 + Vite — Super Admin portal
│   │   ├── src/
│   │   │   ├── pages/                 ← Dashboard, Tenants, Packages, Plans, Subscriptions, Reports
│   │   │   ├── components/            ← Page-specific components
│   │   │   ├── store/                 ← Redux slices (superAdminSlice, authSlice)
│   │   │   ├── hooks/                 ← useTenants, useSubscriptions, usePlans
│   │   │   └── main.jsx
│   │   ├── package.json               ← depends on @vehubpro/ui, @vehubpro/api-client, @vehubpro/utils
│   │   └── vite.config.js
│   │
│   ├── web-tenant/                    ← React 18 + Vite — Tenant portal
│   │   ├── src/
│   │   │   ├── pages/
│   │   │   │   ├── Dashboard/
│   │   │   │   ├── Customers/
│   │   │   │   ├── Vehicles/
│   │   │   │   ├── ServicesMaster/
│   │   │   │   ├── JobCards/
│   │   │   │   ├── Invoices/
│   │   │   │   ├── Portfolio/
│   │   │   │   └── Insights/
│   │   │   ├── components/            ← Tenant-specific components
│   │   │   ├── store/                 ← tenantSlice, authSlice, jobCardSlice
│   │   │   └── hooks/                 ← useJobCards, useCustomers, useVehicles
│   │   ├── package.json               ← depends on @vehubpro/ui, @vehubpro/api-client
│   │   └── vite.config.js
│   │
│   ├── web-public/                    ← React 18 + Vite — Public portfolio (no auth)
│   │   ├── src/
│   │   │   ├── pages/
│   │   │   │   ├── PortfolioGallery/  ← /portfolio/:slug
│   │   │   │   └── VehicleDetail/    ← /portfolio/:slug/vehicle/:id
│   │   │   └── components/
│   │   ├── package.json               ← depends on @vehubpro/api-client, @vehubpro/utils
│   │   └── vite.config.js
│   │
│   ├── mobile/                        ← React Native + Expo (scaffold only — future phase)
│   │   ├── app/                       ← Expo Router pages
│   │   ├── components/
│   │   ├── package.json               ← will depend on @vehubpro/api-client, @vehubpro/shared-types
│   │   └── app.json
│   │
│   └── backend/                       ← Django 4.2 + DRF (Python — not a JS workspace)
│       ├── manage.py
│       ├── config/
│       │   ├── settings/
│       │   │   ├── base.py
│       │   │   ├── dev.py
│       │   │   └── prod.py
│       │   ├── urls.py
│       │   └── wsgi.py
│       ├── apps/
│       │   ├── core/                  ← Tenant, User, Subscription, Package, Plan models
│       │   ├── services_module/       ← Customer, Vehicle, ServiceCategory, ServiceItem, JobCard, Invoice
│       │   ├── portfolio_module/      ← InventoryVehicle, TestDriveBooking
│       │   ├── notifications/         ← Email, SMS, WhatsApp Celery tasks
│       │   ├── storage/               ← S3 upload/download service
│       │   └── audit/                 ← AuditLog model + middleware
│       ├── utils/
│       │   ├── encryption.py          ← AES-256-GCM + HMAC blind index
│       │   ├── gst.py                 ← GST calculation engine
│       │   ├── invoice_number.py      ← FY-based invoice sequence (Redis INCR)
│       │   ├── s3.py                  ← S3 upload + presigned URL service
│       │   └── permissions.py         ← RBAC permission classes
│       ├── requirements/
│       │   ├── base.txt
│       │   ├── dev.txt
│       │   └── prod.txt
│       └── pytest.ini
│
├── packages/
│   ├── ui/                            ← @vehubpro/ui — Shared React component library
│   │   ├── src/
│   │   │   ├── components/
│   │   │   │   ├── DataTable/         ← Sort, filter, pagination, export
│   │   │   │   ├── StatusBadge/       ← Color-coded status chips
│   │   │   │   ├── PageHeader/        ← Title + breadcrumb + actions
│   │   │   │   ├── ConfirmModal/      ← Reusable confirm dialog
│   │   │   │   ├── FormField/         ← react-hook-form + Yup error display
│   │   │   │   ├── KpiCard/           ← Analytics KPI card
│   │   │   │   ├── VehicleTypeBadge/  ← Icon + label per vehicle type
│   │   │   │   └── ConsentCheckbox/   ← DPDP consent checkbox with legal text
│   │   │   └── index.js               ← Barrel export
│   │   └── package.json               ← name: "@vehubpro/ui"
│   │
│   ├── api-client/                    ← @vehubpro/api-client — Shared API service layer
│   │   ├── src/
│   │   │   ├── client.js              ← Axios instance, JWT interceptors, token refresh
│   │   │   ├── endpoints/
│   │   │   │   ├── auth.js
│   │   │   │   ├── tenants.js
│   │   │   │   ├── customers.js
│   │   │   │   ├── vehicles.js
│   │   │   │   ├── jobCards.js
│   │   │   │   ├── invoices.js
│   │   │   │   ├── portfolio.js
│   │   │   │   └── public.js          ← No-auth portfolio endpoints
│   │   │   └── index.js
│   │   └── package.json               ← name: "@vehubpro/api-client"
│   │
│   ├── shared-types/                  ← @vehubpro/shared-types — TypeScript type definitions
│   │   ├── src/
│   │   │   ├── models/
│   │   │   │   ├── tenant.types.ts
│   │   │   │   ├── user.types.ts
│   │   │   │   ├── customer.types.ts
│   │   │   │   ├── vehicle.types.ts
│   │   │   │   ├── jobcard.types.ts
│   │   │   │   ├── invoice.types.ts
│   │   │   │   └── portfolio.types.ts
│   │   │   ├── enums/
│   │   │   │   ├── roles.ts
│   │   │   │   ├── vehicleTypes.ts
│   │   │   │   └── jobCardStatus.ts
│   │   │   └── index.ts
│   │   └── package.json               ← name: "@vehubpro/shared-types"
│   │
│   ├── utils/                         ← @vehubpro/utils — Shared JS utilities
│   │   ├── src/
│   │   │   ├── fy.js                  ← getCurrentFY(), getFYLabel(), isSameFY()
│   │   │   ├── gst.js                 ← formatGST(), getGSTBreakdown() display helpers
│   │   │   ├── date.js                ← formatDate(), daysSince(), isExpiringSoon()
│   │   │   ├── mask.js                ← maskMobile(), maskEmail(), maskRegNo()
│   │   │   └── validation.js          ← indianMobile(), gstinFormat(), regNoFormat()
│   │   └── package.json               ← name: "@vehubpro/utils"
│   │
│   └── constants/                     ← @vehubpro/constants — Shared enums + config
│       ├── src/
│       │   ├── roles.js               ← ROLES object used across web + mobile
│       │   ├── vehicleTypes.js        ← VEHICLE_TYPES, FUEL_TYPES, BODY_TYPES
│       │   ├── jobCardStatuses.js     ← JC_STATUS, JC_STATUS_TRANSITIONS map
│       │   ├── serviceCategories.js   ← Default category names per vehicle type
│       │   └── plans.js               ← PLAN_LIMITS, ADDON_TYPES
│       └── package.json               ← name: "@vehubpro/constants"
│
└── .github/
    └── workflows/
        ├── ci.yml                     ← Run tests on every PR
        └── deploy.yml                 ← Deploy on push to main
```

---

## 🗂️ PHASE 1 — Foundation & Infrastructure (Sprint 1–2)

### TASK 1.1 — Django Project Bootstrap

**Cursor Prompt:**
```
Create a Django 4.2 project called `vehubpro` with the following setup:
- Django REST Framework, SimpleJWT, django-cors-headers, psycopg2-binary, boto3, celery, redis, Pillow, cryptography installed in requirements/base.txt
- Settings split into config/settings/base.py, dev.py, prod.py
- base.py: INSTALLED_APPS includes apps.core, apps.services_module, apps.portfolio_module, apps.notifications, apps.storage, apps.audit
- Custom User model in apps.core.models inheriting AbstractBaseUser with fields: id (UUID), tenant (FK, nullable for SA users), email (EncryptedField), mobile (EncryptedField), full_name (EncryptedField), role (ENUM), is_active, consent_given, consent_timestamp (editable=False), created_at, updated_at
- AUTH_USER_MODEL = 'core.User'
- DRF settings: DEFAULT_AUTHENTICATION_CLASSES = JWTAuthentication, DEFAULT_PERMISSION_CLASSES = IsAuthenticated, EXCEPTION_HANDLER = custom handler that strips PII from error logs
- Configure DATABASES with PostgreSQL. Add db connection pooling with CONN_MAX_AGE=60
- Configure Celery with Redis broker
```

---

### TASK 1.2 — Encryption Utility

**Cursor Prompt:**
```
Create backend/utils/encryption.py with:

1. AES-256-GCM field encryption using Python `cryptography` library:
   - encrypt(plaintext: str, key: bytes) -> str  # returns base64(nonce + tag + ciphertext)
   - decrypt(ciphertext_b64: str, key: bytes) -> str
   - Key sourced from env var ENCRYPTION_KEY (32-byte hex). Never hardcoded.

2. HMAC blind index for searchable encrypted fields:
   - blind_index(value: str, key: bytes) -> str  # HMAC-SHA256 hex digest
   - Key sourced from separate env var BLIND_INDEX_KEY

3. EncryptedField (Django model field):
   - Subclass of TextField
   - from_db_value: calls decrypt()
   - get_prep_value: calls encrypt()
   - Never stores plaintext to DB

4. EncryptedSearchField (stores both encrypted value + blind index):
   - Creates two columns: {field_name}_encrypted and {field_name}_bidx
   - Searching by email: filter(email_bidx=blind_index(search_term))

5. PIIMaskingMixin for serializers:
   - mask_mobile(value): returns "+91 98***1234" format
   - mask_email(value): returns "us**@gm***.com" format
   - Applied in list serializers, full value in detail serializers

Unit tests: test encrypt→decrypt roundtrip, test blind index consistency, test masking formats.
```

---

### TASK 1.3 — GST & Invoice Number Utilities

**Cursor Prompt:**
```
Create backend/utils/gst.py and backend/utils/invoice_number.py:

gst.py:
- get_financial_year(date) -> str: returns "25-26" format. If month >= 4: f"{yr%100}-{(yr+1)%100:02d}" else f"{(yr-1)%100}-{yr%100:02d}"
- calculate_gst(line_items: list, tenant_state: str, customer_state: str) -> dict:
  - line_items: [{"base_price": Decimal, "gst_pct": Decimal, "qty": Decimal}]
  - If tenant_state == customer_state: split into cgst + sgst (each = total_gst / 2)
  - Else: igst = total_gst
  - Returns: {"subtotal": Decimal, "cgst": Decimal, "sgst": Decimal, "igst": Decimal, "total": Decimal}
- All calculations using Python Decimal with ROUND_HALF_UP
- Unit tests for intra-state, inter-state, zero GST, multiple line items

invoice_number.py:
- generate_invoice_number(tenant_id: UUID, redis_client) -> str:
  - Acquires Redis INCR on key f"inv_seq:{tenant_id}:{fy_code}"
  - Returns f"INV/{fy_code}/{seq:06d}"
  - On April 1: key resets (set TTL to expire on April 1 next year)
  - Fallback: if Redis unavailable, use SELECT MAX(sequence_no)+1 FOR UPDATE in invoices table
- generate_jobcard_number(tenant_id, redis_client) -> str:
  - Format: f"JC-{fy_code}-{seq:05d}"

Unit tests: test FY boundary (March 31 vs April 1), test sequence increment, test concurrent calls.
```

---

### TASK 1.4 — S3 Storage Service

**Cursor Prompt:**
```
Create backend/utils/s3.py:

- S3Client class using boto3:
  - upload_vehicle_image(tenant_id, file_obj, original_filename) -> str (S3 key):
    - Compress with Pillow: resize to max 1920px wide, 80% JPEG quality
    - Key: f"vehicles/{tenant_id}/{uuid4()}.jpg"
    - ContentType: image/jpeg, ServerSideEncryption: AES256
  - upload_invoice_pdf(tenant_id, fy_code, invoice_number, pdf_bytes) -> str (S3 key):
    - Key: f"invoices/{tenant_id}/{fy_code}/{invoice_number}.pdf"
    - ContentType: application/pdf, ACL: private
  - get_presigned_url(s3_key, expiry_seconds=900) -> str:
    - Generates presigned GET URL, expiry default 15 minutes
  - delete_object(s3_key) -> bool
  - All methods log S3 key only — never log file content or PII filenames

- Django model mixin: S3MediaMixin
  - Field: s3_key = CharField (stores key only, not URL)
  - Property: presigned_url — calls get_presigned_url() at request time
  - Never serialize s3_key directly to API — always serialize presigned_url

Settings required: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET_NAME, AWS_S3_REGION (all from env, never hardcoded)
```

---

### TASK 1.5 — RBAC Permission System

**Cursor Prompt:**
```
Create backend/utils/permissions.py with DRF permission classes:

Roles enum (in apps/core/models.py):
SUPER_ADMIN, PLATFORM_MANAGER, FINANCE_ADMIN, SUPPORT_AGENT,
OWNER, MANAGER, RECEPTIONIST, TECHNICIAN, SALES_STAFF, ACCOUNTANT

Permission classes:
- IsSuperAdmin: request.user.tenant is None and role in [SUPER_ADMIN, PLATFORM_MANAGER, FINANCE_ADMIN, SUPPORT_AGENT]
- IsTenantOwner: request.user.tenant is not None and role == OWNER
- IsTenantManager: role in [OWNER, MANAGER]
- CanManageJobCards: role in [OWNER, MANAGER, RECEPTIONIST, TECHNICIAN]
- CanViewInvoices: role in [OWNER, MANAGER, RECEPTIONIST, ACCOUNTANT]
- CanManagePortfolio: role in [OWNER, MANAGER, SALES_STAFF]
- IsSameTenant: checks request.user.tenant == obj.tenant (object-level)

TenantScopedViewSetMixin:
- Override get_queryset(): always filters by tenant=request.user.tenant
- Override perform_create(): injects tenant=request.user.tenant
- Override get_object(): calls check_object_permissions with IsSameTenant

Write unit tests for each permission class with different role combinations.
```

---

### TASK 1.6 — Audit Log System

**Cursor Prompt:**
```
Create apps/audit/models.py and apps/audit/middleware.py:

AuditLog model:
- id: UUID PK
- actor_id: UUID (user id, nullable for system events)
- actor_role: VARCHAR
- tenant_id: UUID nullable
- action: ENUM (CREATE, READ, UPDATE, DELETE, LOGIN, LOGOUT, EXPORT, ERASURE_REQUEST, CONSENT_GIVEN, STATUS_CHANGE, PII_ACCESS)
- entity_type: VARCHAR (e.g. "Customer", "Invoice", "JobCard")
- entity_id: UUID
- ip_address: EncryptedField (GDPR: IP = personal data)
- user_agent: VARCHAR (truncated to 255)
- old_value_hash: VARCHAR nullable (HMAC of old JSON — never raw PII)
- new_value_hash: VARCHAR nullable
- metadata: JSONField (non-PII context: status change from/to, invoice number, etc.)
- created_at: TIMESTAMP (auto, immutable — no updated_at on audit logs)
- Meta: managed=True, indexes on (tenant_id, entity_type, created_at), db_table='audit_logs'

AuditLogService:
- log(actor, action, entity_type, entity_id, request, old_obj=None, new_obj=None, metadata=None)
- Runs async via Celery task to not block request
- Call in: serializer save(), status change endpoints, export endpoints, login/logout signals

AuditMiddleware:
- Attaches request.start_time for response time tracking
- Logs all 401/403 responses to audit log (failed access attempts)
```

---

### TASK 1.7 — Monorepo Bootstrap (Turborepo + pnpm)

**Cursor Prompt:**
```
Set up the VeHubPro Turborepo monorepo:

STEP 1 — Root workspace init:
- Create root package.json with private:true, packageManager: "pnpm@9.x"
- Create pnpm-workspace.yaml:
    packages:
      - "apps/*"
      - "packages/*"
- Create turbo.json:
    {
      "pipeline": {
        "build": { "dependsOn": ["^build"], "outputs": ["dist/**"] },
        "dev":   { "cache": false, "persistent": true },
        "test":  { "dependsOn": ["^build"] },
        "lint":  {}
      }
    }
- Root scripts: "dev": "turbo run dev", "build": "turbo run build", "test": "turbo run test", "lint": "turbo run lint"

STEP 2 — packages/constants (@vehubpro/constants):
- Pure JS, no framework dependency (so React Native can import it too)
- Export ROLES, VEHICLE_TYPES, FUEL_TYPES, BODY_TYPES, JC_STATUS, JC_STATUS_TRANSITIONS, ADDON_TYPES, PLAN_LIMITS
- JC_STATUS_TRANSITIONS: { DRAFT: ['CONFIRMED','CANCELLED'], CONFIRMED: ['IN_PROGRESS','CANCELLED'], IN_PROGRESS: ['ON_HOLD','COMPLETED'], ON_HOLD: ['IN_PROGRESS','CANCELLED'], COMPLETED: ['INVOICED'], INVOICED: ['DELIVERED'], DELIVERED: [], CANCELLED: [] }

STEP 3 — packages/utils (@vehubpro/utils):
- Pure JS (no React), so React Native can import it
- fy.js: getCurrentFY(), getFYLabel(fyCode), getFYStart(fyCode), getFYEnd(fyCode)
- gst.js: formatINR(amount), getGSTLabel(cgst, sgst, igst)
- date.js: formatDate(iso), formatDateTime(iso), daysSince(iso), isExpiringSoon(date, days=30)
- mask.js: maskMobile(mobile) → "+91 98***1234", maskEmail(email) → "us**@gm***.com", maskRegNo(reg) → "KA01**1234"
- validation.js: isValidIndianMobile(str), isValidGSTIN(str), isValidRegNo(str)

STEP 4 — packages/shared-types (@vehubpro/shared-types):
- TypeScript types only (no runtime code)
- Define interfaces: Tenant, User, Customer, Vehicle, ServiceCategory, ServiceItem, JobCard, Invoice, InventoryVehicle, TestDriveBooking, Subscription, SubscriptionAddon
- Define enum types: Role, VehicleType, FuelType, JobCardStatus, InvoicePaymentStatus
- All types exported from index.ts
- Used by web apps and future React Native mobile app

STEP 5 — packages/api-client (@vehubpro/api-client):
- Works in both browser (React) and React Native (Expo) — use axios (works in both environments)
- client.js: Axios instance, baseURL from env. Request interceptor: attach Bearer token. Response interceptor: on 401 → call refresh endpoint, retry original request once, on second fail → call onAuthFailure() callback (injected by app, not hardcoded — so web does router redirect, mobile does navigation reset)
- Token storage: abstract via createApiClient({ getToken, setToken, clearToken, onAuthFailure }) factory — web apps pass localStorage/cookie helpers, mobile app passes SecureStore helpers
- endpoints/: one file per domain, each function returns typed promise using shared-types interfaces

STEP 6 — packages/ui (@vehubpro/ui):
- React-only (web), TailwindCSS + shadcn/ui base
- Export: DataTable, StatusBadge, PageHeader, ConfirmModal, FormField, KpiCard, VehicleTypeBadge, ConsentCheckbox, Pagination, SearchInput, DateRangePicker, FileDropzone (for image upload)
- ConsentCheckbox props: { label: string, regulationText: string, required: boolean } — used for DPDP consent on CustomerCreate

STEP 7 — Three web apps (apps/web-super-admin, apps/web-tenant, apps/web-public):
- Each: Vite + React 18, TailwindCSS config that reads from packages/ui
- Each package.json: workspace dependencies "@vehubpro/ui": "workspace:*", "@vehubpro/api-client": "workspace:*", "@vehubpro/utils": "workspace:*", "@vehubpro/shared-types": "workspace:*", "@vehubpro/constants": "workspace:*"
- Each has own Redux store (only web-super-admin and web-tenant need Redux — web-public is stateless)
- Each has own .env file: VITE_API_URL, VITE_APP_NAME

STEP 8 — apps/mobile scaffold (@vehubpro/mobile):
- Expo SDK 51 + React Native
- app.json with name: "VeHubPro", slug: "vehubpro"
- package.json: depends on @vehubpro/api-client, @vehubpro/shared-types, @vehubpro/utils, @vehubpro/constants
- app/ folder with Expo Router: (auth)/login.jsx, (tenant)/dashboard.jsx — scaffold only
- NOTE: Do NOT implement mobile screens now. Just create the scaffold so the monorepo resolves correctly.
- Add metro.config.js to resolve monorepo packages: use @expo/metro-config with watchFolders pointing to packages/*
```

---

## 🏢 PHASE 2 — Super Admin Portal (Sprint 3–4)

### TASK 2.1 — Tenant Management API + UI

**Cursor Prompt:**
```
Backend — apps/core/views.py:
Create TenantViewSet (ModelViewSet, permission: IsSuperAdmin):
- list: paginated, filter by status, search by business_name and slug
- create: validate slug uniqueness, create default Owner user, send welcome email via Celery
- retrieve: include active_subscription, module_entitlements, user_count, vehicle_count
- update: PATCH only allowed fields
- destroy: soft-delete (is_active=False), does NOT delete tenant data
- Custom actions:
  - POST /tenants/{id}/suspend/ → status=SUSPENDED, notify owner
  - POST /tenants/{id}/reactivate/ → status=ACTIVE
  - GET /tenants/{id}/module-overrides/ → list overrides
  - POST /tenants/{id}/module-overrides/ → add override

Tenant serializer:
- owner_name, owner_email, owner_mobile: decrypt and mask in list (show last 4 digits)
- Full decrypt in retrieve only (log PII_ACCESS to audit)
- bank_account_no: always masked (XXXX{last4})

Frontend — src/apps/super-admin/pages/Tenants/:
- TenantList.jsx: DataTable with columns: business_name, owner_name (masked), status badge, plan, created_at, Actions
- TenantCreate.jsx: form with step 1 (business info) + step 2 (assign subscription)
- TenantDetail.jsx: tabs: Overview | Subscription | Modules | Users | Audit Log
- Use StatusBadge component: ACTIVE=green, TRIAL=blue, SUSPENDED=orange, CANCELLED=red
```

---

### TASK 2.2 — Package + Plan + Subscription Management

**Cursor Prompt:**
```
Backend — Create Package, Plan, Subscription, SubscriptionHistory, SubscriptionAddon models:

Package model: id, name, description, modules (JSONField: list of module keys), is_active
Plan model: id, package (FK), name, price, billing_cycle (MONTHLY/ANNUAL/CUSTOM), user_limit, vehicle_limit, listing_limit, storage_limit_gb, trial_days, is_active
Subscription model (full schema from PRD section 3.3): all fields including user_limit, vehicle_limit, listing_limit, storage_limit_gb, user_count, vehicle_count, listing_count, storage_used_gb
SubscriptionHistory model (PRD section 3.3.1): immutable — override save() to block updates, override delete() to block deletes
SubscriptionAddon model (PRD section 3.3.2): all addon_type options

Create SubscriptionService:
- assign_subscription(tenant, plan, assigned_by, notes): creates Subscription + SubscriptionHistory(CREATED) + activates module entitlements
- get_effective_limits(tenant_id): base subscription limits + SUM of active addon quantities, cached in Redis TTL 300s
- check_user_limit(tenant_id) -> bool: current user_count < effective user_limit
- check_vehicle_limit(tenant_id) -> bool: similar
- on_plan_change(subscription, new_plan, changed_by): creates SubscriptionHistory(UPGRADED or DOWNGRADED)

Frontend:
- PackageMatrix.jsx: grid showing Package × Module toggles (Super Admin sets which modules each package includes)
- PlanList.jsx: grouped by Package, with Create Plan modal
- TenantSubscriptionPanel.jsx: shows current plan, usage bars (users X/10, vehicles X/500, storage X GB / 20 GB), upgrade/downgrade buttons, addon list, history timeline
```

---

## 🔧 PHASE 3 — Services Module (Sprint 5–7)

### TASK 3.1 — Customer Management

**Cursor Prompt:**
```
Backend — apps/services_module/models.py:
Customer model:
- All PII fields encrypted: full_name (EncryptedField), mobile (EncryptedSearchField = encrypted + HMAC bidx), email (EncryptedSearchField), address (EncryptedField), consent_ip (EncryptedField)
- consent_given: BooleanField, editable=False after True
- consent_timestamp: DateTimeField, auto_now_add=False, editable=False, set once in save()
- is_active: soft delete
- tenant: FK

CustomerSerializer:
- validate(): check consent_given=True, else raise ValidationError("DPDP: Consent required")
- create(): set consent_timestamp=now(), consent_ip from request.META['REMOTE_ADDR'] (encrypted)
- List serializer: mask mobile and email
- Detail serializer: full decrypt, log PII_ACCESS to AuditLog

CustomerViewSet:
- get_queryset(): filter by tenant, is_active=True
- search: filter by mobile_bidx=blind_index(q) OR full_name (decrypt+compare is slow — index on name hash too)
- destroy(): soft delete only, log DELETE to audit

Frontend — src/apps/tenant/pages/Customers/:
- CustomerList.jsx: searchable table, click row → detail
- CustomerCreate.jsx: form with DPDP consent checkbox (required, cannot proceed without checking)
  - Consent text: "I confirm this customer has given explicit consent for their data to be stored and used for vehicle service management as per DPDP Act 2023."
- CustomerDetail.jsx: profile card + vehicles list + service history timeline
- Mask mobile/email in list. Show full on detail with "Click to reveal" button that logs access.
```

---

### TASK 3.2 — Service Vehicles

**Cursor Prompt:**
```
Backend — Vehicle model:
- customer (FK to Customer), tenant (FK to Tenant)
- registration_no: EncryptedSearchField (encrypted + HMAC blind index for search)
- vin_number: EncryptedField
- vehicle_type: ENUM (CAR/MOTORCYCLE/SCOOTER/TRUCK/BUS/AUTO_RICKSHAW/EV_2W/EV_3W/EV_4W/COMMERCIAL/TRACTOR/OTHER)
- brand, model, year, fuel_type, transmission, color, engine_cc, battery_capacity_kwh: plaintext (not PII)
- insurance_expiry, puc_expiry, permit_expiry, fitness_cert_expiry: DateField (plaintext — used for alert triggers)
- no_of_wheels, load_capacity_kg: IntegerField nullable
- is_active: soft delete

VehicleViewSet:
- list: filter by tenant + customer_id param + vehicle_type param
- create: check subscription vehicle_limit via SubscriptionService.check_vehicle_limit() — raise 403 if exceeded
- on create success: increment subscription.vehicle_count

Expiry alert Celery task (run daily at 9AM):
- Query vehicles where insurance_expiry between today and today+30 days
- Query vehicles where puc_expiry between today and today+15 days  
- Query vehicles where permit_expiry between today and today+30 days
- Send WhatsApp/SMS notification to tenant owner for each expiring vehicle
- Log notification sent in audit

Frontend — VehicleForm.jsx:
- vehicle_type dropdown first — dynamically shows/hides fields based on type
  (battery_capacity_kwh shows only for EV types, load_capacity_kg shows for TRUCK/COMMERCIAL)
- Registration number field: auto-uppercase, format hint "KA01AB1234"
- Show expiry date fields with color indicators: red if expired, orange if within 30 days, green if valid
```

---

### TASK 3.3 — Services Master (Categories + Items)

**Cursor Prompt:**
```
Backend:
ServiceCategory model: tenant(FK), category_name, applicable_vehicle_types (ArrayField of ENUM), icon_code, sort_order, is_active
ServiceItem model: tenant(FK), category(FK ServiceCategory), service_name, description, base_price (Decimal), hsn_code, gst_percentage (Decimal), unit_type (ENUM: PER_SERVICE/PER_HOUR/PER_KM), applicable_vehicle_types (ArrayField, optional override), is_active

ServiceCategoryViewSet: tenant-scoped, filter by applicable_vehicle_types query param
ServiceItemViewSet: tenant-scoped, filter by category_id, applicable_vehicle_types, search by service_name

Seeder command: management/commands/seed_service_categories.py
- Creates default categories + items for a new tenant on onboarding:
  Engine & Lubrication, Brake System, Electrical, AC & Climate, Suspension & Steering,
  Tyres, Chain & Drivetrain (for 2W), Body & Exterior, Transmission, EV Specific, CNG/LPG Kit,
  Periodic Maintenance, Inspection
- Each category has applicable_vehicle_types set per PRD section 4.4

Frontend — ServiceMasterPage.jsx:
- Left panel: category list with vehicle type filter chips
- Right panel: service items for selected category (edit in-place)
- Add Category modal: name + vehicle type multi-select chips + sort order
- Add Service Item modal: name, price, HSN code, GST% selector (5/12/18/28), unit type
```

---

### TASK 3.4 — Job Cards

**Cursor Prompt:**
```
Backend — JobCard model:
- tenant(FK), customer(FK), vehicle(FK), jobcard_number (unique per tenant+FY)
- status: ENUM (DRAFT/CONFIRMED/IN_PROGRESS/ON_HOLD/COMPLETED/INVOICED/DELIVERED/CANCELLED)
- km_reading: IntegerField, next_service_km: IntegerField nullable
- notes: EncryptedField (may contain sensitive customer complaint details — DPDP)
- assigned_technician: FK(User) nullable
- estimated_delivery: DateTimeField nullable
- subtotal, discount_amount, cgst_amount, sgst_amount, igst_amount, total_amount: DecimalField
- created_at, updated_at

JobCardService model (junction): jobcard(FK), service_item_snapshot (JSONB: {id, name, base_price, gst_pct, qty, line_total})
- Snapshot service name + price at creation time — price changes don't affect old job cards

JobCardViewSet:
- create: validate vehicle.tenant == request.user.tenant, validate customer.tenant == request.user.tenant
  - Calculate GST using gst.py calculate_gst()
  - Generate jobcard_number using invoice_number.py generate_jobcard_number()
  - Only OWNER/MANAGER/RECEPTIONIST can create
- status_change action (POST /job-cards/{id}/status/):
  - Enforce state machine transitions from PRD section 4.5
  - TECHNICIAN can only move: CONFIRMED→IN_PROGRESS, IN_PROGRESS→ON_HOLD, ON_HOLD→IN_PROGRESS, IN_PROGRESS→COMPLETED
  - RECEPTIONIST/MANAGER can move all states
  - Log STATUS_CHANGE to AuditLog with metadata {from_status, to_status}
  
Frontend — JobCardKanban.jsx:
- Columns: CONFIRMED, IN_PROGRESS, ON_HOLD, COMPLETED, INVOICED, DELIVERED
- Drag-drop cards between valid next states only (disable invalid drop targets)
- Card shows: JC number, customer name (masked), vehicle reg (masked), total amount, technician avatar

Frontend — JobCardCreate.jsx (3-step form):
- Step 1: Customer search (typeahead by mobile blind index) + vehicle selector (filtered by customer)
- Step 2: Service selector — grouped by category, filtered by vehicle.vehicle_type. Running total updates in real-time with GST breakdown
- Step 3: Details — km reading, notes, estimated delivery, technician assignment
```

---

### TASK 3.5 — Invoice Generation

**Cursor Prompt:**
```
Backend — Invoice model:
- tenant(FK), jobcard(FK OneToOne), invoice_number (unique), fy_code, sequence_no
- customer_name_snapshot: EncryptedField
- customer_mobile_snapshot: EncryptedField  
- customer_address_snapshot: EncryptedField
- customer_gstin_snapshot: VARCHAR nullable (plaintext — statutory)
- subtotal, discount, cgst, sgst, igst, total: DecimalField (plaintext — GST audit)
- payment_status: ENUM (UNPAID/PARTIAL/PAID)
- payment_mode: ENUM (CASH/UPI/CARD/BANK_TRANSFER/CHEQUE)
- amount_paid: DecimalField
- pdf_s3_key: EncryptedField (S3 key is encrypted)
- created_at (immutable after creation — no update allowed except payment fields)

InvoiceService:
- generate(jobcard_id, user):
  - Check jobcard.status == COMPLETED else raise ValidationError
  - Snapshot customer PII (decrypt from Customer, re-encrypt into Invoice fields)
  - Generate invoice_number via generate_invoice_number()
  - Calculate GST totals
  - Generate PDF using ReportLab or WeasyPrint with tenant logo, GST details, line items
  - Upload PDF to S3 via S3Client.upload_invoice_pdf()
  - Set jobcard.status = INVOICED
  - Log CREATE to AuditLog

InvoiceViewSet:
- retrieve: decrypt snapshots, generate presigned S3 URL for PDF, log PII_ACCESS
- Never allow update of invoice_number, subtotal, cgst, sgst, total, line_items
- payment action (POST /invoices/{id}/record-payment/): update payment_status + amount_paid only
- send_whatsapp action: send PDF presigned URL via WhatsApp Business API, log to audit

Frontend — InvoiceView.jsx:
- Shows invoice in paper-like layout matching printed GST invoice format
- Download PDF button (fetches presigned URL, opens in new tab)
- Send via WhatsApp button
- Record Payment section: mode selector + amount input + reference number
- Payment status badge: UNPAID=red, PARTIAL=orange, PAID=green
```

---

## 🚗 PHASE 4 — Portfolio Module (Sprint 8–9)

### TASK 4.1 — Inventory Vehicle Listing

**Cursor Prompt:**
```
Backend — InventoryVehicle model (portfolio):
- tenant(FK), vehicle_type ENUM, brand, model, variant, year, no_of_owners, last_rto
- registration_no: EncryptedField (privacy — not always shown publicly)
- fuel_type, transmission, km_driven, engine_cc, battery_capacity_kwh, color, body_type: plaintext
- key_features: ArrayField(CharField) 
- description: TextField
- base_price, final_price, sold_price: DecimalField
- insurance_status ENUM, insurance_expiry DATE, fc_date DATE, permit_expiry DATE
- images: JSONField (list of S3 keys — NOT URLs)
- video_url: URLField nullable
- status: ENUM (AVAILABLE/BOOKED/SOLD/ARCHIVED)
- is_featured: BooleanField
- view_count: IntegerField default 0 (incremented on public page view)

InventoryVehicleViewSet (tenant portal):
- create/update: handle image upload — accept multipart/form-data, upload each image via S3Client, store key list
- Images: max 20, compress via Pillow before upload
- status_change: SOLD requires sold_price, updates SubscriptionHistory if listing_count changes
- list: return presigned URLs for images (generated at response time, 15min expiry)

Public API ViewSet (no auth):
- GET /public/portfolio/{tenant_slug}/vehicles/ — filter AVAILABLE+BOOKED only, no PII
- GET /public/portfolio/{tenant_slug}/vehicles/{id}/ — full specs, presigned image URLs, increment view_count async via Celery
- POST /public/portfolio/{tenant_slug}/test-drives/ — create TestDriveBooking, OTP verify mobile

Frontend — InventoryVehicleForm.jsx (multi-step):
- Step 1: vehicle_type selector with icon cards → dynamically adjusts form fields
- Step 2: Basic specs (brand, model, year, fuel, transmission, km, color, body_type, engine_cc or battery_kwh based on type)
- Step 3: Pricing (base_price, final_price)
- Step 4: Compliance (insurance_status, insurance_expiry, fc_date, permit_expiry)
- Step 5: Key features (multi-select chips, options vary by vehicle_type)
- Step 6: Image upload (drag-drop, reorder via drag, set thumbnail = first image)
- Step 7: Description (rich text)
- Step 8: Preview → Publish

Frontend — Public Portfolio Page (src/apps/public/portfolio/[slug]):
- Server-rendered or React with SEO meta tags
- Vehicle grid with filter sidebar: fuel_type, transmission, price range slider, brand, vehicle_type, body_type
- Book Test Drive modal: name, phone (OTP verify), preferred date/time
- WhatsApp click-to-chat button
- Share vehicle button (copy URL + WhatsApp share)
```

---

## 🔒 PHASE 5 — Security Hardening & Compliance (Sprint 10)

### TASK 5.1 — DPDP Compliance Endpoints

**Cursor Prompt:**
```
Create apps/core/views/compliance.py:

1. DataExportView (GET /api/compliance/export/):
   - Permission: IsTenantOwner only
   - Exports all customer data for the tenant as JSON
   - Decrypts all PII fields for the export file
   - Uploads export to S3 as encrypted ZIP, sends download link via email
   - Logs EXPORT to AuditLog with record_count

2. DataErasureView (POST /api/compliance/erase-customer/{customer_id}/):
   - Permission: IsTenantOwner only
   - Sets customer PII fields to "[ERASED]" (does NOT delete the record)
   - Nulls vehicle registration_no and vin_number for vehicles owned by this customer
   - Keeps invoice financial totals (GST compliance) — erases customer_name_snapshot, customer_mobile_snapshot, customer_address_snapshot in invoices
   - Logs ERASURE_REQUEST to AuditLog
   - Returns summary of what was erased

3. ConsentWithdrawalView (POST /api/compliance/consent-withdrawal/{customer_id}/):
   - Marks customer.consent_given = False (logs CONSENT_WITHDRAWAL)
   - Blocks further marketing communication
   - Does NOT erase data — erasure must be explicitly requested

4. BreachNotificationService:
   - check_and_notify_breach(affected_tenant_ids, breach_description):
     - Sends breach notification email to affected tenant owners
     - Creates breach_incidents record with timestamp, description, affected_records_count
     - Triggers internal alert to Super Admin
     - Target: complete within 72 hours of detection (DPDP s.8 / GDPR Art.33)
```

---

### TASK 5.2 — API Security & Rate Limiting

**Cursor Prompt:**
```
Add to Django REST Framework config and middleware:

1. Rate limiting using django-ratelimit + Redis:
   - Login endpoint: 5 attempts per IP per 15 minutes. Lock IP for 30 minutes after exceeded.
   - OTP endpoints: 3 requests per mobile per 10 minutes
   - Public portfolio API: 100 requests per IP per minute
   - Authenticated API: 1000 requests per user per hour
   - On limit exceeded: return 429 with Retry-After header

2. Security headers middleware (or use django-csp):
   - X-Content-Type-Options: nosniff
   - X-Frame-Options: DENY
   - Strict-Transport-Security: max-age=31536000; includeSubDomains
   - Content-Security-Policy: default-src 'self'
   - Referrer-Policy: strict-origin-when-cross-origin

3. Input sanitization:
   - All string inputs: strip HTML tags using bleach
   - SQL injection: use Django ORM only — never raw SQL unless parameterized
   - File uploads: validate MIME type (python-magic), reject if not image/pdf, max 10MB

4. JWT security:
   - Access token TTL: 15 minutes
   - Refresh token TTL: 7 days, rotated on every use (ROTATE_REFRESH_TOKENS=True)
   - Store refresh token in httpOnly, SameSite=Strict cookie — not in JavaScript accessible storage
   - Blacklist refresh tokens on logout using SimpleJWT's TokenBlacklist

5. MFA (optional but required for OWNER + Super Admin roles):
   - django-otp with TOTP
   - Enforce MFA on first login if role is OWNER or SUPER_ADMIN
   - Backup codes: generate 10 one-time codes, store hashed
```

---

### TASK 5.3 — Automated Testing

**Cursor Prompt:**
```
Create comprehensive test suite:

Backend tests (pytest-django):

1. tests/test_encryption.py:
   - test encrypt_decrypt_roundtrip
   - test blind_index_consistency (same input always same output)
   - test pii_not_in_db (create Customer, read raw DB row, assert encrypted bytes not plaintext)
   - test masking_format (mobile, email)

2. tests/test_gst.py:
   - test_intra_state_gst (CGST+SGST split)
   - test_inter_state_gst (IGST only)
   - test_multiple_line_items (sum correct)
   - test_zero_gst_item
   - test_fy_boundary (March 31 → April 1 transition)
   - test_invoice_sequence_increment
   - test_invoice_sequence_reset_on_new_fy

3. tests/test_tenant_isolation.py:
   - Create 2 tenants with customers
   - Log in as tenant_1 user
   - Assert GET /customers/ returns ONLY tenant_1 customers
   - Assert GET /customers/{tenant2_customer_id}/ returns 404

4. tests/test_jobcard_workflow.py:
   - test_full_workflow: create customer → vehicle → job card → complete → invoice
   - test_invalid_status_transitions
   - test_vehicle_limit_enforcement (exceed subscription limit → 403)

5. tests/test_compliance.py:
   - test_dpdp_consent_required (create customer without consent → 400)
   - test_data_erasure (erase customer → PII replaced with [ERASED])
   - test_invoice_immutability (PUT invoice → 405)
   - test_audit_log_on_pii_access

Frontend tests (Vitest + React Testing Library):
- CustomerCreate: consent checkbox required before submit
- JobCardCreate: vehicle filtered by selected customer
- InvoiceView: PDF download triggers presigned URL fetch
```

---

## 📊 PHASE 6 — Analytics Dashboards (Sprint 11)

### TASK 6.1 — Tenant Service Insights

**Cursor Prompt:**
```
Backend — Create apps/services_module/analytics.py:

ServiceAnalyticsView (GET /api/analytics/services/):
- Permission: OWNER, MANAGER only
- Query params: date_from, date_to, group_by (day/week/month)
- Returns:
  {
    "revenue_trend": [{"period": "2025-04", "amount": 45000}],
    "job_volume_by_status": {"COMPLETED": 45, "IN_PROGRESS": 12, "DELIVERED": 120},
    "top_services": [{"service_name": "Oil Change", "count": 89, "revenue": 4450}],
    "vehicle_type_breakdown": {"CAR": 60, "MOTORCYCLE": 30, "TRUCK": 10},
    "avg_job_value": 1250.00,
    "customer_retention_rate": 0.68
  }
- All queries use annotation + values() — no Python-level loops
- Results cached in Redis with TTL 300s per tenant

Frontend — ServiceInsightsPage.jsx:
- Date range picker (Today / This Week / This Month / Custom)
- Revenue trend: Recharts AreaChart
- Job volume: Recharts BarChart grouped by status
- Top services: horizontal BarChart
- Vehicle type: PieChart
- KPI cards: Total Revenue, Total Jobs, Avg Job Value, Retention Rate
```

---

## 🚀 PHASE 7 — Production Deployment (Sprint 12)

### TASK 7.1 — Production Setup (No Docker)

**Cursor Prompt:**
```
Set up production deployment WITHOUT Docker, using managed cloud services:

INFRASTRUCTURE OVERVIEW:
- Backend (Django): AWS Elastic Beanstalk (Python platform) OR Render.com (Python web service)
- Frontend (React): AWS Amplify Hosting OR Vercel (one deployment per web app)
- Database: AWS RDS PostgreSQL 15 (Multi-AZ for production)
- Cache / Broker: AWS ElastiCache Redis OR Upstash Redis
- Media Storage: AWS S3 (images + invoice PDFs)
- Celery Workers: AWS Elastic Beanstalk worker tier OR Render background worker
- CDN: AWS CloudFront in front of S3 for media delivery

STEP 1 — Environment Variables (never in code):
Create apps/backend/.env.example listing all required vars:
  DJANGO_SECRET_KEY=
  DJANGO_DEBUG=False
  DJANGO_ALLOWED_HOSTS=api.vehubpro.com
  DATABASE_URL=postgres://user:password@rds-host:5432/vehubpro
  REDIS_URL=rediss://upstash-url:6379
  ENCRYPTION_KEY=                     # 32-byte hex — generate with: python -c "import secrets; print(secrets.token_hex(32))"
  BLIND_INDEX_KEY=                     # separate 32-byte hex key
  AWS_ACCESS_KEY_ID=
  AWS_SECRET_ACCESS_KEY=
  AWS_S3_BUCKET_NAME=vehubpro-media
  AWS_S3_INVOICES_BUCKET=vehubpro-invoices
  AWS_S3_REGION=ap-south-1
  AWS_CLOUDFRONT_DOMAIN=
  RAZORPAY_KEY_ID=
  RAZORPAY_KEY_SECRET=
  WHATSAPP_API_TOKEN=
  SENDGRID_API_KEY=
  MSG91_AUTH_KEY=
  CELERY_BROKER_URL=                   # same as REDIS_URL

STEP 2 — Django production settings (config/settings/prod.py):
- DEBUG = False
- ALLOWED_HOSTS from env
- DATABASES from DATABASE_URL using dj-database-url
- SECURE_SSL_REDIRECT = True
- SECURE_HSTS_SECONDS = 31536000
- SECURE_HSTS_INCLUDE_SUBDOMAINS = True
- SESSION_COOKIE_SECURE = True
- CSRF_COOKIE_SECURE = True
- CSRF_COOKIE_HTTPONLY = True
- CONN_MAX_AGE = 60
- STATIC_ROOT = BASE_DIR / "staticfiles"
- Add whitenoise for static file serving: MIDDLEWARE add WhiteNoiseMiddleware after SecurityMiddleware
- DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
- LOGGING: StreamHandler to stdout (Elastic Beanstalk/Render captures stdout), level INFO, strip PII in custom filter

STEP 3 — Procfile (for Render or Heroku-style platforms):
Create apps/backend/Procfile:
  web: gunicorn config.wsgi:application --workers 4 --bind 0.0.0.0:$PORT --timeout 120
  worker: celery -A config worker --loglevel=info --concurrency=4
  beat: celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler

STEP 4 — requirements/prod.txt additions:
  gunicorn==21.2.0
  whitenoise==6.6.0
  dj-database-url==2.1.0
  django-storages[s3]==1.14.2
  psycopg2-binary==2.9.9

STEP 5 — GitHub Actions CI/CD (.github/workflows/ci.yml):
On pull_request:
  - Checkout code
  - Setup Python 3.11, install requirements/dev.txt
  - Run: cd apps/backend && pytest --tb=short -q
  - Setup Node 20, pnpm install
  - Run: pnpm turbo run lint test build

On push to main (.github/workflows/deploy.yml):
  - Run all CI steps above first
  - Deploy backend: trigger Render deploy webhook OR eb deploy via AWS EB CLI
  - Deploy web-super-admin: trigger Vercel/Amplify deploy via CLI or webhook
  - Deploy web-tenant: same
  - Deploy web-public: same

STEP 6 — AWS S3 bucket setup (via AWS CLI or console — one-time):
  # Media bucket (vehicle images)
  aws s3api create-bucket --bucket vehubpro-media --region ap-south-1
  aws s3api put-bucket-encryption --bucket vehubpro-media --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block --bucket vehubpro-media --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
  
  # Invoice PDFs bucket (stricter)
  aws s3api create-bucket --bucket vehubpro-invoices --region ap-south-1
  aws s3api put-bucket-encryption --bucket vehubpro-invoices --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block --bucket vehubpro-invoices --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
  aws s3api put-bucket-versioning --bucket vehubpro-invoices --versioning-configuration Status=Enabled

STEP 7 — Frontend deployment (Vercel, one app per project):
  # In each web app directory:
  vercel --prod
  # Set env vars in Vercel dashboard: VITE_API_URL=https://api.vehubpro.com
  # web-super-admin → admin.vehubpro.com
  # web-tenant → app.vehubpro.com  
  # web-public → vehubpro.com (or portfolio.vehubpro.com)

STEP 8 — Post-deploy production checklist:
  □ DATABASE_URL points to RDS, not local postgres
  □ ENCRYPTION_KEY and BLIND_INDEX_KEY set in Render/EB env vars (not in .env file in repo)
  □ S3 buckets: Block all public access enabled, SSE-AES256 enabled
  □ Redis: TLS URL (rediss://) used, not plain redis://
  □ Django ALLOWED_HOSTS matches actual domain
  □ CORS_ALLOWED_ORIGINS set to frontend domains only
  □ Run: python manage.py check --deploy (should report no issues)
  □ Run: python manage.py migrate --run-syncdb on first deploy
  □ Celery worker and beat both running as separate processes
  □ CloudWatch / Render logs: verify no PII appearing in logs
  □ Test DPDP erasure endpoint in production with a test customer
```

---

## 📋 SPRINT SUMMARY TABLE

| Sprint | Duration | Deliverable | Exit Criteria |
|--------|----------|-------------|---------------|
| 1 | 2 weeks | Turborepo monorepo setup, all packages scaffolded, Django bootstrap, encryption utils, GST utils, S3 service, RBAC | `pnpm dev` starts all 3 web apps. Encrypt/decrypt tests pass. Tenant isolation test passes. |
| 2 | 2 weeks | Super Admin: Tenant Mgmt, Package/Plan/Subscription APIs + UI (uses @vehubpro/ui DataTable) | SA can create tenant, assign subscription, see usage meters |
| 3 | 2 weeks | Services: Customer + Vehicle with DPDP consent (ConsentCheckbox from @vehubpro/ui), Vehicle expiry alerts | Customer created with consent. PII encrypted in DB. Masking works. |
| 4 | 2 weeks | Services Master (categories + items seeded per vehicle type), Job Card create + Kanban | Job card created with live GST calculation using @vehubpro/utils. State machine enforced. |
| 5 | 2 weeks | Invoice generation (ReportLab PDF → S3), WhatsApp delivery, payment recording | Invoice INV/25-26/000001 generated. PDF in S3 (private). WhatsApp send working. |
| 6 | 2 weeks | Portfolio: Inventory Vehicle (all types), multi-image upload to S3, presigned URL response | Vehicle listed. Images served via presigned URL (15min TTL). |
| 7 | 2 weeks | Public Portfolio page (web-public app), Test Drive booking with OTP | Public URL live at vehubpro.com/portfolio/:slug. Booking creates lead. |
| 8 | 2 weeks | Analytics dashboards (services + portfolio using Recharts), Subscription History UI | Charts render with real DB data. Usage meters update correctly. |
| 9 | 2 weeks | DPDP compliance endpoints, Rate limiting, Security headers, MFA for Owner + SuperAdmin | Erasure request works. Rate limit 429. MFA enforced. Deploy check passes. |
| 10 | 2 weeks | Full test suite (80% coverage), Audit log review, shared-types validation with backend contracts | All critical tests pass. No PII in plaintext in logs. |
| 11 | 2 weeks | Production deploy (Render/EB + Vercel + RDS + ElastiCache), CI/CD pipeline, UAT | UAT sign-off. Zero PII in plaintext in DB. apps/mobile scaffold resolves monorepo packages. |

---

## 📱 FUTURE PHASE — Mobile App (React Native)

When ready to build the mobile app, the monorepo is already prepared:

```
# The mobile app is at apps/mobile/ and already has:
# - @vehubpro/api-client installed (works in React Native via Axios)
# - @vehubpro/shared-types installed (all TypeScript interfaces ready)
# - @vehubpro/utils installed (FY, date, mask, validation helpers)
# - @vehubpro/constants installed (roles, vehicle types, statuses)
# - metro.config.js configured to resolve packages/* from monorepo root
# 
# To start building mobile:
cd apps/mobile && npx expo start
# All API calls, types, and utilities are already shared from packages/
# No code duplication — same business logic as web
```

**Mobile app will cover (when built):**
- Tenant staff app: View assigned job cards, update status, add notes
- Customer notifications: Job card status updates, invoice ready, vehicle expiry alerts
- Portfolio app: Browse available vehicles, book test drives
- Technician: View job card details, add service completion notes

---

*VeHubPro Cursor Development Plan v2.0.0 — Monorepo: Turborepo + pnpm · Web: React.js · Mobile-Ready: React Native scaffold · Backend: Django + PostgreSQL + AWS S3 · Compliance: DPDP 2023 · GDPR · ISO 27001*

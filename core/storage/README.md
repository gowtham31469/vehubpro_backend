# Media storage utilities

Configurable **LOCAL** filesystem or **S3** for user-uploaded files.

## Environment

| Variable | Purpose |
|----------|---------|
| `STORAGE_TYPE` | `LOCAL` (default) or `S3` |
| `BASE_URL` | Origin used to build public URLs for local files (`BASE_URL` + `MEDIA_URL` + stored path) |
| `MEDIA_URL` | URL prefix (default `/media/`) |
| `MEDIA_ROOT` | Absolute path for local storage (default `<backend>/media`) |
| `BRANDING_MAX_UPLOAD_BYTES` | Max branding file size (default 2 MiB) |
| `AWS_*` | Required when `STORAGE_TYPE=S3` |
| `AWS_S3_PRESIGN_EXPIRES_SECONDS` | Pre-signed GET lifetime (default 3600) |

## API

- **`upload_branding_asset(file, tenant_id=..., asset_kind=...)`** — validates png/jpg/jpeg/ico, stores under `tenant_branding/<tenant_id>/<kind>/<uuid>.<ext>`, returns DB value.
- **`upload_media_file(file, relative_key=...)`** — same backends, no branding validation; supply your own key layout.
- **`resolve_media_url(stored_reference)`** — full URL (local) or pre-signed URL (S3).
- **`delete_stored_media(stored_reference)`** — best-effort delete when replacing assets.

## Tenant branding

`TenantBrandingSerializer` accepts `logo_file`, `dark_logo_file`, `favicon_file` (multipart). Responses include stored keys in `logo` / `dark_logo` / `favicon` and resolved `logo_url` / `dark_logo_url` / `favicon_url`.

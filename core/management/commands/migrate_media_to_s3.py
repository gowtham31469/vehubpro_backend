"""
One-off ops command: copy every file under MEDIA_ROOT to the configured S3
bucket, preserving its relative path as the object key — the same key layout
``save_upload_local``/``upload_to_s3`` already use, so DB-stored references
(pdf_key, logo, etc.) resolve correctly against either backend without any
data migration. Run this BEFORE flipping STORAGE_TYPE=S3 live, so the bucket
is fully populated first; local files are left in place (not deleted) so the
cutover can be verified before any cleanup.

Usage:
    python manage.py migrate_media_to_s3                  # upload everything, skip files already in S3
    python manage.py migrate_media_to_s3 --dry-run         # preview only, no uploads
    python manage.py migrate_media_to_s3 --overwrite       # re-upload even if already present in S3
    python manage.py migrate_media_to_s3 --prefix invoice_pdfs/   # only this subfolder

Requires AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_STORAGE_BUCKET_NAME /
AWS_REGION to be set (same env vars core.storage.s3_backend reads) regardless
of the current STORAGE_TYPE value.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.storage.exceptions import StorageConfigError, StorageUploadError
from core.storage.s3_backend import _client, upload_to_s3

# Never migrate OS/editor junk that sometimes ends up under MEDIA_ROOT.
_SKIP_NAMES = {".DS_Store", "Thumbs.db"}


class Command(BaseCommand):
    help = "Copy every file under MEDIA_ROOT to the configured S3 bucket, preserving relative paths as object keys."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="List what would be uploaded without actually uploading anything.",
        )
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Re-upload even if an object with the same key already exists in S3 (default: skip it).",
        )
        parser.add_argument(
            "--prefix", default="",
            help="Only migrate files under this relative subfolder, e.g. invoice_pdfs/",
        )

    def handle(self, *args, **options):
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or ""
        if not bucket:
            raise CommandError(
                "AWS_STORAGE_BUCKET_NAME is not set. Export the AWS_* env vars before running this command, "
                "even if STORAGE_TYPE is still LOCAL — this command migrates to S3 ahead of cutover."
            )

        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_dir():
            raise CommandError(f"MEDIA_ROOT does not exist: {media_root}")

        prefix = options["prefix"].strip().lstrip("/")
        scan_root = (media_root / prefix) if prefix else media_root
        if not scan_root.is_dir():
            raise CommandError(f"--prefix folder does not exist: {scan_root}")

        dry_run = options["dry_run"]
        overwrite = options["overwrite"]

        files = sorted(p for p in scan_root.rglob("*") if p.is_file() and p.name not in _SKIP_NAMES)
        if not files:
            self.stdout.write(self.style.WARNING(f"No files found under {scan_root}."))
            return

        self.stdout.write(f"Found {len(files)} file(s) under {scan_root}.")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no files will be uploaded."))

        client = _client() if not dry_run else None

        uploaded = skipped = failed = 0
        total_bytes = 0
        failures: list[tuple[str, str]] = []

        for path in files:
            relative_key = path.relative_to(media_root).as_posix()
            size = path.stat().st_size

            if not overwrite and client is not None:
                try:
                    client.head_object(Bucket=bucket, Key=relative_key)
                    skipped += 1
                    self.stdout.write(f"  skip (already in S3): {relative_key}")
                    continue
                except Exception:
                    pass  # not found (or transient) — proceed to upload

            if dry_run:
                self.stdout.write(f"  would upload: {relative_key} ({size} bytes)")
                uploaded += 1
                total_bytes += size
                continue

            content_type, _ = mimetypes.guess_type(path.name)
            try:
                with path.open("rb") as fh:
                    upload_to_s3(fh, relative_key, content_type)
                uploaded += 1
                total_bytes += size
                self.stdout.write(f"  uploaded: {relative_key} ({size} bytes)")
            except (StorageUploadError, StorageConfigError, OSError) as exc:
                failed += 1
                failures.append((relative_key, str(exc)))
                self.stdout.write(self.style.ERROR(f"  FAILED: {relative_key} — {exc}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Done. uploaded={uploaded} skipped={skipped} failed={failed} "
            f"({total_bytes / (1024 * 1024):.1f} MiB {'would be ' if dry_run else ''}transferred)."
        ))
        if failures:
            self.stdout.write(self.style.ERROR(f"\n{len(failures)} file(s) failed:"))
            for key, err in failures:
                self.stdout.write(f"  - {key}: {err}")
            raise CommandError(f"{len(failures)} file(s) failed to upload — see above. Re-run to retry (already-uploaded files will be skipped).")

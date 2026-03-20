from django.core.management.base import BaseCommand

from apps.platform.users.models import UserPII


class Command(BaseCommand):
    help = "Rotate encrypted PII fields to the active key version."

    def handle(self, *args, **options):
        count = 0
        for record in UserPII.objects.all().iterator():
            before = (
                record.email_key_version,
                record.phone_key_version,
                record.full_name_key_version,
            )
            record.rotate_keys()
            after = (
                record.email_key_version,
                record.phone_key_version,
                record.full_name_key_version,
            )
            if before != after:
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Rotated keys for {count} user PII record(s)."))

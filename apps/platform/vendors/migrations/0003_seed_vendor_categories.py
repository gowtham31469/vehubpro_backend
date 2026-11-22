from django.db import migrations

# Seeds the starting vendor categories (the previous fixed enum's options)
# for every existing tenant, and rewrites any existing Vendor rows from the
# old lowercase enum keys to the new human-readable names those keys used to
# display as. Tenant-curated from here on (like credit_notes.
# CreditNoteReasonCategory) — tenants can rename, reorder, add to, or archive
# these; this migration only gives each tenant the same starting point.
OLD_KEY_TO_NAME = {
    "parts_supplier": "Parts Supplier",
    "service_provider": "Service Provider",
    "contractor": "Contractor",
    "consultant": "Consultant",
    "utility": "Utility",
    "other": "Other",
}
SEED_NAMES = list(OLD_KEY_TO_NAME.values())


def seed_vendor_categories(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    VendorCategory = apps.get_model("vendors", "VendorCategory")
    Vendor = apps.get_model("vendors", "Vendor")

    for tenant in Tenant.objects.all():
        existing_names = set(
            VendorCategory.objects.filter(tenant=tenant, is_archived=False)
            .values_list("name", flat=True)
        )
        for position, name in enumerate(SEED_NAMES, start=1):
            if name in existing_names:
                continue
            VendorCategory.objects.create(tenant=tenant, name=name, sort_order=position * 10)

        for old_key, name in OLD_KEY_TO_NAME.items():
            Vendor.objects.filter(tenant=tenant, category=old_key).update(category=name)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0002_alter_vendor_category_vendorcategory"),
    ]

    operations = [
        migrations.RunPython(seed_vendor_categories, noop_reverse),
    ]

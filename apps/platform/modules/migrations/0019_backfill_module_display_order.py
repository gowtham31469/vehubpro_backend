from django.db import migrations


def backfill_display_order(apps, schema_editor):
    Module = apps.get_model("modules", "Module")

    # No explicit order existed before this field — preserve the current
    # (id-ordered) relative order exactly, so nothing changes on screen
    # from this migration alone.
    modules = list(Module.objects.order_by("id"))
    for position, module in enumerate(modules, start=1):
        module.display_order = position * 10
        module.save(update_fields=["display_order"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0018_alter_module_options_module_display_order"),
    ]

    operations = [
        migrations.RunPython(backfill_display_order, noop_reverse),
    ]

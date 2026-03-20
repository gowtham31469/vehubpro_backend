from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="last_consent_at",
        ),
        migrations.RemoveField(
            model_name="user",
            name="mfa_enabled",
        ),
        migrations.RemoveField(
            model_name="user",
            name="password_changed_at",
        ),
        migrations.RemoveField(
            model_name="user",
            name="privacy_policy_version",
        ),
        migrations.RemoveField(
            model_name="user",
            name="terms_version",
        ),
        migrations.AlterField(
            model_name="user",
            name="status",
            field=models.CharField(
                choices=[("active", "Active"), ("inactive", "Inactive")],
                default="active",
                max_length=20,
            ),
        ),
    ]

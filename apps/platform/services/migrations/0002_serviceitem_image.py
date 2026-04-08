from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("services", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="serviceitem",
            name="image",
            field=models.CharField(
                blank=True,
                max_length=512,
                null=True,
                help_text="Relative storage key (LOCAL path or S3 object key) for the service item icon/image.",
            ),
        ),
    ]

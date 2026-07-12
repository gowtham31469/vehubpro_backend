# Generated migration for adding next_service_recommendation field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobcards', '0005_update_status_flow'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobcard',
            name='next_service_recommendation',
            field=models.TextField(
                blank=True,
                help_text='Recommended next service details; set when status changes to Job Completed.',
                null=True,
            ),
        ),
    ]

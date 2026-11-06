from django.db import migrations


def backfill_initial_status_events(apps, schema_editor):
    """
    Seed one timeline entry per pre-existing job card (from_status=None,
    to_status=<its current status>), stamped at the job card's own created_at.
    This is NOT reconstructed history — job cards created before this feature
    shipped have no record of intermediate status transitions, only their
    current status — so the backfilled entry represents "status as of
    creation" for display purposes, not an accurate change log.
    """
    JobCard = apps.get_model("jobcards", "JobCard")
    JobCardStatusEvent = apps.get_model("jobcards", "JobCardStatusEvent")

    for jc in JobCard.objects.all().only("id", "status", "created_at"):
        event = JobCardStatusEvent.objects.create(
            job_card_id=jc.id,
            from_status=None,
            to_status=jc.status,
            changed_by=None,
        )
        JobCardStatusEvent.objects.filter(pk=event.pk).update(created_at=jc.created_at)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("jobcards", "0013_jobcardstatusevent"),
    ]

    operations = [
        migrations.RunPython(backfill_initial_status_events, noop_reverse),
    ]

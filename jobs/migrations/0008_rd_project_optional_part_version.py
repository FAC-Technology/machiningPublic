from django.db import migrations, models

RD_PROJECT_NAME = "R&D"


def seed_rd_project(apps, schema_editor):
    Project = apps.get_model("jobs", "Project")
    Project.objects.get_or_create(name=RD_PROJECT_NAME, defaults={"is_active": True})


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0007_coverping"),
    ]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="part_version",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.RunPython(seed_rd_project, migrations.RunPython.noop),
    ]

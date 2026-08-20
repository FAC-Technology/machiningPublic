from django.db import migrations, models


DEFAULT_DESTINATIONS = ("Unit 1", "Unit 2", "Unit 4")


def seed_destinations(apps, schema_editor):
    Destination = apps.get_model("jobs", "Destination")
    for name in DEFAULT_DESTINATIONS:
        Destination.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0004_optional_notes_longer_folder_path"),
    ]

    operations = [
        migrations.CreateModel(
            name="Destination",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.RunPython(seed_destinations, migrations.RunPython.noop),
    ]

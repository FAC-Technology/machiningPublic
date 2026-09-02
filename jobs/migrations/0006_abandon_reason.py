from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0005_destination"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="abandon_reason",
            field=models.TextField(blank=True),
        ),
    ]

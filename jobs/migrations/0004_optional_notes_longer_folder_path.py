from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0003_project"),
    ]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="job",
            name="folder_path",
            field=models.CharField(blank=True, max_length=1000),
        ),
    ]

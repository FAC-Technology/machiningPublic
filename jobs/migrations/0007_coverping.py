from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0006_abandon_reason"),
    ]

    operations = [
        migrations.CreateModel(
            name="CoverPing",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField(unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-date"],
            },
        ),
    ]

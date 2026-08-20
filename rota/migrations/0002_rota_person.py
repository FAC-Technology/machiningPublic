import django.db.models.deletion
from django.db import migrations, models


def clear_assignments(apps, schema_editor):
    RotaAssignment = apps.get_model("rota", "RotaAssignment")
    RotaAssignment.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0005_destination"),
        ("rota", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(clear_assignments, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rotaassignment",
            name="machinist",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rota_days",
                to="jobs.person",
            ),
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models


DEFAULT_PROJECTS = ("PRD", "P10", "P05")


def convert_projects(apps, schema_editor):
    Project = apps.get_model("jobs", "Project")
    Job = apps.get_model("jobs", "Job")
    for name in DEFAULT_PROJECTS:
        Project.objects.get_or_create(name=name)
    for job in Job.objects.all():
        name = (job.project_name or "").strip() or "PRD"
        project, _ = Project.objects.get_or_create(name=name)
        job.project_id = project.pk
        job.save(update_fields=["project"])


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0002_alter_job_dxf_filename_alter_job_folder_path_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Project",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.RenameField(
            model_name="job",
            old_name="project",
            new_name="project_name",
        ),
        migrations.AddField(
            model_name="job",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="jobs",
                to="jobs.project",
            ),
        ),
        migrations.RunPython(convert_projects, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="job",
            name="project_name",
        ),
        migrations.AlterField(
            model_name="job",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="jobs",
                to="jobs.project",
            ),
        ),
    ]

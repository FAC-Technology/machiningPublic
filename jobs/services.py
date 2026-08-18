from .models import Job


def find_duplicate_jobs(job_name, project, part_version, exclude_pk=None):
    qs = Job.objects.exclude(status__in=[Job.Status.CANCELLED, Job.Status.ABANDONED])
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return list(
        qs.filter(
            job_name__iexact=job_name.strip(),
            project=project,
            part_version__iexact=part_version.strip(),
        )
    )

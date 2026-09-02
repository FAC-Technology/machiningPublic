from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, IntegerField, When
from django.utils import timezone

RD_PROJECT_NAME = "R&D"


class Person(models.Model):
    name = models.CharField(max_length=120)
    initials = models.CharField(max_length=4, unique=True)
    is_engineer = models.BooleanField(default=False)
    is_machinist = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["initials"]

    def save(self, *args, **kwargs):
        self.initials = (self.initials or "").strip().upper()
        if not (self.name or "").strip():
            self.name = self.initials
        super().save(*args, **kwargs)

    def __str__(self):
        return self.initials

    @property
    def label(self):
        return self.initials

    def role_summary(self):
        roles = []
        if self.is_engineer:
            roles.append("Engineer")
        if self.is_machinist:
            roles.append("Machinist")
        if self.is_admin:
            roles.append("Admin")
        return ", ".join(roles) or "Shop"


class Panel(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Project(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_rd(self):
        return self.name == RD_PROJECT_NAME


class Destination(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class JobQuerySet(models.QuerySet):
    QUEUE_STATUSES = ("queued", "on_hold", "in_progress")
    HISTORY_STATUSES = ("completed", "abandoned", "cancelled")

    def queue(self):
        return self.filter(status__in=self.QUEUE_STATUSES)

    def history(self):
        return self.filter(status__in=self.HISTORY_STATUSES)

    def with_queue_order(self):
        today = timezone.localdate()
        return self.annotate(
            sort_in_progress=Case(
                When(status="in_progress", then=0),
                default=1,
                output_field=IntegerField(),
            ),
            sort_priority=Case(
                When(deadline__lt=today, then=0),
                default="priority",
                output_field=IntegerField(),
            ),
        ).order_by("sort_in_progress", "sort_priority", "deadline", "created_at")


class Job(models.Model):
    class Priority(models.IntegerChoices):
        URGENT = 0, "Urgent"
        HIGH = 1, "High"
        MEDIUM = 2, "Medium"
        LOW = 3, "Low"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        ON_HOLD = "on_hold", "On hold — no material"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        ABANDONED = "abandoned", "Abandoned"
        CANCELLED = "cancelled", "Cancelled"

    job_id = models.CharField(max_length=24, unique=True, editable=False)
    job_label = models.CharField(max_length=240, blank=True)
    job_name = models.CharField("Part number", max_length=200)
    project = models.ForeignKey("Project", on_delete=models.PROTECT, related_name="jobs")
    part_version = models.CharField(max_length=50, blank=True)
    requested_by = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="submitted_jobs",
    )
    submitted_date = models.DateField(default=timezone.localdate)
    priority = models.IntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    quantity = models.PositiveIntegerField(default=1)
    panel = models.ForeignKey(Panel, on_delete=models.PROTECT, related_name="jobs")
    deadline = models.DateField()
    destination = models.CharField(max_length=200)
    notes = models.TextField(blank=True)

    folder_path = models.CharField(max_length=1000, blank=True)
    pdf_filename = models.CharField(max_length=260, blank=True)
    dxf_filename = models.CharField(max_length=260, blank=True)
    vcarve_filename = models.CharField(max_length=260, blank=True)
    pdf_stamp = models.CharField(max_length=80, blank=True)
    dxf_stamp = models.CharField(max_length=80, blank=True)
    vcarve_stamp = models.CharField(max_length=80, blank=True)
    files_confirmed = models.BooleanField(default=False)
    duplicate_acknowledged = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    materials_present = models.BooleanField(default=False)
    cancel_reason = models.TextField(blank=True)
    abandon_reason = models.TextField(blank=True)
    overdue_reason = models.TextField(blank=True)

    machinist_primary = models.ForeignKey(
        Person,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="primary_jobs",
    )
    machinist_secondary = models.ForeignKey(
        Person,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="secondary_jobs",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    panel_used = models.CharField(max_length=120, blank=True)
    machinist_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["priority", "deadline", "created_at"]

    def __str__(self):
        return self.job_label or self.job_id

    def save(self, *args, **kwargs):
        creating = self.pk is None
        if self.requested_by_id:
            self.job_label = self.build_job_label()
        super().save(*args, **kwargs)
        if creating and not self.job_id:
            self.job_id = f"MJ-{self.pk:04d}"
            type(self).objects.filter(pk=self.pk).update(job_id=self.job_id, job_label=self.job_label)
            self.refresh_from_db(fields=["job_id"])

    def build_job_label(self):
        day = (self.submitted_date or timezone.localdate()).strftime("%Y_%m_%d")
        initials = self.requested_by.initials.upper()
        project = _token(self.project.name if self.project_id else "")
        part = _token(self.job_name)
        if self.is_rd:
            return f"{day}_{initials}_{project}-{part}"
        version = _token(self.part_version)
        return f"{day}_{initials}_{project}-{part}-{version}"

    def clean(self):
        super().clean()
        if self.quantity < 1 or self.quantity > 100:
            raise ValidationError({"quantity": "Quantity must be between 1 and 100."})
        if not self.pk and self.deadline and self.deadline < timezone.localdate():
            raise ValidationError({"deadline": "Deadline cannot be before today."})

    @property
    def is_rd(self):
        return bool(self.project_id) and self.project.is_rd

    @property
    def is_overdue(self):
        return self.deadline < timezone.localdate() and self.status in JobQuerySet.QUEUE_STATUSES

    @property
    def can_edit_submission(self):
        return self.started_at is None and self.status in (
            self.Status.QUEUED,
            self.Status.ON_HOLD,
        )

    @property
    def is_open(self):
        return self.status in JobQuerySet.QUEUE_STATUSES

    def effective_priority(self):
        return self.Priority.URGENT if self.is_overdue else self.priority

    @property
    def submitted_files(self):
        return [
            ("pdf", "PDF", self.pdf_filename),
            ("dxf", "DXF", self.dxf_filename),
            ("vcarve", "VCarve", self.vcarve_filename),
        ]


def _token(value):
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value.strip())


class CoverPing(models.Model):
    date = models.DateField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return str(self.date)

import mimetypes

from django.contrib import messages
from django.db.models import ProtectedError, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .files import job_file, write_job_files
from .forms import CancelForm, JobSubmitForm, MachinistUpdateForm, PanelForm, PersonForm, ProjectForm
from .identity import current_person, set_current_person
from .models import Job, Panel, Person, Project

SORT_MAP = {
    "priority": None,
    "deadline": ["deadline", "priority"],
    "submitted": ["-created_at"],
    "name": ["job_name"],
    "status": ["status", "priority"],
}


def _require_person(request):
    person = current_person(request)
    if not person:
        messages.error(request, "Select your initials first (top of the sidebar).")
        return None
    return person


def _filtered_jobs(request, qs):
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    priority = request.GET.get("priority", "").strip()
    sort = request.GET.get("sort", "priority")

    if search:
        qs = qs.filter(
            Q(job_name__icontains=search)
            | Q(project__name__icontains=search)
            | Q(job_id__icontains=search)
            | Q(job_label__icontains=search)
            | Q(requested_by__initials__icontains=search)
            | Q(requested_by__name__icontains=search)
            | Q(panel__name__icontains=search)
            | Q(destination__icontains=search)
        )
    if status:
        qs = qs.filter(status=status)
    if priority != "":
        qs = qs.filter(priority=priority)

    ordering = SORT_MAP.get(sort, SORT_MAP["priority"])
    if ordering is None:
        qs = qs.with_queue_order()
    else:
        qs = qs.order_by(*ordering)
    return qs


def home(request):
    return redirect("jobs:queue")


@require_POST
def choose_person(request):
    pk = request.POST.get("person")
    person = Person.objects.filter(pk=pk, is_active=True).first() if pk else None
    set_current_person(request, person)
    return redirect(request.META.get("HTTP_REFERER") or "jobs:queue")


def submit_page(request, job=None):
    person = current_person(request)
    initial = {}
    if person and person.is_engineer and job is None:
        initial["requested_by"] = person.pk

    form = JobSubmitForm(
        request.POST or None,
        request.FILES or None,
        instance=job,
        initial=initial,
        current_person=person,
    )
    if request.method == "POST":
        actor = _require_person(request)
        if actor and form.is_valid():
            if job and not job.can_edit_submission:
                messages.error(request, "This job has already been started, so it cannot be edited. Cancel it and submit a new version instead.")
                return redirect("jobs:detail", job_id=job.job_id)
            saved = form.save()
            if any(form.uploads.values()):
                write_job_files(saved, form.uploads)
                saved.save()
            verb = "updated" if job else "added to the queue"
            messages.success(request, f"{saved.job_label} {verb} as {saved.job_id}.")
            return redirect("jobs:queue")

    return render(
        request,
        "jobs/submit.html",
        {
            "form": form,
            "editing": job,
            "duplicates": getattr(form, "duplicates", []),
        },
    )


def edit_job(request, job_id):
    job = get_object_or_404(Job, job_id=job_id)
    if not job.can_edit_submission:
        messages.error(request, "Editing is only allowed until a machinist starts the job.")
        return redirect("jobs:detail", job_id=job.job_id)
    return submit_page(request, job=job)


def queue_page(request):
    jobs = _filtered_jobs(
        request,
        Job.objects.queue().select_related(
            "requested_by", "panel", "machinist_primary", "machinist_secondary"
        ),
    )
    return render(
        request,
        "jobs/queue.html",
        {
            "jobs": jobs,
            "status_choices": [
                (Job.Status.QUEUED, "Queued"),
                (Job.Status.ON_HOLD, "On hold"),
                (Job.Status.IN_PROGRESS, "In progress"),
            ],
            "priority_choices": Job.Priority.choices,
            "history": False,
        },
    )


def history_page(request):
    jobs = _filtered_jobs(
        request,
        Job.objects.history().select_related(
            "requested_by", "panel", "machinist_primary", "machinist_secondary"
        ),
    )
    if request.GET.get("sort", "priority") == "priority":
        jobs = jobs.order_by("-finished_at", "-updated_at")
    return render(
        request,
        "jobs/queue.html",
        {
            "jobs": jobs,
            "status_choices": [
                (Job.Status.COMPLETED, "Completed"),
                (Job.Status.ABANDONED, "Abandoned"),
                (Job.Status.CANCELLED, "Cancelled"),
            ],
            "priority_choices": Job.Priority.choices,
            "history": True,
        },
    )


def job_detail(request, job_id):
    job = get_object_or_404(
        Job.objects.select_related(
            "requested_by", "panel", "machinist_primary", "machinist_secondary"
        ),
        job_id=job_id,
    )
    return render(
        request,
        "jobs/detail.html",
        {
            "job": job,
            "update_form": MachinistUpdateForm(instance=job),
            "cancel_form": CancelForm(),
        },
    )


@require_POST
def update_job(request, job_id):
    actor = _require_person(request)
    if not actor:
        return redirect("jobs:detail", job_id=job_id)

    job = get_object_or_404(Job, job_id=job_id)
    action = request.POST.get("action")

    if action == "cancel":
        form = CancelForm(request.POST)
        if not job.can_edit_submission:
            messages.error(request, "Once machining has started, withdraw the job as abandoned instead of cancelling.")
            return redirect("jobs:detail", job_id=job.job_id)
        if form.is_valid():
            job.status = Job.Status.CANCELLED
            job.cancel_reason = form.cleaned_data["cancel_reason"]
            job.finished_at = timezone.now()
            job.save()
            messages.success(request, f"{job.job_id} cancelled and moved to history.")
            return redirect("jobs:history")
        messages.error(request, "Give a reason to cancel the job.")
        return redirect("jobs:detail", job_id=job.job_id)

    form = MachinistUpdateForm(request.POST, instance=job)
    detail_fields = {"machinist_notes", "panel_used", "machinist_primary", "machinist_secondary", "overdue_reason", "materials_present"}
    if detail_fields & set(request.POST.keys()):
        if form.is_valid():
            job = form.save(commit=False)

    if job.is_overdue and not (job.overdue_reason or "").strip() and action in {"start", "complete", "hold"}:
        messages.error(request, "This job missed its deadline. Add an overdue reason before continuing.")
        return redirect("jobs:detail", job_id=job.job_id)

    if action == "start":
        if not job.materials_present:
            job.status = Job.Status.ON_HOLD
            job.save()
            messages.error(request, "Material is not marked as in stock, so the job is on hold.")
            return redirect("jobs:detail", job_id=job.job_id)
        if actor.is_machinist:
            if not job.machinist_primary:
                job.machinist_primary = actor
            elif job.machinist_primary_id != actor.id and not job.machinist_secondary:
                job.machinist_secondary = actor
        job.status = Job.Status.IN_PROGRESS
        job.started_at = job.started_at or timezone.now()
        job.finished_at = None
    elif action == "complete":
        if job.status == Job.Status.ABANDONED:
            messages.error(request, "Abandoned jobs cannot be restarted. Submit a new job.")
            return redirect("jobs:detail", job_id=job.job_id)
        job.status = Job.Status.COMPLETED
        job.started_at = job.started_at or timezone.now()
        job.finished_at = timezone.now()
    elif action == "abandon":
        job.status = Job.Status.ABANDONED
        job.finished_at = timezone.now()
        if not (job.machinist_notes or "").strip():
            messages.error(request, "Add a note explaining why the job was abandoned.")
            return redirect("jobs:detail", job_id=job.job_id)
    elif action == "hold":
        job.status = Job.Status.ON_HOLD
        job.materials_present = False
    elif action == "save":
        if job.materials_present and job.status == Job.Status.ON_HOLD and not job.started_at:
            job.status = Job.Status.QUEUED
        elif not job.materials_present and job.status == Job.Status.QUEUED:
            job.status = Job.Status.ON_HOLD

    job.save()
    messages.success(request, f"{job.job_id} updated.")
    if job.status in (Job.Status.COMPLETED, Job.Status.ABANDONED, Job.Status.CANCELLED):
        return redirect("jobs:history")
    return redirect(request.POST.get("next") or "jobs:queue")


def job_file_view(request, job_id, kind):
    job = get_object_or_404(Job, job_id=job_id)
    try:
        path = job_file(job, kind)
    except Exception as exc:
        messages.error(request, str(exc))
        return redirect("jobs:detail", job_id=job.job_id)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path.open("rb"), content_type=content_type, filename=path.name)


def setup_page(request):
    person_form = PersonForm(prefix="person")
    panel_form = PanelForm(prefix="panel")
    project_form = ProjectForm(prefix="project")
    if request.method == "POST":
        if "add_person" in request.POST:
            person_form = PersonForm(request.POST, prefix="person")
            if person_form.is_valid():
                person_form.save()
                messages.success(request, "Person added.")
                return redirect("jobs:setup")
        elif "add_panel" in request.POST:
            panel_form = PanelForm(request.POST, prefix="panel")
            if panel_form.is_valid():
                panel_form.save()
                messages.success(request, "Panel added.")
                return redirect("jobs:setup")
        elif "add_project" in request.POST:
            project_form = ProjectForm(request.POST, prefix="project")
            if project_form.is_valid():
                project_form.save()
                messages.success(request, "Project added.")
                return redirect("jobs:setup")
    return render(
        request,
        "jobs/setup.html",
        {
            "person_form": person_form,
            "panel_form": panel_form,
            "project_form": project_form,
            "people": Person.objects.all(),
            "panels": Panel.objects.all(),
            "projects": Project.objects.all(),
        },
    )


@require_POST
def toggle_person(request, pk):
    person = get_object_or_404(Person, pk=pk)
    person.is_active = not person.is_active
    person.save(update_fields=["is_active"])
    return redirect("jobs:setup")


@require_POST
def toggle_panel(request, pk):
    panel = get_object_or_404(Panel, pk=pk)
    panel.is_active = not panel.is_active
    panel.save(update_fields=["is_active"])
    return redirect("jobs:setup")


@require_POST
def toggle_project(request, pk):
    project = get_object_or_404(Project, pk=pk)
    project.is_active = not project.is_active
    project.save(update_fields=["is_active"])
    return redirect("jobs:setup")


@require_POST
def delete_panel(request, pk):
    panel = get_object_or_404(Panel, pk=pk)
    name = panel.name
    try:
        panel.delete()
        messages.success(request, f"Deleted panel {name}.")
    except ProtectedError:
        count = panel.jobs.count()
        messages.error(
            request,
            f"Can't delete {name} — {count} job(s) still use it. Hide it instead, or change those jobs first.",
        )
    return redirect("jobs:setup")


@require_POST
def delete_project(request, pk):
    project = get_object_or_404(Project, pk=pk)
    name = project.name
    try:
        project.delete()
        messages.success(request, f"Deleted project {name}.")
    except ProtectedError:
        count = project.jobs.count()
        messages.error(
            request,
            f"Can't delete {name} — {count} job(s) still use it. Hide it instead, or change those jobs first.",
        )
    return redirect("jobs:setup")

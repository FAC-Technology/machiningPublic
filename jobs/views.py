import mimetypes

from django.contrib import messages
from django.db.models import ProtectedError, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .files import job_file, write_job_files
from .forms import (
    CancelForm,
    DestinationForm,
    JobSubmitForm,
    MachinistUpdateForm,
    PanelForm,
    PersonForm,
    ProjectForm,
)
from .google_chat import (
    job_is_in_top_queue,
    notify_job_abandoned,
    notify_job_cancelled,
    notify_job_edited,
    notify_job_started,
)
from .identity import current_person, set_current_person
from .models import Destination, Job, Panel, Person, Project

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


def _require_admin(request):
    person = _require_person(request)
    if not person:
        return None
    if not person.is_admin:
        messages.error(request, "Only an admin can change people, panels, and projects.")
        return None
    return person


def _last_active_admin(person):
    if not (person.is_admin and person.is_active):
        return False
    return not Person.objects.filter(is_admin=True, is_active=True).exclude(pk=person.pk).exists()


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
    form = JobSubmitForm(
        request.POST or None,
        request.FILES or None,
        instance=job,
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
            if job:
                notify_job_edited(saved)
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
            "cancel_form": CancelForm() if job else None,
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
            "requested_by", "panel", "machinist_primary", "machinist_secondary", "project"
        ),
        job_id=job_id,
    )
    return render(
        request,
        "jobs/detail.html",
        {
            "job": job,
            "update_form": MachinistUpdateForm(instance=job),
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
        if not actor.is_engineer:
            messages.error(request, "Only an engineer can cancel a job.")
            return redirect("jobs:detail", job_id=job.job_id)
        form = CancelForm(request.POST)
        if not job.can_edit_submission:
            messages.error(request, "Once machining has started, withdraw the job as abandoned instead of cancelling.")
            return redirect("jobs:detail", job_id=job.job_id)
        if form.is_valid():
            in_top = job_is_in_top_queue(job)
            job.status = Job.Status.CANCELLED
            job.cancel_reason = form.cleaned_data["cancel_reason"]
            job.finished_at = timezone.now()
            job.save()
            if in_top:
                notify_job_cancelled(job, actor)
            messages.success(request, f"{job.job_id} cancelled and moved to history.")
            return redirect("jobs:history")
        messages.error(request, "Give a reason to cancel the job.")
        return redirect("jobs:edit", job_id=job.job_id)

    from_job_page = "panel_used" in request.POST
    if from_job_page:
        form = MachinistUpdateForm(request.POST, instance=job)
        if not form.is_valid():
            messages.error(request, "Check the machinist field and try again.")
            return render(
                request,
                "jobs/detail.html",
                {
                    "job": job,
                    "update_form": form,
                },
            )
        job = form.save(commit=False)
    elif "machinist_choice" in request.POST:
        person, error = MachinistUpdateForm.person_from_choice(
            request.POST.get("machinist_choice"),
            request.POST.get("machinist_other"),
        )
        if error:
            messages.error(request, error)
            if request.POST.get("next"):
                return redirect(request.POST.get("next"))
            return redirect("jobs:detail", job_id=job.job_id)
        if person:
            job.machinist_primary = person
            job.machinist_secondary = None

    if job.is_overdue and not (job.overdue_reason or "").strip() and action in {"start", "complete"}:
        messages.error(request, "This job missed its deadline. Add an overdue reason before continuing.")
        return redirect("jobs:detail", job_id=job.job_id)

    if action == "start":
        if not job.machinist_primary:
            messages.error(request, "Select a machinist before starting.")
            if request.POST.get("next"):
                return redirect(request.POST.get("next"))
            return redirect("jobs:detail", job_id=job.job_id)
        job.status = Job.Status.IN_PROGRESS
        job.started_at = job.started_at or timezone.now()
        job.finished_at = None
    elif action == "complete":
        if not job.started_at:
            messages.error(request, "Start machining before completing the job.")
            return redirect("jobs:detail", job_id=job.job_id)
        if job.status == Job.Status.ABANDONED:
            messages.error(request, "Abandoned jobs cannot be restarted. Submit a new job.")
            return redirect("jobs:detail", job_id=job.job_id)
        job.status = Job.Status.COMPLETED
        job.started_at = job.started_at or timezone.now()
        job.finished_at = timezone.now()
    elif action == "abandon":
        if not job.started_at:
            messages.error(request, "Start machining before abandoning the job.")
            return redirect("jobs:detail", job_id=job.job_id)
        reason = (request.POST.get("abandon_reason") or "").strip()
        if not reason:
            messages.error(request, "Give a reason to abandon the job.")
            return redirect("jobs:detail", job_id=job.job_id)
        job.status = Job.Status.ABANDONED
        job.abandon_reason = reason
        job.finished_at = timezone.now()

    job.save()
    if action == "start":
        notify_job_started(job)
    elif action == "abandon":
        notify_job_abandoned(job, actor)
    messages.success(request, f"{job.job_id} updated.")
    if job.status in (Job.Status.COMPLETED, Job.Status.ABANDONED, Job.Status.CANCELLED):
        return redirect("jobs:history")
    if request.POST.get("next"):
        return redirect(request.POST.get("next"))
    return redirect("jobs:detail", job_id=job.job_id)


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
    if not _require_admin(request):
        return redirect("jobs:queue")
    editing_person = None
    edit_pk = request.POST.get("person_pk") or request.GET.get("edit_person")
    if edit_pk:
        editing_person = Person.objects.filter(pk=edit_pk).first()
    person_form = PersonForm(prefix="person", instance=editing_person)
    panel_form = PanelForm(prefix="panel")
    project_form = ProjectForm(prefix="project")
    destination_form = DestinationForm(prefix="destination")
    if request.method == "POST":
        if "add_person" in request.POST:
            person_form = PersonForm(request.POST, prefix="person")
            editing_person = None
            if person_form.is_valid():
                person_form.save()
                messages.success(request, "Person added.")
                return redirect("jobs:setup")
        elif "save_person" in request.POST:
            if not editing_person:
                messages.error(request, "Choose someone to edit.")
                return redirect("jobs:setup")
            person_form = PersonForm(request.POST, prefix="person", instance=editing_person)
            if person_form.is_valid():
                if _last_active_admin(editing_person) and not person_form.cleaned_data.get("is_admin"):
                    person_form.add_error("is_admin", "Keep at least one active admin.")
                else:
                    person_form.save()
                    messages.success(request, "Person updated.")
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
        elif "add_destination" in request.POST:
            destination_form = DestinationForm(request.POST, prefix="destination")
            if destination_form.is_valid():
                destination_form.save()
                messages.success(request, "Destination added.")
                return redirect("jobs:setup")
    return render(
        request,
        "jobs/setup.html",
        {
            "person_form": person_form,
            "panel_form": panel_form,
            "project_form": project_form,
            "destination_form": destination_form,
            "editing_person": editing_person,
            "people": Person.objects.all(),
            "panels": Panel.objects.all(),
            "projects": Project.objects.all(),
            "destinations": Destination.objects.all(),
        },
    )


@require_POST
def toggle_person(request, pk):
    if not _require_admin(request):
        return redirect("jobs:queue")
    person = get_object_or_404(Person, pk=pk)
    if person.is_active and _last_active_admin(person):
        messages.error(request, "Keep at least one active admin.")
        return redirect("jobs:setup")
    person.is_active = not person.is_active
    person.save(update_fields=["is_active"])
    return redirect("jobs:setup")


@require_POST
def delete_person(request, pk):
    if not _require_admin(request):
        return redirect("jobs:queue")
    person = get_object_or_404(Person, pk=pk)
    actor = current_person(request)
    if actor and actor.pk == person.pk:
        messages.error(request, "You can't delete the person you are working as.")
        return redirect("jobs:setup")
    if _last_active_admin(person):
        messages.error(request, "Keep at least one active admin.")
        return redirect("jobs:setup")
    initials = person.initials
    try:
        person.delete()
        messages.success(request, f"Deleted {initials}.")
    except ProtectedError:
        count = person.submitted_jobs.count()
        messages.error(
            request,
            f"Can't delete {initials} — {count} job(s) still use them. Deactivate them instead.",
        )
    return redirect("jobs:setup")


@require_POST
def toggle_panel(request, pk):
    if not _require_admin(request):
        return redirect("jobs:queue")
    panel = get_object_or_404(Panel, pk=pk)
    panel.is_active = not panel.is_active
    panel.save(update_fields=["is_active"])
    return redirect("jobs:setup")


@require_POST
def toggle_project(request, pk):
    if not _require_admin(request):
        return redirect("jobs:queue")
    project = get_object_or_404(Project, pk=pk)
    project.is_active = not project.is_active
    project.save(update_fields=["is_active"])
    return redirect("jobs:setup")


@require_POST
def delete_panel(request, pk):
    if not _require_admin(request):
        return redirect("jobs:queue")
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
    if not _require_admin(request):
        return redirect("jobs:queue")
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


@require_POST
def toggle_destination(request, pk):
    if not _require_admin(request):
        return redirect("jobs:queue")
    destination = get_object_or_404(Destination, pk=pk)
    destination.is_active = not destination.is_active
    destination.save(update_fields=["is_active"])
    return redirect("jobs:setup")


@require_POST
def delete_destination(request, pk):
    if not _require_admin(request):
        return redirect("jobs:queue")
    destination = get_object_or_404(Destination, pk=pk)
    name = destination.name
    count = Job.objects.filter(destination=name).count()
    if count:
        messages.error(
            request,
            f"Can't delete {name} — {count} job(s) still use it. Hide it instead, or change those jobs first.",
        )
        return redirect("jobs:setup")
    destination.delete()
    messages.success(request, f"Deleted destination {name}.")
    return redirect("jobs:setup")

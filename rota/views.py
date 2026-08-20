from datetime import datetime, timedelta

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from jobs.identity import current_person
from jobs.models import Person

from .models import (
    SLOT_PRIMARY,
    SLOT_SECONDARY,
    RotaAssignment,
    cover_for_date,
    rota_days_for_week,
    week_start,
)


def _parse_week(value):
    if not value:
        return week_start()
    return week_start(datetime.strptime(value, "%Y-%m-%d").date())


def _can_edit(request):
    person = current_person(request)
    return bool(person and person.is_admin)


def _week_grid(start):
    days = rota_days_for_week(start)
    assignments = RotaAssignment.objects.filter(date__in=days).select_related("machinist")
    by_day = {day: {SLOT_PRIMARY: None, SLOT_SECONDARY: None} for day in days}
    notes = {day: "" for day in days}
    for item in assignments:
        by_day[item.date][item.slot] = item.machinist
        if item.notes:
            notes[item.date] = item.notes
    return [
        {
            "date": day,
            "primary": by_day[day][SLOT_PRIMARY],
            "secondary": by_day[day][SLOT_SECONDARY],
            "notes": notes[day],
        }
        for day in days
    ]


def rota_week(request):
    start = _parse_week(request.GET.get("week"))
    machinists = Person.objects.filter(is_active=True, is_machinist=True)
    today = timezone.localdate()
    primary, secondary = cover_for_date(today)
    todays = [person for person in (primary, secondary) if person]
    return render(
        request,
        "rota/week.html",
        {
            "week_start": start,
            "prev_week": start - timedelta(days=7),
            "next_week": start + timedelta(days=7),
            "grid": _week_grid(start),
            "machinists": machinists,
            "can_edit": _can_edit(request),
            "today": today,
            "todays_cover": todays,
        },
    )


@require_POST
def save_rota(request):
    if not _can_edit(request):
        messages.error(request, "Only an admin can change the rota.")
        return redirect("rota:week")

    start = _parse_week(request.POST.get("week"))
    for day in rota_days_for_week(start):
        key = day.isoformat()
        notes = request.POST.get(f"notes-{key}", "").strip()
        primary_id = request.POST.get(f"slot-{key}-{SLOT_PRIMARY}", "").strip()
        secondary_id = request.POST.get(f"slot-{key}-{SLOT_SECONDARY}", "").strip()
        if primary_id and primary_id == secondary_id:
            messages.error(request, f"Primary and secondary for {day.strftime('%A')} must be different people.")
            return redirect(f"{reverse('rota:week')}?week={start.isoformat()}")
        for slot, person_id in ((SLOT_PRIMARY, primary_id), (SLOT_SECONDARY, secondary_id)):
            existing = RotaAssignment.objects.filter(date=day, slot=slot).first()
            if not person_id:
                if existing:
                    existing.delete()
                continue
            RotaAssignment.objects.update_or_create(
                date=day,
                slot=slot,
                defaults={"machinist_id": person_id, "notes": notes},
            )
    messages.success(request, "Rota updated.")
    return redirect(f"{reverse('rota:week')}?week={start.isoformat()}")


@require_POST
def suggest_rota(request):
    if not _can_edit(request):
        messages.error(request, "Only an admin can change the rota.")
        return redirect("rota:week")

    start = _parse_week(request.POST.get("week"))
    people = list(Person.objects.filter(is_active=True, is_machinist=True))
    if len(people) < 2:
        messages.error(request, "Need at least two machinists to fill a two-person rota.")
        return redirect(f"{reverse('rota:week')}?week={start.isoformat()}")

    for index, day in enumerate(rota_days_for_week(start)):
        first = people[index % len(people)]
        second = people[(index + 1) % len(people)]
        RotaAssignment.objects.update_or_create(
            date=day, slot=SLOT_PRIMARY, defaults={"machinist": first, "notes": ""}
        )
        RotaAssignment.objects.update_or_create(
            date=day, slot=SLOT_SECONDARY, defaults={"machinist": second, "notes": ""}
        )
    messages.success(request, "Filled this week with a rotating two-person cover.")
    return redirect(f"{reverse('rota:week')}?week={start.isoformat()}")

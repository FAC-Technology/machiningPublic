from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import RotaAssignment, rota_days_for_week, week_start

User = get_user_model()


def _parse_week(value):
    if not value:
        return week_start()
    return week_start(datetime.strptime(value, "%Y-%m-%d").date())


def _week_grid(start):
    days = rota_days_for_week(start)
    assignments = RotaAssignment.objects.filter(date__in=days).select_related("machinist")
    by_day = {day: {1: None, 2: None} for day in days}
    notes = {day: "" for day in days}
    for item in assignments:
        by_day[item.date][item.slot] = item.machinist
        if item.notes:
            notes[item.date] = item.notes
    return [
        {
            "date": day,
            "slot_1": by_day[day][1],
            "slot_2": by_day[day][2],
            "notes": notes[day],
        }
        for day in days
    ]


@login_required
def rota_week(request):
    start = _parse_week(request.GET.get("week"))
    machinists = User.objects.filter(
        role__in=[User.Role.MACHINIST, User.Role.ADMIN],
        is_active=True,
    ).order_by("display_name", "username")
    today = timezone.localdate()
    todays = [
        a.machinist for a in RotaAssignment.objects.filter(date=today).select_related("machinist")
    ]
    return render(
        request,
        "rota/week.html",
        {
            "week_start": start,
            "prev_week": start - timedelta(days=7),
            "next_week": start + timedelta(days=7),
            "grid": _week_grid(start),
            "machinists": machinists,
            "can_edit": request.user.is_machinist_role() or request.user.role == User.Role.ADMIN,
            "today": today,
            "todays_cover": todays,
        },
    )


@login_required
@require_POST
def save_rota(request):
    if not (request.user.is_machinist_role() or request.user.role == User.Role.ADMIN):
        messages.error(request, "Only machinists can change the rota.")
        return redirect("rota:week")

    start = _parse_week(request.POST.get("week"))
    for day in rota_days_for_week(start):
        key = day.isoformat()
        notes = request.POST.get(f"notes-{key}", "").strip()
        for slot in (1, 2):
            user_id = request.POST.get(f"slot-{key}-{slot}", "").strip()
            existing = RotaAssignment.objects.filter(date=day, slot=slot).first()
            if not user_id:
                if existing:
                    existing.delete()
                continue
            RotaAssignment.objects.update_or_create(
                date=day,
                slot=slot,
                defaults={"machinist_id": user_id, "notes": notes},
            )
    messages.success(request, "Rota updated.")
    return redirect(f"{reverse('rota:week')}?week={start.isoformat()}")


@login_required
@require_POST
def suggest_rota(request):
    if not (request.user.is_machinist_role() or request.user.role == User.Role.ADMIN):
        messages.error(request, "Only machinists can change the rota.")
        return redirect("rota:week")

    start = _parse_week(request.POST.get("week"))
    people = list(
        User.objects.filter(role=User.Role.MACHINIST, is_active=True).order_by("username")
    )
    if len(people) < 2:
        messages.error(request, "Need at least two machinists to fill a two-person rota.")
        return redirect(f"{reverse('rota:week')}?week={start.isoformat()}")

    for index, day in enumerate(rota_days_for_week(start)):
        first = people[index % len(people)]
        second = people[(index + 1) % len(people)]
        RotaAssignment.objects.update_or_create(
            date=day, slot=1, defaults={"machinist": first, "notes": ""}
        )
        RotaAssignment.objects.update_or_create(
            date=day, slot=2, defaults={"machinist": second, "notes": ""}
        )
    messages.success(request, "Filled this week with a rotating two-person cover.")
    return redirect(f"{reverse('rota:week')}?week={start.isoformat()}")

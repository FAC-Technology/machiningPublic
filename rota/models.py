from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


SLOT_PRIMARY = 1
SLOT_SECONDARY = 2


def _week_start_weekday():
    return getattr(settings, "ROTA_WEEK_START_WEEKDAY", 3)


def _skip_weekdays():
    return tuple(getattr(settings, "ROTA_SKIP_WEEKDAYS", (4, 5, 6)))


def week_start(day=None):
    day = day or timezone.localdate()
    offset = (day.weekday() - _week_start_weekday()) % 7
    return day - timedelta(days=offset)


def is_cover_day(day):
    return day.weekday() not in _skip_weekdays()


def calendar_days_for_week(start):
    return [start + timedelta(days=i) for i in range(7)]


def rota_days_for_week(start):
    return [day for day in calendar_days_for_week(start) if is_cover_day(day)]


def cover_days_for_week(start):
    return rota_days_for_week(start)


def machining_date_for(day=None):
    day = day or timezone.localdate()
    if is_cover_day(day):
        return day
    return None


def cover_for_date(day=None):
    day = machining_date_for(day)
    if day is None:
        return None, None
    assignments = {
        item.slot: item.machinist
        for item in RotaAssignment.objects.filter(date=day).select_related("machinist")
    }
    return assignments.get(SLOT_PRIMARY), assignments.get(SLOT_SECONDARY)


class RotaAssignment(models.Model):
    date = models.DateField()
    slot = models.PositiveSmallIntegerField()
    machinist = models.ForeignKey(
        "jobs.Person",
        on_delete=models.CASCADE,
        related_name="rota_days",
    )
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["date", "slot"]
        constraints = [
            models.UniqueConstraint(fields=["date", "slot"], name="unique_rota_slot"),
        ]

    def __str__(self):
        role = "primary" if self.slot == SLOT_PRIMARY else "secondary"
        return f"{self.date} {role}: {self.machinist}"

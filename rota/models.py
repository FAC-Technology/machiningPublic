from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


SLOT_PRIMARY = 1
SLOT_SECONDARY = 2


def week_start(day=None):
    day = day or timezone.localdate()
    return day - timedelta(days=day.weekday())


def rota_days_for_week(start):
    indexes = getattr(settings, "ROTA_WEEKDAY_INDEXES", (0, 1, 2, 3))
    return [start + timedelta(days=i) for i in indexes]


def machining_date_for(day=None):
    day = day or timezone.localdate()
    indexes = getattr(settings, "ROTA_WEEKDAY_INDEXES", (0, 1, 2, 3))
    if day.weekday() in indexes:
        return day
    start = week_start(day)
    days = rota_days_for_week(start)
    if day.weekday() > max(indexes):
        return days[-1]
    return rota_days_for_week(start - timedelta(days=7))[-1]


def cover_for_date(day=None):
    day = machining_date_for(day)
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

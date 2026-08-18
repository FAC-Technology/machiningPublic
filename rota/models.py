from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def week_start(day=None):
    day = day or timezone.localdate()
    return day - timedelta(days=day.weekday())


def rota_days_for_week(start):
    indexes = getattr(settings, "ROTA_WEEKDAY_INDEXES", (0, 1, 2, 3))
    return [start + timedelta(days=i) for i in indexes]


class RotaAssignment(models.Model):
    date = models.DateField()
    slot = models.PositiveSmallIntegerField()
    machinist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
        return f"{self.date} slot {self.slot}: {self.machinist}"

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse

from jobs.identity import SESSION_KEY
from jobs.models import Person
from rota.models import (
    SLOT_PRIMARY,
    SLOT_SECONDARY,
    RotaAssignment,
    machining_date_for,
    rota_days_for_week,
    week_start,
)


class RotaCalendarTests(TestCase):
    def test_week_has_four_days(self):
        days = rota_days_for_week(week_start())
        self.assertEqual(len(days), 4)
        self.assertEqual(days[0].weekday(), 0)
        self.assertEqual(days[-1].weekday(), 3)

    def test_friday_uses_thursday_cover(self):
        monday = week_start()
        friday = monday + timedelta(days=4)
        self.assertEqual(machining_date_for(friday), monday + timedelta(days=3))


class RotaPageTests(TestCase):
    def setUp(self):
        self.admin = Person.objects.create(
            initials="HA", name="HA", is_admin=True, is_machinist=True
        )
        self.machinist = Person.objects.create(initials="PS", name="PS", is_machinist=True)
        self.engineer = Person.objects.create(initials="EN", name="EN", is_engineer=True)

    def _as(self, person):
        session = self.client.session
        session[SESSION_KEY] = person.pk
        session.save()

    def test_everyone_can_see_rota(self):
        response = self.client.get(reverse("rota:week"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Primary machinist")
        self.assertContains(response, "Secondary machinist")
        self.assertContains(response, "Monday")
        self.assertContains(response, "Thursday")
        self.assertNotContains(response, "Save rota")

    def test_admin_can_save_primary_and_secondary(self):
        self._as(self.admin)
        response = self.client.get(reverse("rota:week"))
        self.assertContains(response, "Save rota")
        start = week_start()
        monday = start.isoformat()
        self.client.post(
            reverse("rota:save"),
            {
                "week": start.isoformat(),
                f"slot-{monday}-1": str(self.admin.pk),
                f"slot-{monday}-2": str(self.machinist.pk),
            },
        )
        self.assertEqual(
            RotaAssignment.objects.get(date=start, slot=SLOT_PRIMARY).machinist,
            self.admin,
        )
        self.assertEqual(
            RotaAssignment.objects.get(date=start, slot=SLOT_SECONDARY).machinist,
            self.machinist,
        )

    def test_non_admin_cannot_save(self):
        self._as(self.machinist)
        start = week_start()
        monday = start.isoformat()
        self.client.post(
            reverse("rota:save"),
            {
                "week": start.isoformat(),
                f"slot-{monday}-1": str(self.machinist.pk),
            },
        )
        self.assertEqual(RotaAssignment.objects.count(), 0)

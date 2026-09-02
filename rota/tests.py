from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from jobs.identity import SESSION_KEY
from jobs.models import Person
from rota.models import (
    SLOT_PRIMARY,
    SLOT_SECONDARY,
    RotaAssignment,
    cover_days_for_week,
    machining_date_for,
    rota_days_for_week,
    week_start,
)


class RotaCalendarTests(TestCase):
    def test_week_is_thursday_then_monday_to_wednesday(self):
        start = week_start()
        days = rota_days_for_week(start)
        self.assertEqual(start.weekday(), 3)
        self.assertEqual([day.weekday() for day in days], [3, 0, 1, 2])
        self.assertEqual(len(cover_days_for_week(start)), 4)

    def test_weekend_has_no_cover(self):
        start = week_start()
        friday = start + timedelta(days=1)
        saturday = start + timedelta(days=2)
        sunday = start + timedelta(days=3)
        self.assertEqual(friday.weekday(), 4)
        self.assertIsNone(machining_date_for(friday))
        self.assertIsNone(machining_date_for(saturday))
        self.assertIsNone(machining_date_for(sunday))
        self.assertNotIn(friday, cover_days_for_week(start))
        self.assertIn(start, cover_days_for_week(start))


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
        self.assertContains(response, "Thursday")
        self.assertContains(response, "Monday")
        self.assertContains(response, "Wednesday")
        self.assertNotContains(response, "Friday")
        self.assertNotContains(response, "Saturday")
        self.assertNotContains(response, "Sunday")
        self.assertNotContains(response, "No one")
        self.assertNotContains(response, "Save rota")

    def test_admin_can_save_primary_and_secondary(self):
        self._as(self.admin)
        response = self.client.get(reverse("rota:week"))
        self.assertContains(response, "Save rota")
        start = week_start()
        thursday = start.isoformat()
        self.client.post(
            reverse("rota:save"),
            {
                "week": start.isoformat(),
                f"slot-{thursday}-1": str(self.admin.pk),
                f"slot-{thursday}-2": str(self.machinist.pk),
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
        friday = start + timedelta(days=1)
        self.assertFalse(RotaAssignment.objects.filter(date=friday).exists())

    def test_fill_week_skips_weekend(self):
        self._as(self.admin)
        start = week_start()
        self.client.post(reverse("rota:suggest"), {"week": start.isoformat()})
        for offset in (1, 2, 3):
            self.assertFalse(RotaAssignment.objects.filter(date=start + timedelta(days=offset)).exists())
        self.assertTrue(RotaAssignment.objects.filter(date=start, slot=SLOT_PRIMARY).exists())
        self.assertEqual(RotaAssignment.objects.count(), 8)

    def test_non_admin_cannot_save(self):
        self._as(self.machinist)
        start = week_start()
        thursday = start.isoformat()
        self.client.post(
            reverse("rota:save"),
            {
                "week": start.isoformat(),
                f"slot-{thursday}-1": str(self.machinist.pk),
            },
        )
        self.assertEqual(RotaAssignment.objects.count(), 0)

    def test_admin_sees_post_to_chat_button(self):
        self._as(self.admin)
        response = self.client.get(reverse("rota:week"))
        self.assertContains(response, "Post this week to Chat")
        self.assertContains(response, "Google Chat webhook is not set")

    @override_settings(GOOGLE_CHAT_WEBHOOK_URL="https://chat.example/hook")
    def test_admin_sees_chat_connected_when_webhook_is_set(self):
        self._as(self.admin)
        response = self.client.get(reverse("rota:week"))
        self.assertContains(response, "Google Chat is connected.")

    def test_non_admin_does_not_see_post_to_chat_button(self):
        self._as(self.machinist)
        response = self.client.get(reverse("rota:week"))
        self.assertNotContains(response, "Post this week to Chat")

    @patch("jobs.google_chat.post_text")
    def test_save_and_suggest_do_not_post(self, mocked):
        self._as(self.admin)
        start = week_start()
        thursday = start.isoformat()
        self.client.post(
            reverse("rota:save"),
            {
                "week": start.isoformat(),
                f"slot-{thursday}-1": str(self.admin.pk),
                f"slot-{thursday}-2": str(self.machinist.pk),
            },
        )
        self.client.post(reverse("rota:suggest"), {"week": start.isoformat()})
        mocked.assert_not_called()

    @override_settings(GOOGLE_CHAT_WEBHOOK_URL="https://chat.example/hook")
    @patch("jobs.google_chat.post_text", return_value=True)
    def test_admin_can_post_week_to_chat(self, mocked):
        self._as(self.admin)
        start = week_start()
        thursday = start.isoformat()
        self.client.post(
            reverse("rota:save"),
            {
                "week": start.isoformat(),
                f"slot-{thursday}-1": str(self.admin.pk),
                f"slot-{thursday}-2": str(self.machinist.pk),
            },
        )
        mocked.reset_mock()
        response = self.client.post(
            reverse("rota:notify"),
            {"week": start.isoformat()},
            follow=True,
        )
        mocked.assert_called_once()
        text = mocked.call_args[0][0]
        self.assertIn("Machining rota", text)
        self.assertIn("HA", text)
        self.assertIn("PS", text)
        self.assertContains(response, "Posted this week to Google Chat.")

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_non_admin_cannot_post_week_to_chat(self, mocked):
        self._as(self.machinist)
        self.client.post(reverse("rota:notify"), {"week": week_start().isoformat()})
        mocked.assert_not_called()

    @override_settings(GOOGLE_CHAT_WEBHOOK_URL="")
    def test_unconfigured_chat_explains_itself(self):
        self._as(self.admin)
        response = self.client.post(
            reverse("rota:notify"),
            {"week": week_start().isoformat()},
            follow=True,
        )
        self.assertContains(response, "Chat webhook is not set.")

from django.test import TestCase

from rota.models import rota_days_for_week, week_start


class RotaCalendarTests(TestCase):
    def test_week_has_four_days(self):
        days = rota_days_for_week(week_start())
        self.assertEqual(len(days), 4)
        self.assertEqual(days[0].weekday(), 0)
        self.assertEqual(days[-1].weekday(), 3)

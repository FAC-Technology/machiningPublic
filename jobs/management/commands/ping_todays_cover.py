from django.core.management.base import BaseCommand
from django.utils import timezone

from jobs.google_chat import chat_configured, post_todays_cover
from jobs.models import CoverPing
from rota.models import is_cover_day


class Command(BaseCommand):
    help = "Post today's machining cover to Google Chat. Safe to run twice."

    def handle(self, *args, **options):
        today = timezone.localdate()
        if not is_cover_day(today):
            self.stdout.write("Not a machining day; skipped.")
            return
        if CoverPing.objects.filter(date=today).exists():
            self.stdout.write("Already posted today's cover.")
            return
        if not chat_configured():
            self.stdout.write("GOOGLE_CHAT_WEBHOOK_URL is not set; skipped.")
            return
        if post_todays_cover(today):
            CoverPing.objects.create(date=today)
            self.stdout.write(self.style.SUCCESS("Posted today's cover."))
            return
        self.stderr.write("Failed to post today's cover.")

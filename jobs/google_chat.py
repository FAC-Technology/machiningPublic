import ast
import json
import logging
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from rota.models import (
    SLOT_PRIMARY,
    SLOT_SECONDARY,
    RotaAssignment,
    cover_for_date,
    rota_days_for_week,
)

from .models import Job

logger = logging.getLogger(__name__)

TOP_QUEUE_N = 5
POST_TIMEOUT_SECONDS = 5


def _running_tests():
    return len(sys.argv) > 1 and sys.argv[1] == "test"


def _clean_url(value):
    return str(value or "").strip().strip("\"'")


def _url_from_local_settings_file():
    if _running_tests():
        return ""
    base = Path(getattr(settings, "BASE_DIR", Path(__file__).resolve().parent.parent))
    path = base / "config" / "local_settings.py"
    if not path.is_file():
        return ""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError):
        return ""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "GOOGLE_CHAT_WEBHOOK_URL":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    return _clean_url(node.value.value)
    return ""


def webhook_url():
    url = _clean_url(getattr(settings, "GOOGLE_CHAT_WEBHOOK_URL", ""))
    if url:
        return url
    url = _clean_url(os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", ""))
    if url:
        return url
    return _url_from_local_settings_file()


def chat_configured():
    return bool(webhook_url())


def post_text(text):
    url = webhook_url()
    if not url:
        return False
    try:
        body = json.dumps({"text": text}).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(request, timeout=POST_TIMEOUT_SECONDS) as response:
            response.read()
        return True
    except Exception as exc:
        logger.warning("Google Chat webhook failed: %s", exc)
        return False


def job_is_in_top_queue(job, n=TOP_QUEUE_N):
    if not job.pk:
        return False
    top_ids = list(Job.objects.queue().with_queue_order().values_list("pk", flat=True)[:n])
    return job.pk in top_ids


def cover_initials(day=None):
    primary, secondary = cover_for_date(day)
    return [person.initials for person in (primary, secondary) if person]


def with_cover(text, day=None):
    people = cover_initials(day)
    if not people:
        return text
    return f"{text} — cover {', '.join(people)}"


def _day_label(day):
    return f"{day.strftime('%A')} {day.day} {day.strftime('%b')}"


def _week_label(day):
    return f"{day.day} {day.strftime('%b %Y')}"


def _slot_initials(person):
    return person.initials if person else "Unassigned"


def todays_cover_text(day=None):
    day = day or timezone.localdate()
    primary, secondary = cover_for_date(day)
    lines = [f"*Today's machining cover* — {_day_label(day)}"]
    if not primary and not secondary:
        lines.append("No cover set.")
    else:
        lines.append(f"Primary: {_slot_initials(primary)}")
        lines.append(f"Secondary: {_slot_initials(secondary)}")
    return "\n".join(lines)


def week_rota_text(start):
    days = rota_days_for_week(start)
    assignments = RotaAssignment.objects.filter(date__in=days).select_related("machinist")
    by_day = {day: {SLOT_PRIMARY: None, SLOT_SECONDARY: None} for day in days}
    for item in assignments:
        by_day[item.date][item.slot] = item.machinist
    lines = [f"*Machining rota* — week of {_week_label(start)}"]
    for day in days:
        primary = by_day[day][SLOT_PRIMARY]
        secondary = by_day[day][SLOT_SECONDARY]
        lines.append(
            f"{_day_label(day)}: {_slot_initials(primary)} / {_slot_initials(secondary)}"
        )
    return "\n".join(lines)


def notify_job_started(job):
    machinist = job.machinist_primary.initials if job.machinist_primary else "?"
    post_text(f"*{job.job_id} started* by {machinist} — {job.job_label}")


def notify_job_edited(job):
    if not job_is_in_top_queue(job):
        return
    post_text(with_cover(f"*{job.job_id} updated*"))


def notify_job_abandoned(job, actor):
    engineer = job.requested_by.initials if job.requested_by else "?"
    machinist = actor.initials if actor else "?"
    text = f"*{job.job_id} abandoned* by {machinist} — engineer {engineer}."
    reason = (job.abandon_reason or "").strip()
    if reason:
        text += f" Reason: {reason}"
    post_text(text)


def notify_job_cancelled(job, actor):
    engineer = actor.initials if actor else "?"
    text = with_cover(f"*{job.job_id} cancelled* by {engineer}")
    reason = (job.cancel_reason or "").strip()
    if reason:
        text += f". Reason: {reason}"
    post_text(text)


def post_todays_cover(day=None):
    day = day or timezone.localdate()
    return post_text(todays_cover_text(day))


def post_week_rota(start):
    return post_text(week_rota_text(start))

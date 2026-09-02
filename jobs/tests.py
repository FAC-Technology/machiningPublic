from datetime import timedelta
from io import StringIO
from unittest.mock import patch
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from jobs.google_chat import job_is_in_top_queue, post_text
from jobs.identity import SESSION_KEY
from jobs.models import CoverPing, Destination, Job, Panel, Person, Project, RD_PROJECT_NAME
from rota.models import SLOT_PRIMARY, SLOT_SECONDARY, RotaAssignment, is_cover_day, week_start


def _pdf():
    return SimpleUploadedFile("part.pdf", b"%PDF-1.1", content_type="application/pdf")


def _dxf():
    return SimpleUploadedFile("part.dxf", b"0\nEOF\n", content_type="image/vnd.dxf")


def _crv():
    return SimpleUploadedFile("part.crv", b"toolpath", content_type="application/octet-stream")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class JobFlowTests(TestCase):
    def setUp(self):
        self.engineer = Person.objects.create(
            name="Hasan", initials="HA", is_engineer=True, is_machinist=True, is_admin=True
        )
        self.machinist = Person.objects.create(
            name="Priya", initials="PS", is_engineer=False, is_machinist=True
        )
        self.panel = Panel.objects.create(name="18mm birch ply")
        self.project, _ = Project.objects.get_or_create(name="PRD")
        self.rd_project, _ = Project.objects.get_or_create(name=RD_PROJECT_NAME)
        Project.objects.get_or_create(name="P10")
        Project.objects.get_or_create(name="P05")
        for name in ("Unit 1", "Unit 2", "Unit 4"):
            Destination.objects.get_or_create(name=name)
        session = self.client.session
        session[SESSION_KEY] = self.engineer.pk
        session.save()

    def _payload(self, **overrides):
        data = {
            "job_name": "Upright",
            "project": self.project.pk,
            "part_version": "A",
            "priority": Job.Priority.HIGH,
            "quantity": 2,
            "panel": self.panel.pk,
            "deadline": (timezone.localdate() + timedelta(days=7)).isoformat(),
            "destination": "Unit 1",
            "notes": "Keep stock on the bore.",
            "drawing_pdf": _pdf(),
            "drawing_dxf": _dxf(),
            "vcarve_file": _crv(),
        }
        data.update(overrides)
        return data

    def test_submit_with_three_files(self):
        response = self.client.post(reverse("jobs:submit"), self._payload(), follow=True)
        self.assertEqual(response.status_code, 200)
        job = Job.objects.get()
        self.assertTrue(job.job_id.startswith("MJ-"))
        self.assertEqual(job.submitted_date, timezone.localdate())
        self.assertEqual(job.pdf_filename, "part.pdf")
        self.assertEqual(job.destination, "Unit 1")
        self.assertEqual(job.requested_by, self.engineer)
        self.assertEqual(job.status, Job.Status.QUEUED)

    def test_unknown_destination_is_rejected(self):
        self.client.post(
            reverse("jobs:submit"),
            self._payload(destination="Project box 4"),
        )
        self.assertEqual(Job.objects.count(), 0)

    def test_submit_page_has_destination_dropdown(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertContains(response, "Unit 1")
        self.assertContains(response, "Unit 2")
        self.assertContains(response, "Unit 4")
        self.assertContains(response, '<select name="destination"')
        self.assertContains(response, 'value="HA"')
        self.assertContains(response, 'min="%s"' % timezone.localdate().isoformat())

    def test_deadline_cannot_be_before_today(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        self.client.post(reverse("jobs:submit"), self._payload(deadline=yesterday.isoformat()))
        self.assertEqual(Job.objects.count(), 0)

    def test_setup_can_add_destination(self):
        self.client.post(
            reverse("jobs:setup"),
            {"destination-name": "Stores", "add_destination": "1"},
        )
        self.assertTrue(Destination.objects.filter(name="Stores").exists())
        response = self.client.get(reverse("jobs:submit"))
        self.assertContains(response, "Stores")

    def test_submit_page_has_project_dropdown(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertContains(response, "PRD")
        self.assertContains(response, "P10")
        self.assertContains(response, "P05")
        self.assertContains(response, "R&amp;D")
        self.assertContains(response, "Choose project")

    def test_submit_page_part_number_starts_blank_template(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertContains(response, 'value="PN-00000"')
        self.assertRegex(response.content.decode(), r'name="part_version"[^>]*value="1"|value="1"[^>]*name="part_version"')

    def test_short_part_number_is_padded(self):
        self.client.post(reverse("jobs:submit"), self._payload(job_name="12"))
        self.assertEqual(Job.objects.get().job_name, "PN-00012")
        self.client.post(reverse("jobs:submit"), self._payload(job_name="PN-7", acknowledge_duplicate="on"))
        self.assertEqual(Job.objects.last().job_name, "PN-00007")

    def test_rd_job_uses_name_instead_of_part_number(self):
        self.client.post(
            reverse("jobs:submit"),
            self._payload(
                project=self.rd_project.pk,
                rd_name="Bracket",
                job_name="",
                part_version="",
            ),
        )
        job = Job.objects.get()
        self.assertEqual(job.job_name, "Bracket")
        self.assertEqual(job.part_version, "")
        self.assertTrue(job.is_rd)
        self.assertIn("R-D-Bracket", job.job_label)
        self.assertFalse(job.job_label.endswith("-"))
        detail = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(detail, "<dt>Name</dt>")
        self.assertContains(detail, "Bracket")
        self.assertNotContains(detail, "<dt>Part</dt>")
        self.assertNotContains(detail, " · v")
        queue = self.client.get(reverse("jobs:queue"))
        self.assertContains(queue, "Bracket")
        self.assertNotContains(queue, job.job_label)

    def test_rd_name_is_not_padded_as_part_number(self):
        self.client.post(
            reverse("jobs:submit"),
            self._payload(
                project=self.rd_project.pk,
                rd_name="12",
                job_name="PN-00000",
                part_version="1",
            ),
        )
        job = Job.objects.get()
        self.assertEqual(job.job_name, "12")
        self.assertEqual(job.part_version, "")

    def test_rd_submit_requires_name(self):
        self.client.post(
            reverse("jobs:submit"),
            self._payload(
                project=self.rd_project.pk,
                rd_name="",
                job_name="PN-00000",
                part_version="1",
            ),
        )
        self.assertEqual(Job.objects.count(), 0)

    def test_rd_name_is_limited_to_ten_characters(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertContains(response, 'id="id_rd_name"')
        self.assertContains(response, 'maxlength="10"')
        self.client.post(
            reverse("jobs:submit"),
            self._payload(
                project=self.rd_project.pk,
                rd_name="12345678901",
                job_name="",
                part_version="",
            ),
        )
        self.assertEqual(Job.objects.count(), 0)
        self.client.post(
            reverse("jobs:submit"),
            self._payload(
                project=self.rd_project.pk,
                rd_name="1234567890",
                job_name="",
                part_version="",
            ),
        )
        self.assertEqual(Job.objects.get().job_name, "1234567890")

    def test_rd_duplicate_warns_then_allows(self):
        def payload(**extra):
            data = self._payload(
                project=self.rd_project.pk,
                rd_name="Proto arm",
                job_name="",
                part_version="",
            )
            data.update(extra)
            return data

        self.client.post(reverse("jobs:submit"), payload())
        self.client.post(reverse("jobs:submit"), payload())
        self.assertEqual(Job.objects.count(), 1)
        self.client.post(reverse("jobs:submit"), payload(acknowledge_duplicate="on"))
        self.assertEqual(Job.objects.count(), 2)

    def test_submit_page_has_no_requested_by_field(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertNotContains(response, "id_requested_by")
        self.assertNotContains(response, "Requested by")

    def test_submit_page_has_no_stock_checkbox(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertNotContains(response, "The panel is in stock")
        self.assertNotContains(response, "id_materials_present")

    def test_requested_by_comes_from_working_as(self):
        other = Person.objects.create(name="Other", initials="OT", is_engineer=True)
        self.client.post(reverse("jobs:submit"), self._payload(requested_by=other.pk))
        job = Job.objects.get()
        self.assertEqual(job.requested_by, self.engineer)
        queue = self.client.get(reverse("jobs:queue"))
        self.assertContains(queue, job.requested_by.initials)

    def test_setup_page_has_projects(self):
        response = self.client.get(reverse("jobs:setup"))
        self.assertContains(response, "Projects")
        self.assertContains(response, "PRD")
        self.assertContains(response, "P10")
        self.assertContains(response, "P05")
        self.assertContains(response, "R&amp;D")
        self.assertContains(self.client.get(reverse("jobs:queue")), "People &amp; panels")

    def test_people_are_shown_as_initials_only(self):
        response = self.client.get(reverse("jobs:queue"))
        self.assertContains(response, ">HA<")
        self.assertNotContains(response, "Hasan")
        self.assertNotContains(response, "Priya")
        setup = self.client.get(reverse("jobs:setup"))
        self.assertContains(setup, "id_person-initials")
        self.assertNotContains(setup, "id_person-name")
        self.assertNotContains(setup, "Hasan")

    def test_add_person_with_initials_only(self):
        response = self.client.post(
            reverse("jobs:setup"),
            {"person-initials": "ab", "person-is_engineer": "on", "add_person": "1"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        person = Person.objects.get(initials="AB")
        self.assertTrue(person.is_engineer)
        self.assertEqual(person.name, "AB")

    def test_add_person_rejects_non_letters(self):
        self.client.post(
            reverse("jobs:setup"),
            {"person-initials": "H1", "add_person": "1"},
        )
        self.client.post(
            reverse("jobs:setup"),
            {"person-initials": "12", "add_person": "1"},
        )
        self.assertFalse(Person.objects.filter(initials__in=["H1", "12"]).exists())
        setup = self.client.get(reverse("jobs:setup"))
        self.assertContains(setup, 'pattern="[A-Za-z]{2,4}"')
        self.assertContains(setup, "Edit")
        self.assertContains(setup, "Delete")

    def test_can_edit_person_privileges(self):
        response = self.client.get(reverse("jobs:setup"), {"edit_person": self.machinist.pk})
        self.assertContains(response, "Editing PS")
        self.assertContains(response, "Save person")
        self.client.post(
            reverse("jobs:setup"),
            {
                "person-initials": "PS",
                "person-is_engineer": "on",
                "person-is_machinist": "on",
                "person_pk": self.machinist.pk,
                "save_person": "1",
            },
        )
        self.machinist.refresh_from_db()
        self.assertTrue(self.machinist.is_engineer)
        self.assertTrue(self.machinist.is_machinist)
        self.assertFalse(self.machinist.is_admin)

    def test_can_delete_unused_person(self):
        extra = Person.objects.create(initials="ZX", name="ZX", is_machinist=True)
        self.client.post(reverse("jobs:delete_person", args=[extra.pk]))
        self.assertFalse(Person.objects.filter(initials="ZX").exists())

    def test_cannot_delete_person_with_jobs(self):
        other = Person.objects.create(initials="OT", name="OT", is_engineer=True)
        Job.objects.create(
            job_name="Upright",
            project=self.project,
            part_version="A",
            requested_by=other,
            priority=Job.Priority.HIGH,
            quantity=1,
            panel=self.panel,
            deadline=timezone.localdate() + timedelta(days=7),
            destination="Unit 1",
            materials_present=True,
        )
        self.client.post(reverse("jobs:delete_person", args=[other.pk]))
        self.assertTrue(Person.objects.filter(pk=other.pk).exists())

    def test_cannot_delete_the_person_you_are_working_as(self):
        self.client.post(reverse("jobs:delete_person", args=[self.engineer.pk]))
        self.assertTrue(Person.objects.filter(pk=self.engineer.pk).exists())

    def test_setup_is_admin_only(self):
        session = self.client.session
        session[SESSION_KEY] = self.machinist.pk
        session.save()
        response = self.client.get(reverse("jobs:setup"))
        self.assertRedirects(response, reverse("jobs:queue"))
        queue = self.client.get(reverse("jobs:queue"))
        self.assertNotContains(queue, "People &amp; panels")
        extra_panel = Panel.objects.create(name="Scrap ply")
        self.client.post(reverse("jobs:delete_panel", args=[extra_panel.pk]))
        self.assertTrue(Panel.objects.filter(pk=extra_panel.pk).exists())

    def test_submit_page_has_one_file_box(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertContains(response, "Drop the PDF, DXF, and VCarve files here")
        self.assertContains(response, "PDF: not added")
        self.assertContains(response, "DXF: not added")
        self.assertContains(response, "VCarve: not added")
        self.assertContains(response, "Notes (optional)")
        self.assertNotContains(response, "id_pdf_filename")

    def test_missing_file_is_rejected(self):
        payload = self._payload()
        payload.pop("vcarve_file")
        self.client.post(reverse("jobs:submit"), payload)
        self.assertEqual(Job.objects.count(), 0)

    def test_wrong_file_type_is_rejected(self):
        self.client.post(
            reverse("jobs:submit"),
            self._payload(drawing_pdf=SimpleUploadedFile("notes.txt", b"nope", content_type="text/plain")),
        )
        self.assertEqual(Job.objects.count(), 0)

    def test_notes_are_optional(self):
        self.client.post(reverse("jobs:submit"), self._payload(notes=""))
        job = Job.objects.get()
        self.assertEqual(job.notes, "")

    def test_queue_and_job_page_have_clickable_file_links(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        pdf_url = reverse("jobs:file", args=[job.job_id, "pdf"])
        dxf_url = reverse("jobs:file", args=[job.job_id, "dxf"])
        crv_url = reverse("jobs:file", args=[job.job_id, "vcarve"])
        queue = self.client.get(reverse("jobs:queue"))
        self.assertNotContains(queue, pdf_url)
        self.assertNotContains(queue, dxf_url)
        self.assertNotContains(queue, crv_url)
        self.assertNotContains(queue, "<th>Destination</th>")
        self.assertNotContains(queue, "<th>Files</th>")
        table = queue.content.decode().split("<tbody>", 1)[1]
        self.assertNotIn(job.job_label, table)
        self.assertNotIn(job.destination, table)
        detail = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(detail, pdf_url)
        self.assertContains(detail, 'href="%s"' % pdf_url)
        self.assertContains(detail, job.destination)
        self.assertContains(detail, job.job_id)
        self.assertNotContains(detail, job.job_label)
        self.assertNotContains(detail, "pdf-preview")
        self.assertNotContains(detail, "Cancel job")
        file_response = self.client.get(pdf_url)
        self.assertEqual(file_response.status_code, 200)
        edit = self.client.get(reverse("jobs:edit", args=[job.job_id]))
        self.assertContains(edit, "Cancel job")
        self.assertContains(edit, f"Edit {job.job_id}")

    def test_quantity_limits(self):
        self.client.post(reverse("jobs:submit"), self._payload(quantity=0))
        self.client.post(reverse("jobs:submit"), self._payload(quantity=101))
        self.assertEqual(Job.objects.count(), 0)

    def test_duplicate_warns_then_allows(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        self.client.post(reverse("jobs:submit"), self._payload())
        self.assertEqual(Job.objects.count(), 1)
        self.client.post(reverse("jobs:submit"), self._payload(acknowledge_duplicate="on"))
        self.assertEqual(Job.objects.count(), 2)

    def test_hold_and_stock_controls_are_gone(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        detail = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertNotContains(detail, "id_materials_present")
        self.assertNotContains(detail, "Panel is in stock")
        self.assertNotContains(detail, 'value="hold"')
        self.assertNotContains(detail, "On hold")
        self.assertNotContains(detail, 'value="abandon"')
        self.client.post(reverse("jobs:update", args=[job.job_id]), {"action": "hold"})
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.QUEUED)
        self.assertTrue(job.materials_present)

    def test_complete_moves_to_history(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
            },
        )
        self.client.post(reverse("jobs:update", args=[job.job_id]), {"action": "complete"})
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.COMPLETED)

    def test_pages_render_without_login(self):
        self.assertEqual(self.client.get(reverse("jobs:submit")).status_code, 200)
        self.assertEqual(self.client.get(reverse("jobs:queue")).status_code, 200)

    def test_can_delete_unused_panel_and_project(self):
        extra_panel = Panel.objects.create(name="Scrap ply")
        extra_project = Project.objects.create(name="TEST")
        self.client.post(reverse("jobs:delete_panel", args=[extra_panel.pk]))
        self.client.post(reverse("jobs:delete_project", args=[extra_project.pk]))
        self.assertFalse(Panel.objects.filter(name="Scrap ply").exists())
        self.assertFalse(Project.objects.filter(name="TEST").exists())

    def test_cannot_delete_panel_or_project_in_use(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        self.client.post(reverse("jobs:delete_panel", args=[self.panel.pk]))
        self.client.post(reverse("jobs:delete_project", args=[self.project.pk]))
        self.assertTrue(Panel.objects.filter(pk=self.panel.pk).exists())
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

    def test_job_update_has_rota_machinist_dropdown(self):
        day = timezone.localdate()
        if is_cover_day(day):
            RotaAssignment.objects.create(date=day, slot=SLOT_PRIMARY, machinist=self.engineer)
            RotaAssignment.objects.create(date=day, slot=SLOT_SECONDARY, machinist=self.machinist)
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        detail = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(detail, '<select name="machinist_choice"')
        if is_cover_day(day):
            self.assertContains(detail, "HA (primary)")
            self.assertContains(detail, "PS (secondary)")
        else:
            self.assertNotContains(detail, "(primary)")
        self.assertContains(detail, ">Other<")
        self.assertNotContains(detail, "id_machinist_primary")
        self.assertNotContains(detail, "id_machinist_secondary")
        self.assertNotContains(detail, "Primary machinist")
        self.assertNotContains(detail, "Secondary machinist")
        self.assertNotContains(detail, 'value="save"')
        self.assertNotContains(detail, ">Complete<")
        self.assertNotContains(detail, ">Abandon<")
        self.assertNotContains(detail, "Overdue reason")
        self.assertNotContains(detail, "id_materials_present")
        self.assertNotContains(detail, 'value="hold"')
        self.assertContains(detail, 'id="machinist-other-row" hidden')
        self.assertNotContains(detail, "Cancel job")
        edit = self.client.get(reverse("jobs:edit", args=[job.job_id]))
        self.assertContains(edit, "Cancel job")
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
            },
        )
        job.refresh_from_db()
        self.assertEqual(job.machinist_primary, self.machinist)
        self.assertIsNone(job.machinist_secondary)
        self.assertEqual(job.status, Job.Status.IN_PROGRESS)
        started = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(started, ">Complete<")
        self.assertContains(started, ">Abandon<")
        self.assertContains(started, 'id="abandon-dialog"')
        self.assertContains(started, "abandon_reason")
        self.assertNotContains(started, 'value="start"')
        self.assertNotContains(started, "Cancel job")

    def test_other_machinist_uses_typed_initials(self):
        extra = Person.objects.create(initials="JK", name="JK", is_machinist=True)
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "jk",
            },
        )
        job.refresh_from_db()
        self.assertEqual(job.machinist_primary, extra)
        self.assertIsNone(job.machinist_secondary)

    def test_unknown_other_initials_are_rejected(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "ZZ",
            },
        )
        job.refresh_from_db()
        self.assertIsNone(job.machinist_primary)

    def test_overdue_reason_only_when_deadline_has_passed(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.assertNotContains(
            self.client.get(reverse("jobs:detail", args=[job.job_id])),
            "Overdue reason",
        )
        job.deadline = timezone.localdate() - timedelta(days=1)
        job.save(update_fields=["deadline"])
        overdue = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(overdue, "Overdue reason")
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
                "overdue_reason": "Waiting on a tool.",
            },
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.IN_PROGRESS)
        self.assertEqual(job.overdue_reason, "Waiting on a tool.")

    def test_only_engineer_can_cancel(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        session = self.client.session
        session[SESSION_KEY] = self.machinist.pk
        session.save()
        detail = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertNotContains(detail, "Cancel job")
        edit = self.client.get(reverse("jobs:edit", args=[job.job_id]))
        self.assertNotContains(edit, "Cancel job")
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {"action": "cancel", "cancel_reason": "Not needed."},
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.QUEUED)
        session = self.client.session
        session[SESSION_KEY] = self.engineer.pk
        session.save()
        self.assertContains(
            self.client.get(reverse("jobs:edit", args=[job.job_id])),
            "Cancel job",
        )
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {"action": "cancel", "cancel_reason": "Not needed."},
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.CANCELLED)

    def test_cannot_abandon_before_start(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "abandon",
                "panel_used": "",
                "machinist_choice": "",
                "abandon_reason": "Tool broke.",
            },
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.QUEUED)
        self.assertIsNone(job.started_at)

    def test_abandon_requires_a_reason(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
            },
        )
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "abandon",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
                "abandon_reason": "",
            },
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.IN_PROGRESS)
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "abandon",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
                "abandon_reason": "Panel split on the last pass.",
            },
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.ABANDONED)
        self.assertEqual(job.abandon_reason, "Panel split on the last pass.")
        history = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(history, "Panel split on the last pass.")

    def test_queue_shows_status_without_start(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        queue = self.client.get(reverse("jobs:queue"))
        self.assertContains(queue, "Queued")
        self.assertNotContains(queue, "Start machining")
        self.assertNotContains(queue, 'name="machinist_choice"')

    def test_in_progress_jobs_are_first_in_queue(self):
        self.client.post(reverse("jobs:submit"), self._payload(job_name="Waiting"))
        self.client.post(
            reverse("jobs:submit"),
            self._payload(job_name="Running", acknowledge_duplicate="on"),
        )
        waiting, running = Job.objects.order_by("pk")
        self.client.post(
            reverse("jobs:update", args=[running.job_id]),
            {
                "action": "start",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
            },
        )
        running.refresh_from_db()
        self.assertEqual(running.status, Job.Status.IN_PROGRESS)
        ordered = list(Job.objects.queue().with_queue_order().values_list("job_id", flat=True))
        self.assertEqual(ordered, [running.job_id, waiting.job_id])
        queue = self.client.get(reverse("jobs:queue"))
        html = queue.content.decode()
        table = html.split("<tbody>", 1)[1]
        self.assertLess(table.index(running.job_id), table.index(waiting.job_id))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class GoogleChatPingTests(TestCase):
    def setUp(self):
        self.engineer = Person.objects.create(
            name="Hasan", initials="HA", is_engineer=True, is_machinist=True, is_admin=True
        )
        self.machinist = Person.objects.create(
            name="Priya", initials="PS", is_engineer=False, is_machinist=True
        )
        self.panel = Panel.objects.create(name="18mm birch ply")
        self.project, _ = Project.objects.get_or_create(name="PRD")
        Destination.objects.get_or_create(name="Unit 1")
        session = self.client.session
        session[SESSION_KEY] = self.engineer.pk
        session.save()

    def _make_job(self, name, **kwargs):
        values = {
            "job_name": name,
            "project": self.project,
            "part_version": "A",
            "requested_by": self.engineer,
            "priority": Job.Priority.HIGH,
            "quantity": 1,
            "panel": self.panel,
            "deadline": timezone.localdate() + timedelta(days=7),
            "destination": "Unit 1",
            "materials_present": True,
        }
        values.update(kwargs)
        return Job.objects.create(**values)

    def _fill_ahead(self, count=5):
        jobs = []
        for index in range(count):
            jobs.append(
                self._make_job(
                    f"Ahead{index}",
                    part_version=str(index + 1),
                    deadline=timezone.localdate() + timedelta(days=1),
                    priority=Job.Priority.URGENT,
                )
            )
        return jobs

    def _edit(self, job, **overrides):
        data = {
            "job_name": job.job_name,
            "project": job.project.pk,
            "part_version": job.part_version,
            "priority": job.priority,
            "quantity": job.quantity,
            "panel": job.panel.pk,
            "deadline": job.deadline.isoformat(),
            "destination": job.destination,
            "notes": "Changed on the floor.",
        }
        data.update(overrides)
        return self.client.post(reverse("jobs:edit", args=[job.job_id]), data)

    def _start(self, job):
        return self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
            },
        )

    @override_settings(GOOGLE_CHAT_WEBHOOK_URL="")
    def test_post_text_is_quiet_without_url(self):
        with patch("jobs.google_chat.urlopen") as mocked:
            self.assertFalse(post_text("hello"))
            mocked.assert_not_called()

    @override_settings(GOOGLE_CHAT_WEBHOOK_URL="https://chat.example/hook")
    def test_post_text_sends_json(self):
        with patch("jobs.google_chat.urlopen") as mocked:
            mocked.return_value.__enter__.return_value.read.return_value = b"{}"
            self.assertTrue(post_text("hello"))
            request = mocked.call_args[0][0]
            self.assertEqual(request.full_url, "https://chat.example/hook")
            self.assertIn(b'"text": "hello"', request.data)

    def test_job_is_in_top_queue(self):
        self._fill_ahead(5)
        sixth = self._make_job("Sixth", priority=Job.Priority.LOW, deadline=timezone.localdate() + timedelta(days=20))
        self.assertTrue(job_is_in_top_queue(Job.objects.queue().with_queue_order()[0]))
        self.assertFalse(job_is_in_top_queue(sixth))

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_new_submit_does_not_post(self, mocked):
        self.client.post(
            reverse("jobs:submit"),
            {
                "job_name": "Upright",
                "project": self.project.pk,
                "part_version": "A",
                "priority": Job.Priority.HIGH,
                "quantity": 1,
                "panel": self.panel.pk,
                "deadline": (timezone.localdate() + timedelta(days=7)).isoformat(),
                "destination": "Unit 1",
                "drawing_pdf": SimpleUploadedFile("part.pdf", b"%PDF-1.1", content_type="application/pdf"),
                "drawing_dxf": SimpleUploadedFile("part.dxf", b"0\nEOF\n", content_type="image/vnd.dxf"),
                "vcarve_file": SimpleUploadedFile("part.crv", b"toolpath", content_type="application/octet-stream"),
            },
        )
        mocked.assert_not_called()

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_start_always_posts(self, mocked):
        self._fill_ahead(5)
        job = self._make_job("Sixth", priority=Job.Priority.LOW, deadline=timezone.localdate() + timedelta(days=20))
        self._start(job)
        mocked.assert_called_once()
        text = mocked.call_args[0][0]
        self.assertIn(f"*{job.job_id} started*", text)
        self.assertIn("PS", text)

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_complete_does_not_post(self, mocked):
        job = self._make_job("Running")
        self._start(job)
        mocked.reset_mock()
        self.client.post(reverse("jobs:update", args=[job.job_id]), {"action": "complete"})
        mocked.assert_not_called()

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_edit_posts_only_in_top_five(self, mocked):
        job = self._make_job("Top")
        self._edit(job)
        mocked.assert_called_once()
        self.assertIn(f"*{job.job_id} updated*", mocked.call_args[0][0])
        self.assertNotIn("cover", mocked.call_args[0][0])
        mocked.reset_mock()
        self._fill_ahead(5)
        buried = self._make_job("Buried", priority=Job.Priority.LOW, deadline=timezone.localdate() + timedelta(days=20))
        self._edit(buried)
        mocked.assert_not_called()

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_cancel_posts_only_in_top_five(self, mocked):
        job = self._make_job("Top")
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {"action": "cancel", "cancel_reason": "Not needed."},
        )
        mocked.assert_called_once()
        text = mocked.call_args[0][0]
        self.assertIn(f"*{job.job_id} cancelled*", text)
        self.assertIn("HA", text)
        self.assertIn("Not needed.", text)
        self.assertNotIn("cover", text)
        mocked.reset_mock()
        self._fill_ahead(5)
        buried = self._make_job("Buried", priority=Job.Priority.LOW, deadline=timezone.localdate() + timedelta(days=20))
        self.client.post(
            reverse("jobs:update", args=[buried.job_id]),
            {"action": "cancel", "cancel_reason": "Later."},
        )
        buried.refresh_from_db()
        self.assertEqual(buried.status, Job.Status.CANCELLED)
        mocked.assert_not_called()

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_edit_and_cancel_name_todays_cover_when_set(self, mocked):
        with patch("jobs.google_chat.cover_for_date", return_value=(self.machinist, None)):
            job = self._make_job("Top")
            self._edit(job)
            self.assertIn("cover PS", mocked.call_args[0][0])
            mocked.reset_mock()
            self.client.post(
                reverse("jobs:update", args=[job.job_id]),
                {"action": "cancel", "cancel_reason": "Not needed."},
            )
            self.assertIn("cover PS", mocked.call_args[0][0])

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_abandon_always_posts_engineer(self, mocked):
        self._fill_ahead(5)
        job = self._make_job("Sixth", priority=Job.Priority.LOW, deadline=timezone.localdate() + timedelta(days=20))
        self._start(job)
        mocked.reset_mock()
        session = self.client.session
        session[SESSION_KEY] = self.machinist.pk
        session.save()
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "abandon",
                "panel_used": "",
                "machinist_choice": "other",
                "machinist_other": "PS",
                "abandon_reason": "Panel split.",
            },
        )
        mocked.assert_called_once()
        text = mocked.call_args[0][0]
        self.assertIn(f"*{job.job_id} abandoned*", text)
        self.assertIn("engineer HA", text)
        self.assertIn("by PS", text)
        self.assertIn("Panel split.", text)

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_daily_cover_posts_once_on_machining_days(self, mocked):
        start = week_start()
        RotaAssignment.objects.create(date=start, slot=SLOT_PRIMARY, machinist=self.engineer)
        RotaAssignment.objects.create(date=start, slot=SLOT_SECONDARY, machinist=self.machinist)
        with (
            override_settings(GOOGLE_CHAT_WEBHOOK_URL="https://chat.example/hook"),
            patch("jobs.management.commands.ping_todays_cover.timezone") as tz,
        ):
            tz.localdate.return_value = start
            call_command("ping_todays_cover", stdout=StringIO())
            call_command("ping_todays_cover", stdout=StringIO())
        self.assertEqual(mocked.call_count, 1)
        text = mocked.call_args[0][0]
        self.assertIn("Today's machining cover", text)
        self.assertIn("HA", text)
        self.assertIn("PS", text)
        self.assertTrue(CoverPing.objects.filter(date=start).exists())

    @patch("jobs.google_chat.post_text", return_value=True)
    def test_daily_cover_skips_weekend(self, mocked):
        friday = week_start() + timedelta(days=1)
        with (
            override_settings(GOOGLE_CHAT_WEBHOOK_URL="https://chat.example/hook"),
            patch("jobs.management.commands.ping_todays_cover.timezone") as tz,
        ):
            tz.localdate.return_value = friday
            call_command("ping_todays_cover", stdout=StringIO())
        mocked.assert_not_called()
        self.assertFalse(CoverPing.objects.filter(date=friday).exists())


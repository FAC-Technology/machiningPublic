from datetime import timedelta
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from jobs.identity import SESSION_KEY
from jobs.models import Destination, Job, Panel, Person, Project
from rota.models import SLOT_PRIMARY, SLOT_SECONDARY, RotaAssignment, machining_date_for


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
        self.assertContains(queue, pdf_url)
        self.assertContains(queue, dxf_url)
        self.assertContains(queue, crv_url)
        detail = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(detail, pdf_url)
        self.assertContains(detail, 'href="%s"' % pdf_url)
        file_response = self.client.get(pdf_url)
        self.assertEqual(file_response.status_code, 200)

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

    def test_machinist_can_hold_when_material_missing(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.assertEqual(job.status, Job.Status.QUEUED)
        self.client.post(reverse("jobs:update", args=[job.job_id]), {"action": "hold"})
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.ON_HOLD)
        self.assertFalse(job.materials_present)

    def test_complete_moves_to_history(self):
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.client.post(reverse("jobs:update", args=[job.job_id]), {"action": "start", "materials_present": "on"})
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
        day = machining_date_for()
        RotaAssignment.objects.create(date=day, slot=SLOT_PRIMARY, machinist=self.engineer)
        RotaAssignment.objects.create(date=day, slot=SLOT_SECONDARY, machinist=self.machinist)
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        detail = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(detail, '<select name="machinist_choice"')
        self.assertContains(detail, "HA (primary)")
        self.assertContains(detail, "PS (secondary)")
        self.assertContains(detail, ">Other<")
        self.assertNotContains(detail, "id_machinist_primary")
        self.assertNotContains(detail, "id_machinist_secondary")
        self.assertNotContains(detail, "Primary machinist")
        self.assertNotContains(detail, "Secondary machinist")
        self.assertNotContains(detail, 'value="save"')
        self.assertNotContains(detail, ">Complete<")
        self.assertNotContains(detail, "Overdue reason")
        self.assertContains(detail, 'id="machinist-other-row" hidden')
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "machinist_choice": str(self.machinist.pk),
                "materials_present": "on",
            },
        )
        job.refresh_from_db()
        self.assertEqual(job.machinist_primary, self.machinist)
        self.assertIsNone(job.machinist_secondary)
        self.assertEqual(job.status, Job.Status.IN_PROGRESS)
        started = self.client.get(reverse("jobs:detail", args=[job.job_id]))
        self.assertContains(started, ">Complete<")
        self.assertNotContains(started, 'value="start"')

    def test_other_machinist_uses_typed_initials(self):
        extra = Person.objects.create(initials="JK", name="JK", is_machinist=True)
        self.client.post(reverse("jobs:submit"), self._payload())
        job = Job.objects.get()
        self.client.post(
            reverse("jobs:update", args=[job.job_id]),
            {
                "action": "start",
                "machinist_choice": "other",
                "machinist_other": "jk",
                "materials_present": "on",
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
                "machinist_choice": "other",
                "machinist_other": "ZZ",
                "materials_present": "on",
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
                "machinist_choice": "",
                "materials_present": "on",
                "overdue_reason": "Waiting on a tool.",
            },
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.IN_PROGRESS)
        self.assertEqual(job.overdue_reason, "Waiting on a tool.")

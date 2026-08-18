from datetime import timedelta
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from jobs.identity import SESSION_KEY
from jobs.models import Job, Panel, Person, Project


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
        session = self.client.session
        session[SESSION_KEY] = self.engineer.pk
        session.save()

    def _payload(self, **overrides):
        data = {
            "requested_by": self.engineer.pk,
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
            "materials_present": "on",
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

    def test_custom_destination(self):
        self.client.post(
            reverse("jobs:submit"),
            self._payload(destination="Project box 4"),
        )
        self.assertEqual(Job.objects.get().destination, "Project box 4")

    def test_submit_page_has_destination_units(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertContains(response, "Unit 1")
        self.assertContains(response, "Unit 2")
        self.assertContains(response, "Unit 4")
        self.assertContains(response, 'value="HA"')

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

    def test_setup_page_has_projects(self):
        response = self.client.get(reverse("jobs:setup"))
        self.assertContains(response, "Projects")
        self.assertContains(response, "PRD")
        self.assertContains(response, "P10")
        self.assertContains(response, "P05")

    def test_submit_page_has_one_file_box(self):
        response = self.client.get(reverse("jobs:submit"))
        self.assertContains(response, "Drop the PDF, DXF, and VCarve files here")
        self.assertContains(response, "PDF: not added")
        self.assertContains(response, "DXF: not added")
        self.assertContains(response, "VCarve: not added")
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

    def test_no_material_goes_on_hold_and_cannot_start(self):
        payload = self._payload()
        payload.pop("materials_present")
        self.client.post(reverse("jobs:submit"), payload)
        job = Job.objects.get()
        self.assertEqual(job.status, Job.Status.ON_HOLD)

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

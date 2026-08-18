from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .files import validate_typed_file
from .models import Job, Panel, Person, Project
from .services import find_duplicate_jobs


UNIT_DESTINATIONS = ("Unit 1", "Unit 2", "Unit 4")
DEFAULT_PART_NUMBER = "PN-00000"


class JobSubmitForm(forms.ModelForm):
    drawing_pdf = forms.FileField(required=False, label="PDF drawing")
    drawing_dxf = forms.FileField(required=False, label="DXF")
    vcarve_file = forms.FileField(required=False, label="VCarve")
    acknowledge_duplicate = forms.BooleanField(
        required=False,
        label="I've checked with the people involved and still want to submit this job",
    )
    materials_present = forms.BooleanField(
        required=False,
        label="The panel is in stock",
    )

    class Meta:
        model = Job
        fields = [
            "requested_by",
            "job_name",
            "project",
            "part_version",
            "priority",
            "quantity",
            "panel",
            "destination",
            "deadline",
            "notes",
            "materials_present",
        ]
        widgets = {
            "job_name": forms.TextInput(attrs={"placeholder": "PN-00000"}),
            "part_version": forms.TextInput(attrs={"placeholder": "1"}),
            "quantity": forms.NumberInput(attrs={"min": 1, "max": 100}),
            "deadline": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Anything the machinist needs to know"}),
            "destination": forms.TextInput(
                attrs={
                    "placeholder": "Pick a unit or type a location",
                    "list": "destination-options",
                    "autocomplete": "off",
                }
            ),
        }

    def __init__(self, *args, current_person=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicates = []
        self.uploads = {}
        self.fields["requested_by"].queryset = Person.objects.filter(is_active=True).filter(
            Q(is_engineer=True) | Q(is_admin=True)
        )
        self.fields["panel"].queryset = Panel.objects.filter(is_active=True)
        self.fields["project"].queryset = Project.objects.filter(is_active=True)
        self.fields["project"].empty_label = "Choose project"
        if not self.instance.pk:
            self.fields["deadline"].initial = timezone.localdate() + timedelta(days=7)
            self.fields["job_name"].initial = DEFAULT_PART_NUMBER
            self.fields["part_version"].initial = "1"
        self.fields["job_name"].widget.attrs.update({"id": "id_job_name", "spellcheck": "false", "autocomplete": "off"})
        self.fields["deadline"].input_formats = ["%Y-%m-%d"]
        self.fields["drawing_pdf"].widget.attrs.update({"accept": ".pdf", "id": "id_drawing_pdf"})
        self.fields["drawing_dxf"].widget.attrs.update({"accept": ".dxf", "id": "id_drawing_dxf"})
        self.fields["vcarve_file"].widget.attrs.update({"accept": ".crv,.crv3d", "id": "id_vcarve_file"})

        initials = (current_person.initials if current_person else "") or (
            self.instance.requested_by.initials if self.instance.pk else ""
        )
        self.destination_units = UNIT_DESTINATIONS
        self.destination_initials = initials
        self.fields["destination"].widget.attrs["id"] = "id_destination"

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity < 1 or quantity > 100:
            raise ValidationError("Quantity must be between 1 and 100.")
        return quantity

    def clean_drawing_pdf(self):
        upload = self.cleaned_data.get("drawing_pdf")
        if upload:
            return validate_typed_file(upload, "pdf", "PDF drawing")
        return upload

    def clean_drawing_dxf(self):
        upload = self.cleaned_data.get("drawing_dxf")
        if upload:
            return validate_typed_file(upload, "dxf", "DXF")
        return upload

    def clean_vcarve_file(self):
        upload = self.cleaned_data.get("vcarve_file")
        if upload:
            return validate_typed_file(upload, "vcarve", "VCarve")
        return upload

    def clean_destination(self):
        destination = (self.cleaned_data.get("destination") or "").strip()
        if not destination:
            raise ValidationError("Choose a unit or type a location.")
        return destination

    def clean(self):
        cleaned = super().clean()
        self.uploads = {
            "pdf": cleaned.get("drawing_pdf"),
            "dxf": cleaned.get("drawing_dxf"),
            "vcarve": cleaned.get("vcarve_file"),
        }
        creating = not self.instance.pk
        if creating:
            if not self.uploads["pdf"]:
                self.add_error("drawing_pdf", "Add a PDF drawing.")
            if not self.uploads["dxf"]:
                self.add_error("drawing_dxf", "Add a DXF file.")
            if not self.uploads["vcarve"]:
                self.add_error("vcarve_file", "Add a VCarve file (.crv or .crv3d).")

        job_name = cleaned.get("job_name")
        project = cleaned.get("project")
        version = cleaned.get("part_version")
        if job_name and project and version:
            self.duplicates = find_duplicate_jobs(
                job_name,
                project,
                version,
                exclude_pk=self.instance.pk,
            )
            if self.duplicates and not cleaned.get("acknowledge_duplicate"):
                names = ", ".join(j.job_id or j.job_label for j in self.duplicates)
                self.add_error(
                    "acknowledge_duplicate",
                    f"This looks like a duplicate of {names}. Tick the box if you have checked with the people involved.",
                )
        return cleaned

    def save(self, commit=True):
        job = super().save(commit=False)
        if not job.pk:
            job.submitted_date = timezone.localdate()
        job.duplicate_acknowledged = bool(self.cleaned_data.get("acknowledge_duplicate") or self.duplicates)
        if not job.materials_present:
            job.status = Job.Status.ON_HOLD
        elif job.status == Job.Status.ON_HOLD and job.started_at is None:
            job.status = Job.Status.QUEUED
        if commit:
            job.save()
        return job


class MachinistUpdateForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = [
            "machinist_primary",
            "machinist_secondary",
            "panel_used",
            "machinist_notes",
            "overdue_reason",
            "materials_present",
        ]
        widgets = {
            "panel_used": forms.TextInput(attrs={"placeholder": "Panel name / batch if you have it"}),
            "machinist_notes": forms.Textarea(attrs={"rows": 2, "placeholder": "Shop notes, scrap, or why it went wrong"}),
            "overdue_reason": forms.Textarea(attrs={"rows": 2, "placeholder": "Required if the deadline has passed"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        people = Person.objects.filter(is_active=True, is_machinist=True)
        self.fields["machinist_primary"].queryset = people
        self.fields["machinist_secondary"].queryset = people
        self.fields["machinist_primary"].required = False
        self.fields["machinist_secondary"].required = False
        self.fields["materials_present"].label = "Panel is in stock"


class CancelForm(forms.Form):
    cancel_reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Why is this job being withdrawn?"}),
        label="Cancel reason",
    )


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["name", "initials", "is_engineer", "is_machinist", "is_admin"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Hasan"}),
            "initials": forms.TextInput(attrs={"placeholder": "HA", "maxlength": 4}),
        }

    def clean_initials(self):
        initials = self.cleaned_data["initials"].strip().upper()
        if len(initials) < 2:
            raise ValidationError("Use two or more initials.")
        return initials


class PanelForm(forms.ModelForm):
    class Meta:
        model = Panel
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "18mm birch ply"})}


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "PRD"})}

from datetime import timedelta
import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from rota.models import cover_for_date

from .files import validate_typed_file
from .models import Destination, Job, Panel, Person, Project
from .services import find_duplicate_jobs


DEFAULT_PART_NUMBER = "PN-00000"
PART_NUMBER_DIGITS = 5


def normalize_part_number(value):
    text = (value or "").strip()
    match = re.fullmatch(r"(?:PN-)?(\d+)", text, re.I)
    if not match:
        return text
    digits = match.group(1).lstrip("0") or "0"
    return f"PN-{digits.zfill(PART_NUMBER_DIGITS)}"


class JobSubmitForm(forms.ModelForm):
    drawing_pdf = forms.FileField(required=False, label="PDF drawing")
    drawing_dxf = forms.FileField(required=False, label="DXF")
    vcarve_file = forms.FileField(required=False, label="VCarve")
    acknowledge_duplicate = forms.BooleanField(
        required=False,
        label="I've checked with the people involved and still want to submit this job",
    )
    destination = forms.ChoiceField()

    class Meta:
        model = Job
        fields = [
            "job_name",
            "project",
            "part_version",
            "priority",
            "quantity",
            "panel",
            "destination",
            "deadline",
            "notes",
        ]
        widgets = {
            "job_name": forms.TextInput(attrs={"placeholder": "PN-00000"}),
            "part_version": forms.TextInput(attrs={"placeholder": "1"}),
            "quantity": forms.NumberInput(attrs={"min": 1, "max": 100}),
            "deadline": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Optional — anything the machinist needs to know"}
            ),
        }

    def __init__(self, *args, current_person=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_person = current_person
        self.duplicates = []
        self.uploads = {}
        self.fields["notes"].required = False
        self.fields["panel"].queryset = Panel.objects.filter(is_active=True)
        self.fields["project"].queryset = Project.objects.filter(is_active=True)
        self.fields["project"].empty_label = "Choose project"
        if not self.instance.pk:
            self.fields["deadline"].initial = timezone.localdate() + timedelta(days=7)
            self.fields["job_name"].initial = DEFAULT_PART_NUMBER
            self.fields["part_version"].initial = "1"
        self.fields["job_name"].widget.attrs.update({
            "id": "id_job_name",
            "spellcheck": "false",
            "autocomplete": "off",
            "inputmode": "numeric",
            "maxlength": "8",
        })
        self.fields["deadline"].input_formats = ["%Y-%m-%d"]
        today = timezone.localdate()
        self.fields["deadline"].widget.attrs["min"] = today.isoformat()
        self.fields["drawing_pdf"].widget.attrs.update({"accept": ".pdf", "id": "id_drawing_pdf"})
        self.fields["drawing_dxf"].widget.attrs.update({"accept": ".dxf", "id": "id_drawing_dxf"})
        self.fields["vcarve_file"].widget.attrs.update({"accept": ".crv,.crv3d", "id": "id_vcarve_file"})

        initials = (current_person.initials if current_person else "") or (
            self.instance.requested_by.initials if self.instance.pk else ""
        )
        names = list(Destination.objects.filter(is_active=True).values_list("name", flat=True))
        choices = []
        if initials:
            choices.append((initials, initials))
        for name in names:
            if name != initials:
                choices.append((name, name))
        current = self.instance.destination if self.instance.pk else ""
        if current and current not in dict(choices):
            choices.append((current, current))
        self.fields["destination"].choices = [("", "Choose destination")] + choices
        self.fields["destination"].widget.attrs["id"] = "id_destination"
        if not self.instance.pk and initials:
            self.fields["destination"].initial = initials

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity < 1 or quantity > 100:
            raise ValidationError("Quantity must be between 1 and 100.")
        return quantity

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

    def clean_job_name(self):
        return normalize_part_number(self.cleaned_data.get("job_name"))

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
            raise ValidationError("Choose a destination.")
        return destination

    def clean_deadline(self):
        deadline = self.cleaned_data["deadline"]
        if deadline < timezone.localdate():
            raise ValidationError("Deadline cannot be before today.")
        return deadline

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
            if self.current_person:
                job.requested_by = self.current_person
            job.materials_present = True
        job.duplicate_acknowledged = bool(self.cleaned_data.get("acknowledge_duplicate") or self.duplicates)
        if commit:
            job.save()
        return job


class MachinistUpdateForm(forms.ModelForm):
    OTHER = "other"
    machinist_choice = forms.ChoiceField(required=False, label="Machinist")
    machinist_other = forms.CharField(
        required=False,
        max_length=4,
        label="Other initials",
        widget=forms.TextInput(attrs={"placeholder": "Initials", "maxlength": 4, "autocomplete": "off"}),
    )

    class Meta:
        model = Job
        fields = [
            "panel_used",
            "machinist_notes",
            "overdue_reason",
            "materials_present",
        ]
        widgets = {
            "panel_used": forms.TextInput(attrs={"placeholder": "Panel name / batch if you have it"}),
            "machinist_notes": forms.Textarea(attrs={"rows": 2, "placeholder": "Optional — shop notes, scrap, or anything useful"}),
            "overdue_reason": forms.Textarea(attrs={"rows": 2, "placeholder": "Why this job is still going after the deadline"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["materials_present"].label = "Panel is in stock"
        self.fields["machinist_notes"].required = False
        self.fields["machinist_notes"].label = "Machinist notes (optional)"
        if self.instance.pk and self.instance.is_overdue:
            self.fields["overdue_reason"].required = True
            self.fields["overdue_reason"].label = "Overdue reason"
        else:
            self.fields.pop("overdue_reason", None)
        primary, secondary = cover_for_date()
        choices = [("", "Choose machinist")]
        seen = set()
        if primary:
            choices.append((str(primary.pk), f"{primary.initials} (primary)"))
            seen.add(primary.pk)
        if secondary and secondary.pk not in seen:
            choices.append((str(secondary.pk), f"{secondary.initials} (secondary)"))
            seen.add(secondary.pk)
        choices.append((self.OTHER, "Other"))
        self.fields["machinist_choice"].choices = choices
        self.fields["machinist_choice"].widget.attrs["id"] = "id_machinist_choice"
        self.fields["machinist_other"].widget.attrs["id"] = "id_machinist_other"

        current = self.instance.machinist_primary if self.instance.pk else None
        if current and current.pk in seen:
            self.fields["machinist_choice"].initial = str(current.pk)
        elif current:
            self.fields["machinist_choice"].initial = self.OTHER
            self.fields["machinist_other"].initial = current.initials

    def clean_machinist_other(self):
        return (self.cleaned_data.get("machinist_other") or "").strip().upper()

    def clean(self):
        cleaned = super().clean()
        choice = cleaned.get("machinist_choice") or ""
        other = cleaned.get("machinist_other") or ""
        person = None
        if choice == self.OTHER:
            if len(other) < 2:
                self.add_error("machinist_other", "Enter initials.")
            else:
                person = Person.objects.filter(initials__iexact=other).first()
                if not person:
                    self.add_error("machinist_other", "No one with those initials.")
        elif choice:
            person = Person.objects.filter(pk=choice).first()
            if not person:
                self.add_error("machinist_choice", "Choose a machinist from the rota, or Other.")
        cleaned["resolved_machinist"] = person
        return cleaned

    def save(self, commit=True):
        job = super().save(commit=False)
        job.machinist_primary = self.cleaned_data.get("resolved_machinist")
        job.machinist_secondary = None
        if commit:
            job.save()
        return job


class CancelForm(forms.Form):
    cancel_reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Why is this job being withdrawn?"}),
        label="Cancel reason",
    )


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["initials", "is_engineer", "is_machinist", "is_admin"]
        widgets = {
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


class DestinationForm(forms.ModelForm):
    class Meta:
        model = Destination
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Unit 1"})}

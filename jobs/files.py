from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

PDF_EXT = {".pdf"}
DXF_EXT = {".dxf"}
VCARVE_EXT = {".crv", ".crv3d"}
MAX_FILE_BYTES = 500 * 1024 * 1024
KIND_EXTS = {"pdf": PDF_EXT, "dxf": DXF_EXT, "vcarve": VCARVE_EXT}


def classify_name(name):
    ext = Path(name).suffix.lower()
    if ext in PDF_EXT:
        return "pdf"
    if ext in DXF_EXT:
        return "dxf"
    if ext in VCARVE_EXT:
        return "vcarve"
    return "other"


def validate_typed_file(upload, kind, label):
    if not upload:
        raise ValidationError(f"Add a {label} file.")
    if classify_name(upload.name) != kind:
        allowed = ", ".join(sorted(KIND_EXTS[kind]))
        raise ValidationError(f"{label} must be {allowed}.")
    if getattr(upload, "size", 0) > MAX_FILE_BYTES:
        raise ValidationError(f"{upload.name} is over 500 MB.")
    return upload


def file_stamp(path: Path):
    stat = path.stat()
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def _safe_name(name):
    return Path(name).name.replace("..", "")


def write_job_files(job, uploads):
    folder = Path(settings.MEDIA_ROOT) / "jobs" / (job.job_id or f"tmp-{job.pk}")
    folder.mkdir(parents=True, exist_ok=True)
    mapping = {
        "pdf": ("pdf_filename", "pdf_stamp"),
        "dxf": ("dxf_filename", "dxf_stamp"),
        "vcarve": ("vcarve_filename", "vcarve_stamp"),
    }
    for kind, (name_field, stamp_field) in mapping.items():
        upload = uploads.get(kind)
        if not upload:
            continue
        dest = folder / _safe_name(upload.name)
        with dest.open("wb") as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        setattr(job, name_field, dest.name)
        setattr(job, stamp_field, file_stamp(dest))
    job.folder_path = str(folder)
    job.files_confirmed = True
    return folder


def job_file(job, kind):
    names = {
        "pdf": job.pdf_filename,
        "dxf": job.dxf_filename,
        "vcarve": job.vcarve_filename,
    }
    if kind not in names:
        raise ValidationError("Unknown file type.")
    folder = Path(job.folder_path).resolve()
    path = (folder / names[kind]).resolve()
    if path.parent != folder:
        raise ValidationError("File is not inside the job folder.")
    if not path.is_file():
        raise ValidationError("That file is no longer available.")
    return path

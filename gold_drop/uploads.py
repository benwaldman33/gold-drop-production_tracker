from __future__ import annotations

import json
import os

from flask import current_app
from werkzeug.utils import secure_filename


def allowed_image_filename(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {
        "jpg", "jpeg", "png", "webp", "heic", "heif",
    }


def allowed_lab_filename(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {
        "jpg", "jpeg", "png", "webp", "pdf", "heic", "heif",
    }


def file_size_bytes(file_obj) -> int:
    pos = file_obj.stream.tell()
    file_obj.stream.seek(0, os.SEEK_END)
    size = file_obj.stream.tell()
    file_obj.stream.seek(pos)
    return int(size)


def save_uploads(files, prefix: str, upload_dir: str, max_bytes: int, validator, error_message: str) -> list[str]:
    os.makedirs(upload_dir, exist_ok=True)
    saved: list[str] = []
    for f in files:
        if not f or not getattr(f, "filename", ""):
            continue
        filename = secure_filename(f.filename)
        if not filename or not validator(filename):
            raise ValueError(error_message)
        if file_size_bytes(f) > max_bytes:
            raise ValueError(f"{filename}: file too large (max {max_bytes // (1024 * 1024)} MB).")
        name = f"{prefix}-{filename}"
        full = os.path.join(upload_dir, name)
        stem, ext = os.path.splitext(name)
        i = 2
        while os.path.exists(full):
            name = f"{stem}-{i}{ext}"
            full = os.path.join(upload_dir, name)
            i += 1
        f.save(full)
        rel = os.path.relpath(full, current_app.static_folder).replace("\\", "/")
        saved.append(rel)
    return saved


def field_intake_photo_bucket_count(files) -> int:
    return len([f for f in files if f and getattr(f, "filename", "")])


def validate_field_intake_photo_bucket(files, label: str) -> None:
    mx = int(current_app.config.get("FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET", 30))
    if field_intake_photo_bucket_count(files) > mx:
        raise ValueError(f"{label}: max {mx} photos.")


def save_field_photos(files, prefix: str) -> list[str]:
    return save_uploads(
        files=files,
        prefix=prefix,
        upload_dir=current_app.config["FIELD_UPLOAD_DIR"],
        max_bytes=int(current_app.config.get("FIELD_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)),
        validator=allowed_image_filename,
        error_message="Allowed image types: JPG, JPEG, PNG, WEBP, HEIC, HEIF.",
    )


def save_lab_files(files, prefix: str) -> list[str]:
    return save_uploads(
        files=files,
        prefix=prefix,
        upload_dir=current_app.config["LAB_UPLOAD_DIR"],
        max_bytes=int(current_app.config.get("LAB_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)),
        validator=allowed_lab_filename,
        error_message="Allowed lab file types: JPG, JPEG, PNG, WEBP, PDF, HEIC, HEIF.",
    )


def save_purchase_support_docs(files, prefix: str) -> list[str]:
    return save_uploads(
        files=files,
        prefix=prefix,
        upload_dir=current_app.config["PURCHASE_UPLOAD_DIR"],
        max_bytes=int(current_app.config.get("PURCHASE_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)),
        validator=allowed_lab_filename,
        error_message="Allowed file types: JPG, JPEG, PNG, WEBP, PDF, HEIC, HEIF.",
    )


def save_photo_library_files(files, prefix: str) -> list[str]:
    return save_uploads(
        files=files,
        prefix=prefix,
        upload_dir=current_app.config["PHOTO_LIBRARY_UPLOAD_DIR"],
        max_bytes=int(current_app.config.get("PHOTO_LIBRARY_MAX_BYTES", 50 * 1024 * 1024)),
        validator=allowed_lab_filename,
        error_message="Allowed file types: JPG, JPEG, PNG, WEBP, PDF, HEIC, HEIF.",
    )


def json_paths(value) -> list[str]:
    try:
        paths = json.loads(value or "[]")
    except Exception:
        return []
    return [p for p in paths if isinstance(p, str) and p.strip()]

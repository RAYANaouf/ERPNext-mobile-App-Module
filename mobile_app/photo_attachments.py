"""Photos stored as native private ERPNext attachments."""

from io import BytesIO
from pathlib import Path, PurePath

import frappe

_PREVIEW_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_MAX_PHOTOS_PER_UPLOAD = 12
_MULTIPART_OVERHEAD = 64 * 1024


def _is_local_photo(file_url):
    url = file_url or ""
    return (
        url.startswith(("/private/files/", "/files/"))
        and ".." not in PurePath(url).parts
        and PurePath(url).suffix.lower() in _PHOTO_SUFFIXES
    )


def list_photos(doc):
    if not doc.has_permission("read"):
        return []
    files = frappe.get_all(
        "File",
        filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "is_folder": 0},
        fields=["name", "file_name", "file_url"],
        order_by="creation desc, name asc",
    )
    return [
        {"id": file.name, "file_name": file.file_name}
        for file in files
        if _is_local_photo(file.file_url)
    ]


def photo_preview(doc, file_id, thumbnail):
    from PIL import Image, ImageOps
    from werkzeug.wrappers import Response

    doc.check_permission("read")
    if not isinstance(file_id, str) or not file_id:
        frappe.throw(frappe._("A photo is required."))
    filters = {
        "name": file_id, "attached_to_doctype": doc.doctype,
        "attached_to_name": doc.name, "is_folder": 0,
    }
    if not frappe.db.exists("File", filters):
        frappe.throw("Access denied", frappe.PermissionError)
    file = frappe.get_doc("File", file_id)
    if (
        file.attached_to_doctype != doc.doctype
        or file.attached_to_name != doc.name
        or file.is_folder
        or not _is_local_photo(file.file_url)
    ):
        frappe.throw("Access denied", frappe.PermissionError)
    file.check_permission("read")

    # Only open a file inside the site's public or private uploads folder.
    folder = "private" if file.file_url.startswith("/private/") else "public"
    upload_root = Path(frappe.get_site_path(folder, "files")).resolve()
    path = Path(file.get_full_path()).resolve()
    if not path.is_relative_to(upload_root):
        frappe.throw("Access denied", frappe.PermissionError)

    size = 256 if frappe.utils.sbool(thumbnail) else 2048
    try:
        with Image.open(path, formats=list(_PREVIEW_FORMATS)) as image:
            if image.width * image.height > 64_000_000:
                frappe.throw(frappe._("The photo resolution is too large."))
            image.thumbnail((size, size))
            rotated = ImageOps.exif_transpose(image).convert("RGBA")
            preview = Image.new("RGB", rotated.size, "white")
            preview.paste(rotated, mask=rotated.getchannel("A"))
            result = BytesIO()
            preview.save(result, format="JPEG", quality=85)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        frappe.throw(frappe._("Unable to open the photo."))

    return Response(
        result.getvalue(),
        mimetype="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def photo_upload_limits():
    from frappe.core.api.file import get_max_file_size

    batch_limit = max(0, min(get_max_file_size(), 25 * 1024 * 1024) - _MULTIPART_OVERHEAD)
    return {
        "photo_max_bytes": min(batch_limit, 10 * 1024 * 1024),
        "photo_batch_max_bytes": batch_limit,
        "photo_max_count": _MAX_PHOTOS_PER_UPLOAD,
    }


def read_photo_uploads():
    request = getattr(frappe.local, "request", None)
    if not request or request.mimetype != "multipart/form-data":
        return []

    uploads = request.files.getlist("photo")
    if not uploads or any(not upload.filename for upload in uploads):
        frappe.throw(frappe._("Select a photo to attach."))
    if len(uploads) > _MAX_PHOTOS_PER_UPLOAD:
        frappe.throw(frappe._("Select at most {0} photos per upload.").format(_MAX_PHOTOS_PER_UPLOAD))

    limits = photo_upload_limits()
    remaining = limits["photo_batch_max_bytes"]
    per_photo_limit = limits["photo_max_bytes"]
    photos = []
    for upload in uploads:
        content = upload.stream.read(min(per_photo_limit, remaining) + 1)
        if len(content) > per_photo_limit:
            frappe.throw(
                frappe._("The photo exceeds the {0} MB limit.")
                .format(f"{per_photo_limit / 1048576:g}")
            )
        if len(content) > remaining:
            batch_limit = limits["photo_batch_max_bytes"]
            frappe.throw(
                frappe._("The selected photos exceed the combined limit of {0} MB.")
                .format(f"{batch_limit / 1048576:g}")
            )
        photos.append(_validate_photo(upload.filename, content))
        remaining -= len(content)
    return photos


def _validate_photo(filename, content):
    from PIL import Image

    extensions = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    try:
        with Image.open(BytesIO(content), formats=list(extensions)) as photo:
            if photo.width * photo.height > 40_000_000:
                frappe.throw(frappe._("The photo resolution is too large."))
            extension = extensions[photo.format]
            photo.verify()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        frappe.throw(frappe._("Select a valid JPG, PNG or WebP photo."))

    stem = PurePath(filename.replace("\\", "/")).stem.strip()[:100]
    return (stem or "photo") + extension, content


def attach_photos(doc, photos):
    for filename, content in photos:
        frappe.get_doc({
            "doctype": "File",
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
            "file_name": filename,
            "is_private": 1,
            "content": content,
        }).insert()

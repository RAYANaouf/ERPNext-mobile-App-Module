"""Photos stored as native private ERPNext attachments."""

from io import BytesIO
from pathlib import Path, PurePath

import frappe

_PREVIEW_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


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


def photo_limit():
    from frappe.core.api.file import get_max_file_size

    return min(get_max_file_size(), 10 * 1024 * 1024)


def read_photo_upload():
    request = getattr(frappe.local, "request", None)
    if not request or request.mimetype != "multipart/form-data":
        return None

    from PIL import Image

    upload = request.files.get("photo")
    if not upload or not upload.filename:
        frappe.throw(frappe._("Select a photo to attach."))
    limit = photo_limit()
    content = upload.stream.read(limit + 1)
    if len(content) > limit:
        frappe.throw(frappe._("The photo exceeds the {0} MB limit.").format(f"{limit / 1048576:g}"))

    extensions = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    try:
        with Image.open(BytesIO(content), formats=list(extensions)) as photo:
            if photo.width * photo.height > 40_000_000:
                frappe.throw(frappe._("The photo resolution is too large."))
            extension = extensions[photo.format]
            photo.verify()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        frappe.throw(frappe._("Select a valid JPG, PNG or WebP photo."))

    stem = PurePath(upload.filename.replace("\\", "/")).stem.strip()[:100]
    return (stem or "photo") + extension, content


def attach_photo(doc, photo):
    if photo is None:
        return
    filename, content = photo
    frappe.get_doc({
        "doctype": "File",
        "attached_to_doctype": doc.doctype,
        "attached_to_name": doc.name,
        "file_name": filename,
        "is_private": 1,
        "content": content,
    }).insert()

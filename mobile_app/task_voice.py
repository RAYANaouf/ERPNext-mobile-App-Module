"""Store and read document voice recordings as private files."""

import wave
from io import BytesIO
from pathlib import Path

import frappe
from werkzeug.wrappers import Response

from mobile_app.photo_attachments import photo_upload_limits, read_photo_uploads

_MAX_VOICE_BYTES = 5 * 1024 * 1024
_PRIVATE_FILES = "/private/files/"
_VOICE_MIME_TYPES = {".wav": "audio/wav", ".ogg": "audio/ogg"}


def voice_upload_limit(batch_limit):
    allowed_extensions = frappe.get_system_settings("allowed_file_extensions") or ""
    if allowed_extensions and "WAV" not in allowed_extensions.splitlines():
        return 0
    return min(batch_limit, _MAX_VOICE_BYTES)


def read_voice_attachments():
    request = getattr(frappe.local, "request", None)
    if not request or request.mimetype != "multipart/form-data":
        return []

    uploads = request.files.getlist("voice")
    if not uploads:
        return read_photo_uploads()
    if len(uploads) != 1 or not uploads[0].filename:
        frappe.throw(frappe._("Attach one voice recording at a time."))

    max_bytes = voice_upload_limit(photo_upload_limits()["photo_batch_max_bytes"])
    if not max_bytes:
        frappe.throw(frappe._("Voice recordings are disabled for this site."))
    content = uploads[0].stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        frappe.throw(frappe._("The voice recording exceeds the upload limit."))

    try:
        with wave.open(BytesIO(content), "rb") as audio:
            frame_count = audio.getnframes()
            frame_size = audio.getsampwidth() * audio.getnchannels()
            if not frame_count or len(audio.readframes(frame_count)) != frame_count * frame_size:
                raise wave.Error("Empty or incomplete recording")
    except (EOFError, wave.Error):
        frappe.throw(frappe._("Select a valid WAV voice recording."))

    photos = read_photo_uploads(required=False, reserved_bytes=len(content))
    return [("note-vocale.wav", content), *photos]


def list_voice_ids(doc):
    if not doc.has_permission("read"):
        return []
    return frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
            "is_folder": 0,
            "is_private": 1,
        },
        or_filters=[
            ["file_url", "like", f"{_PRIVATE_FILES}%{suffix}"]
            for suffix in _VOICE_MIME_TYPES
        ],
        order_by="creation desc, name asc",
        pluck="name",
    )


def _get_voice_file(doc, file_id, *, for_update=False):
    if not isinstance(file_id, str) or not file_id:
        frappe.throw(frappe._("A voice recording is required."))

    try:
        file = frappe.get_doc("File", file_id, for_update=for_update)
    except frappe.DoesNotExistError:
        frappe.clear_last_message()
        frappe.throw("Access denied", frappe.PermissionError)
    url = file.file_url or ""
    mime_type = _VOICE_MIME_TYPES.get(Path(url).suffix.lower())
    if (
        file.attached_to_doctype != doc.doctype
        or file.attached_to_name != doc.name
        or file.is_folder
        or not file.is_private
        or not url.startswith(_PRIVATE_FILES)
        or mime_type is None
    ):
        frappe.throw("Access denied", frappe.PermissionError)
    return file, mime_type


def detach_voices(doc, file_ids):
    if isinstance(file_ids, str):
        file_ids = frappe.parse_json(file_ids)
    if not isinstance(file_ids, list) or any(
        not isinstance(file_id, str) or not file_id.strip() for file_id in file_ids
    ):
        frappe.throw(frappe._("Select valid voice recordings."))
    if not file_ids:
        return

    doc.check_permission("write")
    files = []
    for file_id in dict.fromkeys(file_ids):
        file, _ = _get_voice_file(doc, file_id, for_update=True)
        file.check_permission("write")
        file.validate_protected_file()
        files.append(file)

    for file in files:
        file.add_comment_in_reference_doc("Attachment Removed", file.file_name)
        # Keep the private File available to its owner. Only its link to the document is removed.
        file.db_set({
            "attached_to_doctype": None,
            "attached_to_name": None,
            "attached_to_field": None,
        })


def read_voice(doc, file_id):
    doc.check_permission("read")
    file, mime_type = _get_voice_file(doc, file_id)
    file.check_permission("read")

    root = Path(frappe.get_site_path("private", "files")).resolve()
    path = Path(file.get_full_path()).resolve()
    if not path.is_relative_to(root):
        frappe.throw("Access denied", frappe.PermissionError)
    try:
        with path.open("rb") as audio:
            content = audio.read(_MAX_VOICE_BYTES + 1)
    except OSError:
        frappe.throw(frappe._("Unable to open the voice recording."))
    if not content or len(content) > _MAX_VOICE_BYTES:
        frappe.throw(frappe._("Unable to open the voice recording."))

    return Response(
        content,
        mimetype=mime_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )

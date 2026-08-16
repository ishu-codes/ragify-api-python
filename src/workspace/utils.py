import mimetypes
from pathlib import Path

# from src.utils.md import convert_to_md


def ensure_md(path: str):
    doc_path = Path(path)

    if doc_path.suffix.lower() == ".md":
        return str(doc_path)

    # convert_to_md(path)
    # return str(doc_path.with_suffix(".md"))


CUSTOM_MIME_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "application/json": ".json",
    "text/plain": ".txt",
    "application/zip": ".zip",
    "application/x-tar": ".tar",
    "application/gzip": ".gz",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def mime_to_extension(mime_type: str) -> str | None:
    ext = mimetypes.guess_extension(mime_type)
    if ext:
        return ext
    return CUSTOM_MIME_MAP.get(mime_type)


def replace_extension(filename: str, mime_type: str) -> str:
    """
    Replace file extension based on MIME type.
    If MIME cannot be mapped -> return original filename unchanged.
    """
    ext = mime_to_extension(mime_type)
    if not ext:
        return filename

    p = Path(filename)
    return str(p.with_suffix(ext))

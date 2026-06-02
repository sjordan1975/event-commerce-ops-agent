"""Shared image utilities — local path, HTTPS, and gs:// all handled here.

Every place in the codebase that reads image bytes or enumerates a batch
of images goes through this module. Adding a new storage backend means
editing one file.
"""

import time
import urllib.error
import urllib.request
from pathlib import Path

from google.genai import types as genai_types

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Retry config for HTTP image fetches (handles Wikimedia 429 rate limits)
_FETCH_MAX_RETRIES = 4
_FETCH_RETRY_BASE_S = 2.0


def _mime_type(url: str) -> str:
    ext = Path(url.split("?")[0]).suffix.lower()
    return {
        ".png":  "image/png",
        ".webp": "image/webp",
        ".gif":  "image/gif",
    }.get(ext, "image/jpeg")


def _fetch_with_retry(url: str) -> bytes:
    """Fetch image bytes with exponential backoff on 429/503."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(_FETCH_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                wait = _FETCH_RETRY_BASE_S * (2 ** attempt)
                time.sleep(wait)
                last_exc = exc
            else:
                raise
    raise last_exc


def image_as_part(url: str) -> genai_types.Part:
    """Return a genai Part for any image source.

    Supports:
      - gs://bucket/path  → Part.from_uri (Vertex AI reads natively, no local download)
      - https?://...      → fetched via urllib with retry, returned as Part.from_bytes
      - /local/path       → read from disk, returned as Part.from_bytes
    """
    mime = _mime_type(url)

    if url.startswith("gs://"):
        return genai_types.Part.from_uri(file_uri=url, mime_type=mime)

    if url.startswith("http://") or url.startswith("https://"):
        data = _fetch_with_retry(url)
        return genai_types.Part.from_bytes(data=data, mime_type=mime)

    with open(url, "rb") as f:
        data = f.read()
    return genai_types.Part.from_bytes(data=data, mime_type=mime)


def list_images(path: str) -> dict:
    """List image files for batch ingestion.

    Accepts:
      - Local directory path  → returns list of absolute file paths
      - gs://bucket/prefix    → returns list of gs:// URIs

    Returns {"files": [...], "count": N} or {"error": "...", "files": [], "count": 0}.
    """
    if path.startswith("gs://"):
        return _list_gcs(path)
    return _list_local(path)


def _list_local(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"error": f"path not found: {path!r}", "files": [], "count": 0}
    if not p.is_dir():
        return {"error": f"not a directory: {path!r}", "files": [], "count": 0}
    files = sorted(
        str(f.resolve())
        for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTS
    )
    return {"files": files, "count": len(files)}


def _list_gcs(gs_uri: str) -> dict:
    from google.cloud import storage  # lazy import — only needed for GCS paths

    without_scheme = gs_uri[len("gs://"):]
    bucket_name, _, prefix = without_scheme.partition("/")

    try:
        client = storage.Client()
        blobs = client.list_blobs(bucket_name, prefix=prefix or None)
        files = [
            f"gs://{bucket_name}/{blob.name}"
            for blob in blobs
            if Path(blob.name).suffix.lower() in _IMAGE_EXTS
        ]
        return {"files": sorted(files), "count": len(files)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "files": [], "count": 0}

"""Unit tests for src/images.py — routing, enumeration, MIME detection."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.images import _mime_type, image_as_part, list_images


# ── _mime_type ─────────────────────────────────────────────────────────────────

class TestMimeType:
    def test_jpg(self):
        assert _mime_type("photo.jpg") == "image/jpeg"

    def test_jpeg(self):
        assert _mime_type("photo.jpeg") == "image/jpeg"

    def test_png(self):
        assert _mime_type("photo.png") == "image/png"

    def test_webp(self):
        assert _mime_type("photo.webp") == "image/webp"

    def test_gif(self):
        assert _mime_type("photo.gif") == "image/gif"

    def test_unknown_defaults_to_jpeg(self):
        assert _mime_type("photo.bmp") == "image/jpeg"

    def test_uppercase_extension(self):
        assert _mime_type("photo.PNG") == "image/png"  # .lower() normalises before lookup

    def test_gs_uri_with_extension(self):
        assert _mime_type("gs://bucket/folder/photo.jpg") == "image/jpeg"

    def test_https_url_with_extension(self):
        assert _mime_type("https://example.com/img.png") == "image/png"

    def test_query_string_stripped(self):
        assert _mime_type("https://example.com/img.jpg?w=800") == "image/jpeg"


# ── image_as_part — routing ────────────────────────────────────────────────────

class TestImageAsPart:
    def test_gs_uri_uses_from_uri(self):
        with patch("src.images.genai_types.Part.from_uri") as mock_uri:
            mock_uri.return_value = MagicMock()
            result = image_as_part("gs://bucket/photo.jpg")
            mock_uri.assert_called_once_with(
                file_uri="gs://bucket/photo.jpg", mime_type="image/jpeg"
            )
            assert result is mock_uri.return_value

    def test_https_url_uses_from_bytes(self):
        fake_bytes = b"fakeimagebytes"
        with patch("urllib.request.urlopen") as mock_open, \
             patch("src.images.genai_types.Part.from_bytes") as mock_bytes:
            mock_open.return_value.__enter__ = lambda s: s
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            mock_open.return_value.read.return_value = fake_bytes
            mock_bytes.return_value = MagicMock()

            image_as_part("https://example.com/photo.jpg")

            mock_bytes.assert_called_once_with(data=fake_bytes, mime_type="image/jpeg")

    def test_http_url_uses_from_bytes(self):
        fake_bytes = b"fakeimagebytes"
        with patch("urllib.request.urlopen") as mock_open, \
             patch("src.images.genai_types.Part.from_bytes") as mock_bytes:
            mock_open.return_value.__enter__ = lambda s: s
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            mock_open.return_value.read.return_value = fake_bytes
            mock_bytes.return_value = MagicMock()

            image_as_part("http://example.com/photo.jpg")

            mock_bytes.assert_called_once()

    def test_local_path_reads_file(self):
        fake_bytes = b"localimagedata"
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(fake_bytes)
            tmp_path = f.name
        try:
            with patch("src.images.genai_types.Part.from_bytes") as mock_bytes:
                mock_bytes.return_value = MagicMock()
                image_as_part(tmp_path)
                mock_bytes.assert_called_once_with(data=fake_bytes, mime_type="image/jpeg")
        finally:
            os.unlink(tmp_path)

    def test_gs_uri_png_passes_correct_mime(self):
        with patch("src.images.genai_types.Part.from_uri") as mock_uri:
            mock_uri.return_value = MagicMock()
            image_as_part("gs://bucket/photo.png")
            mock_uri.assert_called_once_with(
                file_uri="gs://bucket/photo.png", mime_type="image/png"
            )


# ── list_images — local directory ─────────────────────────────────────────────

class TestListImagesLocal:
    def test_returns_image_files(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.jpg").write_bytes(b"")
            Path(d, "b.png").write_bytes(b"")
            Path(d, "c.txt").write_bytes(b"")  # not an image — excluded
            result = list_images(d)
            assert result["count"] == 2
            assert "error" not in result
            basenames = {Path(f).name for f in result["files"]}
            assert basenames == {"a.jpg", "b.png"}

    def test_all_supported_extensions(self):
        with tempfile.TemporaryDirectory() as d:
            for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                Path(d, f"img{ext}").write_bytes(b"")
            result = list_images(d)
            assert result["count"] == 5

    def test_nonexistent_path_returns_error(self):
        result = list_images("/nonexistent/path/that/does/not/exist")
        assert "error" in result
        assert result["files"] == []
        assert result["count"] == 0

    def test_file_path_not_dir_returns_error(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            result = list_images(f.name)
        assert "error" in result
        assert result["files"] == []

    def test_empty_directory_returns_zero(self):
        with tempfile.TemporaryDirectory() as d:
            result = list_images(d)
            assert result["count"] == 0
            assert result["files"] == []

    def test_returns_absolute_paths(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "photo.jpg").write_bytes(b"")
            result = list_images(d)
            assert all(Path(f).is_absolute() for f in result["files"])

    def test_files_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("c.jpg", "a.jpg", "b.jpg"):
                Path(d, name).write_bytes(b"")
            result = list_images(d)
            names = [Path(f).name for f in result["files"]]
            assert names == sorted(names)

    def test_subdirectories_not_included(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "photo.jpg").write_bytes(b"")
            Path(d, "subdir").mkdir()
            result = list_images(d)
            assert result["count"] == 1


# ── list_images — GCS routing ──────────────────────────────────────────────────

class TestListImagesGCS:
    def test_gs_uri_routes_to_gcs(self):
        mock_blob = MagicMock()
        mock_blob.name = "wc-final/photo.jpg"
        mock_client_instance = MagicMock()
        mock_client_instance.list_blobs.return_value = [mock_blob]

        with patch("google.cloud.storage.Client", return_value=mock_client_instance):
            result = list_images("gs://my-bucket/wc-final/")

        mock_client_instance.list_blobs.assert_called_once_with("my-bucket", prefix="wc-final/")
        assert result["files"] == ["gs://my-bucket/wc-final/photo.jpg"]
        assert result["count"] == 1

    def test_gs_non_image_blobs_excluded(self):
        def _blob(n: str):
            b = MagicMock(); b.name = n; return b
        blobs = [_blob(n) for n in ("img.jpg", "readme.txt", "photo.png")]
        mock_client_instance = MagicMock()
        mock_client_instance.list_blobs.return_value = blobs

        with patch("google.cloud.storage.Client", return_value=mock_client_instance):
            result = list_images("gs://bucket/prefix/")

        assert result["count"] == 2
        basenames = {Path(f).name for f in result["files"]}
        assert basenames == {"img.jpg", "photo.png"}

    def test_gs_error_returns_error_dict(self):
        mock_client_instance = MagicMock()
        mock_client_instance.list_blobs.side_effect = Exception("permission denied")

        with patch("google.cloud.storage.Client", return_value=mock_client_instance):
            result = list_images("gs://bucket/prefix/")

        assert "error" in result
        assert result["files"] == []
        assert result["count"] == 0

    def test_gs_bucket_only_no_prefix(self):
        mock_client_instance = MagicMock()
        mock_client_instance.list_blobs.return_value = []

        with patch("google.cloud.storage.Client", return_value=mock_client_instance):
            list_images("gs://my-bucket/")

        mock_client_instance.list_blobs.assert_called_once_with("my-bucket", prefix=None)

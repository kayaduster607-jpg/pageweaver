"""Exercise download failure boundaries and real PDF output using synthetic pages."""

from contextlib import redirect_stdout, redirect_stderr
from io import BytesIO, StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pikepdf
import requests
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi.testclient import TestClient
import image_url_to_pdf as core
import image_to_pdf_server as web


def image_bytes(color="red"):
    """Create a tiny complete image instead of loading local documents."""
    with Image.new("RGB", (20, 30), color) as image:
        stream = BytesIO()
        image.save(stream, "PNG")
        return stream.getvalue()


def response(body, status=200, content_type="image/png"):
    """Provide a real Requests response object with controlled headers."""
    item = requests.Response()
    item.status_code = status
    item.url = "https://example.test/book/page_0001.png"
    item._content = body
    item.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    return item


def fetch(session, retries=0):
    return core.fetch_image(session, "https://example.test/book/page_0001.png", 1,
                            retries, requests, Image, ImageOps, UnidentifiedImageError)


def page_count(data):
    with pikepdf.Pdf.open(BytesIO(data)) as document:
        return len(document.pages)


class DownloadTests(unittest.TestCase):
    def test_numbering_preserves_raw_query_and_prefix(self):
        pattern = core.parse_sequence_url("https://example.test/book/page_0031.png?b=a%2Fb&a=2#part")
        self.assertEqual(pattern.url_for(2), "https://example.test/book/page_0002.png?b=a%2Fb&a=2#part")

    def test_dry_run_starts_at_one_without_opening_a_session(self):
        output = StringIO()
        with patch.object(core, "require_runtime", side_effect=AssertionError("No runtime needed")):
            with redirect_stdout(output):
                result = core.main(["https://example.test/book/00031.png", "--dry-run"])
        self.assertEqual(result, 0)
        self.assertIn("/00001.png", output.getvalue())
        self.assertNotIn("/00031.png\n  ", output.getvalue())

    def test_hand_constructed_stripes_with_uneven_height(self):
        with Image.new("RGB", (1, 5)) as encoded:
            for y, color in enumerate(["red", "red", "blue", "blue", "blue"]):
                encoded.putpixel((0, y), (255, 0, 0) if color == "red" else (0, 0, 255))
            restored = core.restore_jm_stripes(encoded, 2, Image)
        try:
            self.assertEqual([restored.getpixel((0, y)) for y in range(5)],
                             [(0, 0, 255)] * 3 + [(255, 0, 0)] * 2)
        finally:
            restored.close()

    def test_missing_page_is_not_retried(self):
        session = Mock()
        session.get.return_value = response(b"missing", 404)
        with self.assertRaises(core.SequenceEnded):
            fetch(session, retries=3)
        self.assertEqual(session.get.call_count, 1)

    def test_html_response_is_a_sequence_end_signal(self):
        session = Mock()
        session.get.return_value = response(b"<html>login</html>", content_type="text/html")
        with self.assertRaises(core.SequenceEnded):
            fetch(session)

    def test_transient_timeout_retries_then_decodes(self):
        session = Mock()
        session.get.side_effect = [requests.Timeout("synthetic timeout"), response(image_bytes())]
        with patch.object(core.time, "sleep") as sleep, redirect_stdout(StringIO()):
            image, _ = fetch(session, retries=1)
        try:
            self.assertEqual(image.size, (20, 30))
            self.assertEqual(session.get.call_count, 2)
            sleep.assert_called_once_with(1.0)
        finally:
            image.close()

    def test_truncated_content_is_not_accepted(self):
        session = Mock()
        bad = response(image_bytes())
        bad.headers["Content-Length"] = str(len(bad.content) + 1)
        session.get.return_value = bad
        with self.assertRaisesRegex(RuntimeError, "incomplete response"):
            fetch(session)

    def test_explicit_end_prevents_partial_cli_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "must-not-exist.pdf"
            with patch.object(core, "fetch_image", side_effect=[
                (Image.new("RGB", (20, 30)), "https://example.test/book/0001.png"),
                core.SequenceEnded("synthetic missing page"),
            ]), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = core.main(["https://example.test/book/0001.png", "--end", "3",
                                    "--descramble", "none", "--delay", "0", "-o", str(target)])
            self.assertEqual(result, 1)
            self.assertFalse(target.exists())


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.paths = []
        for index, color in enumerate(("red", "blue")):
            path = self.root / f"{index}.png"
            path.write_bytes(image_bytes(color))
            self.paths.append(path)

    def tearDown(self):
        self.directory.cleanup()

    def test_pages_pdf_has_two_readable_pages(self):
        target = self.root / "pages.pdf"
        core.save_pages_pdf(self.paths, target, 150, Image)
        self.assertEqual(page_count(target.read_bytes()), 2)

    def test_long_pdf_has_one_readable_page(self):
        target = self.root / "long.pdf"
        core.save_long_pdf(self.paths, target, 150, 20, 10000, Image)
        self.assertEqual(page_count(target.read_bytes()), 1)

    def test_long_canvas_limit_prevents_output(self):
        target = self.root / "blocked.pdf"
        with self.assertRaisesRegex(RuntimeError, "safety limit"):
            core.save_long_pdf(self.paths, target, 150, 20, 1, Image)
        self.assertFalse(target.exists())


class WebTests(unittest.TestCase):
    def setUp(self):
        with web.task_lock:
            web.tasks.clear()

    def test_thumbnail_is_available_before_the_next_page(self):
        def next_page(*args, **kwargs):
            if next_page.calls == 0:
                next_page.calls += 1
                return Image.new("RGB", (20, 30)), "https://example.test/book/0001.png"
            self.assertFalse(web.tasks["preview"]["done"])
            self.assertEqual(web.api_thumb("preview", 1).status_code, 200)
            raise core.SequenceEnded("synthetic end")

        next_page.calls = 0
        with patch.object(web, "fetch_image", side_effect=next_page):
            web.download_task("preview", "https://example.test/book/0001.png", 1, None)
        self.assertEqual(web.tasks["preview"]["total"], 1)

    def test_web_retains_prefix_pdf_and_reports_incomplete_range(self):
        with patch.object(web, "fetch_image", side_effect=[
            (Image.new("RGB", (20, 30)), "https://example.test/book/0001.png"),
            core.SequenceEnded("synthetic missing page"),
        ]):
            web.download_task("partial", "https://example.test/book/0001.png", 1, 3)
        state = web.api_status("partial")
        self.assertTrue(state["done"])
        self.assertIsNotNone(state["error"])
        self.assertEqual(page_count(web.tasks["partial"]["pdf"]), 1)

    def test_start_uses_query_parameters_and_keeps_zero(self):
        thread = Mock()
        # Replace only this module's namespace, not Python's global threading API.
        with patch.object(web, "threading", Mock(Thread=thread)):
            with TestClient(web.app) as client:
                result = client.post("/api/start", params={
                    "url": "https://example.test/book/page_0031.png", "start": 0, "end": 2,
                })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(thread.call_args.kwargs["args"][2:], (0, 2))
        self.assertEqual(result.json()["num_len"], 4)

    def test_bad_url_and_invalid_range_never_start_a_task(self):
        thread = Mock()
        with patch.object(web, "threading", Mock(Thread=thread)):
            with TestClient(web.app) as client:
                bad_url = client.post("/api/start", params={"url": "not-a-url"})
                bad_range = client.post("/api/start", params={
                    "url": "https://example.test/book/0001.png", "start": 3, "end": 2,
                })
                negative = client.post("/api/start", params={
                    "url": "https://example.test/book/0001.png", "start": -1,
                })
        self.assertEqual([bad_url.status_code, bad_range.status_code, negative.status_code], [400, 422, 422])
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()

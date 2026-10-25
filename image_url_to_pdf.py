# -*- coding: utf-8 -*-
"""
Download a numbered image sequence, restore JM-style scrambled pages when
needed, and export the ordered pages to a PDF.

Compatible with Python 3.9 and newer.

Examples:
    python image_url_to_pdf.py "https://example.com/book/00031.webp"
    python image_url_to_pdf.py URL -o result.pdf --overwrite
    python image_url_to_pdf.py URL --descramble none
    python image_url_to_pdf.py URL --pdf-mode long
"""

import argparse
import hashlib
import math
import os
import re
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit, urlunsplit


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_JM_REFERER = "https://18comic.vip/"
DEFAULT_SCRAMBLE_ID = 220980
JM_SCRAMBLE_268850 = 268850
JM_SCRAMBLE_421926 = 421926
MAX_PDF_PAGE_POINTS = 14400

IMAGE_NAME_RE = re.compile(
    r"^(?P<prefix>.*?)(?P<number>\d+)(?P<extension>\.[A-Za-z0-9]+)$"
)
JM_PHOTO_PATH_RE = re.compile(r"/media/photos/(?P<aid>\d+)/", re.IGNORECASE)


class SequenceEnded(Exception):
    """Raised when the next numbered image does not exist."""


class SequencePattern(object):
    def __init__(
        self,
        original_url: str,
        scheme: str,
        netloc: str,
        directory: str,
        prefix: str,
        number_width: int,
        extension: str,
        query: str,
        fragment: str,
    ) -> None:
        self.original_url = original_url
        self.scheme = scheme
        self.netloc = netloc
        self.directory = directory
        self.prefix = prefix
        self.number_width = number_width
        self.extension = extension
        self.query = query
        self.fragment = fragment

    def filename_for(self, index: int) -> str:
        number = str(index).zfill(self.number_width)
        return "{}{}{}".format(self.prefix, number, self.extension)

    def url_for(self, index: int) -> str:
        path = self.directory + self.filename_for(index)
        return urlunsplit(
            (self.scheme, self.netloc, path, self.query, self.fragment)
        )


def parse_sequence_url(url: str) -> SequencePattern:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("URL must start with http:// or https://")

    slash_index = parts.path.rfind("/")
    if slash_index < 0:
        directory = ""
        filename = parts.path
    else:
        directory = parts.path[: slash_index + 1]
        filename = parts.path[slash_index + 1 :]

    match = IMAGE_NAME_RE.match(filename)
    if match is None:
        raise ValueError(
            "The URL filename must contain a page number and an extension, "
            "for example 00031.webp or page_0031.jpg"
        )

    number_text = match.group("number")
    return SequencePattern(
        original_url=url,
        scheme=parts.scheme,
        netloc=parts.netloc,
        directory=directory,
        prefix=match.group("prefix"),
        number_width=len(number_text),
        extension=match.group("extension"),
        query=parts.query,
        fragment=parts.fragment,
    )


def extract_jm_aid(url: str) -> Optional[int]:
    match = JM_PHOTO_PATH_RE.search(urlsplit(url).path)
    if match is None:
        return None
    return int(match.group("aid"))


def calculate_jm_segment_count(
    aid: int, filename_stem: str, scramble_id: int = DEFAULT_SCRAMBLE_ID
) -> int:
    """Calculate the horizontal stripe count used by JM image storage."""
    aid = int(aid)
    scramble_id = int(scramble_id)

    if aid < scramble_id:
        return 0
    if aid < JM_SCRAMBLE_268850:
        return 10

    modulo = 10 if aid < JM_SCRAMBLE_421926 else 8
    digest = hashlib.md5(
        "{}{}".format(aid, filename_stem).encode("utf-8")
    ).hexdigest()
    return (ord(digest[-1]) % modulo) * 2 + 2


def require_runtime() -> Tuple[Any, Any, Any, Any, Any]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            "Missing requests. Install it with: python -m pip install requests"
        ) from exc

    try:
        from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError(
            "Missing Pillow. Install it with: python -m pip install pillow"
        ) from exc

    return requests, Image, ImageChops, ImageOps, UnidentifiedImageError


def flatten_to_rgb(image: Any, Image: Any, ImageOps: Any) -> Any:
    transposed = ImageOps.exif_transpose(image)
    if transposed.mode == "RGB":
        return transposed.copy()

    if transposed.mode in ("RGBA", "LA") or "transparency" in transposed.info:
        rgba = transposed.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, (0, 0), rgba.getchannel("A"))
        rgba.close()
        return background

    return transposed.convert("RGB")


def restore_jm_stripes(image: Any, segment_count: int, Image: Any) -> Any:
    """Restore a page whose horizontal stripes are stored bottom-to-top."""
    if segment_count <= 1:
        return image.copy()

    width, height = image.size
    restored = Image.new("RGB", (width, height), "white")
    remainder = height % segment_count
    base_height = height // segment_count

    for index in range(segment_count):
        move = base_height
        source_y = height - (base_height * (index + 1)) - remainder
        destination_y = base_height * index

        if index == 0:
            move += remainder
        else:
            destination_y += remainder

        stripe = image.crop(
            (0, source_y, width, source_y + move)
        )
        restored.paste(stripe, (0, destination_y))
        stripe.close()

    return restored


def parse_extra_headers(values: Sequence[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for value in values:
        if ":" not in value:
            raise ValueError(
                "Invalid --header value {!r}; use 'Name: value'".format(value)
            )
        name, header_value = value.split(":", 1)
        name = name.strip()
        header_value = header_value.strip()
        if not name:
            raise ValueError("HTTP header name cannot be empty")
        headers[name] = header_value
    return headers


def response_is_known_missing(response: Any) -> bool:
    final_name = os.path.basename(urlsplit(response.url).path).lower()
    return final_name in {
        "404.jpg",
        "404.jpeg",
        "404.png",
        "404.webp",
        "notfound.jpg",
        "not-found.jpg",
    }


def fetch_image(
    session: Any,
    url: str,
    timeout: float,
    retries: int,
    requests: Any,
    Image: Any,
    ImageOps: Any,
    UnidentifiedImageError: Any,
) -> Tuple[Any, str]:
    last_error: Optional[BaseException] = None

    for attempt in range(retries + 1):
        try:
            response = session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
            )

            if response.status_code in (404, 410):
                raise SequenceEnded("HTTP {}".format(response.status_code))
            response.raise_for_status()

            if response_is_known_missing(response):
                raise SequenceEnded(
                    "redirected to {}".format(response.url)
                )

            content_type = response.headers.get("Content-Type", "").lower()
            if content_type.startswith("text/") or "html" in content_type:
                raise SequenceEnded(
                    "server returned {} instead of an image".format(
                        content_type or "text"
                    )
                )

            content = response.content
            if not content:
                raise SequenceEnded("empty response")

            expected_length = response.headers.get("Content-Length")
            content_encoding = response.headers.get("Content-Encoding")
            if expected_length and not content_encoding:
                try:
                    if int(expected_length) != len(content):
                        raise IOError(
                            "incomplete response: expected {} bytes, got {}".format(
                                expected_length, len(content)
                            )
                        )
                except ValueError:
                    pass

            try:
                with Image.open(BytesIO(content)) as opened:
                    opened.load()
                    decoded = flatten_to_rgb(opened, Image, ImageOps)
            except (UnidentifiedImageError, OSError) as exc:
                if content_type.startswith("text/") or "html" in content_type:
                    raise SequenceEnded("response is not an image") from exc
                raise IOError("downloaded data is not a complete image") from exc

            return decoded, response.url

        except SequenceEnded:
            raise
        except requests.RequestException as exc:
            last_error = exc
        except OSError as exc:
            last_error = exc

        if attempt < retries:
            wait_seconds = min(2.0 ** attempt, 8.0)
            print(
                "  Request failed; retrying in {:.0f}s ({}/{})".format(
                    wait_seconds, attempt + 1, retries
                )
            )
            time.sleep(wait_seconds)

    raise RuntimeError(
        "Failed to download {} after {} attempt(s): {}".format(
            url, retries + 1, last_error
        )
    )


def resolve_descramble_aid(args: argparse.Namespace, pattern: SequencePattern) -> Optional[int]:
    detected_aid = extract_jm_aid(pattern.original_url)

    if args.descramble == "none":
        return None
    if args.descramble == "auto":
        return detected_aid

    aid = args.jm_aid if args.jm_aid is not None else detected_aid
    if aid is None:
        raise ValueError(
            "--descramble jm requires /media/photos/<id>/ in the URL "
            "or an explicit --jm-aid"
        )
    return aid


def download_sequence(
    args: argparse.Namespace,
    pattern: SequencePattern,
    work_dir: Path,
    requests: Any,
    Image: Any,
    ImageOps: Any,
    UnidentifiedImageError: Any,
) -> List[Path]:
    session = requests.Session()
    headers = {
        "User-Agent": args.user_agent,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }

    jm_aid = resolve_descramble_aid(args, pattern)
    if args.referer:
        headers["Referer"] = args.referer
    elif jm_aid is not None:
        headers["Referer"] = DEFAULT_JM_REFERER
    headers.update(parse_extra_headers(args.header))
    session.headers.update(headers)

    page_paths: List[Path] = []
    current = args.start
    downloaded_count = 0
    reached_explicit_end = False

    while True:
        if args.end is not None and current > args.end:
            reached_explicit_end = True
            break
        if args.max_pages > 0 and downloaded_count >= args.max_pages:
            print(
                "Reached --max-pages={}; stopping as a safety limit.".format(
                    args.max_pages
                )
            )
            break

        page_url = pattern.url_for(current)
        page_label = pattern.filename_for(current)
        print("[{}] Downloading {}".format(current, page_url))

        try:
            image, final_url = fetch_image(
                session=session,
                url=page_url,
                timeout=args.timeout,
                retries=args.retries,
                requests=requests,
                Image=Image,
                ImageOps=ImageOps,
                UnidentifiedImageError=UnidentifiedImageError,
            )
        except SequenceEnded as exc:
            if not page_paths:
                raise RuntimeError(
                    "The first page {} could not be downloaded: {}".format(
                        page_url, exc
                    )
                )
            if args.end is not None:
                raise RuntimeError(
                    "The sequence ended at page {} before --end={}: {}".format(
                        current, args.end, exc
                    )
                )
            print("Sequence ended before page {}: {}".format(current, exc))
            break

        segment_count = 0
        if jm_aid is not None:
            filename_stem = os.path.splitext(page_label)[0]
            segment_count = calculate_jm_segment_count(
                aid=jm_aid,
                filename_stem=filename_stem,
                scramble_id=args.scramble_id,
            )
            if segment_count > 1:
                restored = restore_jm_stripes(image, segment_count, Image)
                image.close()
                image = restored

        page_path = work_dir / (str(current).zfill(pattern.number_width) + ".png")
        image.save(str(page_path), format="PNG")
        width, height = image.size
        image.close()
        page_paths.append(page_path)
        downloaded_count += 1

        restore_note = (
            ", restored {} stripes".format(segment_count)
            if segment_count > 1
            else ""
        )
        redirect_note = "" if final_url == page_url else ", final URL changed"
        print(
            "  Saved {} ({}x{}{}{})".format(
                page_path.name,
                width,
                height,
                restore_note,
                redirect_note,
            )
        )

        current += 1
        if args.delay > 0:
            time.sleep(args.delay)

    session.close()
    if not page_paths:
        raise RuntimeError("No images were downloaded")
    if reached_explicit_end:
        print("Reached --end={}.".format(args.end))
    return page_paths


def save_pages_pdf_with_pillow(
    page_paths: Sequence[Path], output_path: Path, dpi: int, Image: Any
) -> None:
    images: List[Any] = []
    try:
        for path in page_paths:
            with Image.open(str(path)) as opened:
                opened.load()
                images.append(opened.convert("RGB"))

        first = images[0]
        first.save(
            str(output_path),
            format="PDF",
            save_all=True,
            append_images=images[1:],
            resolution=float(dpi),
        )
    finally:
        for image in images:
            image.close()


def save_pages_pdf(
    page_paths: Sequence[Path], output_path: Path, dpi: int, Image: Any
) -> str:
    try:
        import img2pdf
    except ImportError:
        save_pages_pdf_with_pillow(page_paths, output_path, dpi, Image)
        return "Pillow"

    with output_path.open("wb") as output_stream:
        img2pdf.convert(
            *[str(path) for path in page_paths],
            outputstream=output_stream
        )
    return "img2pdf"


def resized_size(width: int, height: int, target_width: int) -> Tuple[int, int]:
    if width == target_width:
        return width, height
    target_height = max(1, int(round(height * target_width / float(width))))
    return target_width, target_height


def save_long_pdf(
    page_paths: Sequence[Path],
    output_path: Path,
    dpi: int,
    requested_width: Optional[int],
    max_long_pixels: int,
    Image: Any,
) -> int:
    dimensions: List[Tuple[int, int]] = []
    for path in page_paths:
        with Image.open(str(path)) as opened:
            dimensions.append(opened.size)

    target_width = requested_width or max(width for width, _ in dimensions)
    scaled_sizes = [
        resized_size(width, height, target_width)
        for width, height in dimensions
    ]
    total_height = sum(height for _, height in scaled_sizes)
    total_pixels = target_width * total_height

    if max_long_pixels > 0 and total_pixels > max_long_pixels:
        raise RuntimeError(
            "Long-page canvas would contain {:,} pixels, above the safety "
            "limit {:,}. Use --pdf-mode pages, set --long-width smaller, "
            "or raise --max-long-pixels.".format(
                total_pixels, max_long_pixels
            )
        )

    canvas = Image.new("RGB", (target_width, total_height), "white")
    y = 0
    try:
        for path, scaled in zip(page_paths, scaled_sizes):
            with Image.open(str(path)) as opened:
                page = opened.convert("RGB")
            if page.size != scaled:
                resized = page.resize(scaled, Image.Resampling.LANCZOS)
                page.close()
                page = resized
            canvas.paste(page, (0, y))
            y += page.height
            page.close()

        effective_dpi = max(
            dpi,
            int(math.ceil(target_width * 72.0 / MAX_PDF_PAGE_POINTS)),
            int(math.ceil(total_height * 72.0 / MAX_PDF_PAGE_POINTS)),
        )
        canvas.save(
            str(output_path),
            format="PDF",
            resolution=float(effective_dpi),
        )
        return effective_dpi
    finally:
        canvas.close()


def safe_file_stem(text: str) -> str:
    decoded = unquote(text).strip()
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", decoded).strip("._")
    return safe or "image_sequence"


def default_output_path(pattern: SequencePattern) -> Path:
    aid = extract_jm_aid(pattern.original_url)
    if aid is not None:
        stem = str(aid)
    else:
        parent_name = pattern.directory.rstrip("/").rsplit("/", 1)[-1]
        stem = safe_file_stem(parent_name)
    return Path("output") / "pdf" / (stem + ".pdf")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(
            "{}_{}{}".format(path.stem, index, path.suffix)
        )
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not find a free output filename")


def create_pdf(
    page_paths: Sequence[Path],
    output_path: Path,
    args: argparse.Namespace,
    Image: Any,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.pdf_mode == "pages":
        backend = save_pages_pdf(page_paths, output_path, args.dpi, Image)
        print("PDF backend: {}".format(backend))
    else:
        effective_dpi = save_long_pdf(
            page_paths=page_paths,
            output_path=output_path,
            dpi=args.dpi,
            requested_width=args.long_width,
            max_long_pixels=args.max_long_pixels,
            Image=Image,
        )
        print("Long-page PDF resolution: {} DPI".format(effective_dpi))


def scramble_for_self_test(image: Any, segment_count: int, Image: Any) -> Any:
    """Create a scrambled image that restore_jm_stripes must reverse."""
    width, height = image.size
    scrambled = Image.new("RGB", (width, height), "white")
    remainder = height % segment_count
    base_height = height // segment_count

    for index in range(segment_count):
        move = base_height
        source_y = height - (base_height * (index + 1)) - remainder
        destination_y = base_height * index
        if index == 0:
            move += remainder
        else:
            destination_y += remainder

        stripe = image.crop(
            (0, destination_y, width, destination_y + move)
        )
        scrambled.paste(stripe, (0, source_y))
        stripe.close()

    return scrambled


def run_self_test() -> None:
    _, Image, ImageChops, _, _ = require_runtime()

    pattern = parse_sequence_url(
        "https://cdn.example.test/media/photos/1439961/00031.webp?token=x"
    )
    assert pattern.url_for(1) == (
        "https://cdn.example.test/media/photos/1439961/00001.webp?token=x"
    )
    assert extract_jm_aid(pattern.original_url) == 1439961

    original = Image.new("RGB", (37, 53), "black")
    pixels = original.load()
    for y in range(original.height):
        color = ((y * 3) % 256, (y * 5) % 256, (y * 7) % 256)
        for x in range(original.width):
            pixels[x, y] = color

    try:
        for segment_count in (2, 10, 16):
            scrambled = scramble_for_self_test(original, segment_count, Image)
            restored = restore_jm_stripes(scrambled, segment_count, Image)
            difference = ImageChops.difference(original, restored)
            assert difference.getbbox() is None
            difference.close()
            restored.close()
            scrambled.close()

        with tempfile.TemporaryDirectory(prefix="image_sequence_self_test_") as temp:
            temp_path = Path(temp)
            pages: List[Path] = []
            for index, color in enumerate(("red", "green", "blue"), start=1):
                page_path = temp_path / "{:05d}.png".format(index)
                page = Image.new("RGB", (80, 120), color)
                page.save(str(page_path), "PNG")
                page.close()
                pages.append(page_path)

            pages_pdf = temp_path / "pages.pdf"
            save_pages_pdf(pages, pages_pdf, 150, Image)
            with pages_pdf.open("rb") as stream:
                assert stream.read(5) == b"%PDF-"

            long_pdf = temp_path / "long.pdf"
            save_long_pdf(
                pages,
                long_pdf,
                dpi=150,
                requested_width=None,
                max_long_pixels=1000000,
                Image=Image,
            )
            with long_pdf.open("rb") as stream:
                assert stream.read(5) == b"%PDF-"
    finally:
        original.close()

    print("Self-test passed: URL numbering, stripe restoration, and PDF output.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download a numbered image sequence from page 1 and export it "
            "as an ordered PDF. JM-style horizontal stripe scrambling is "
            "restored automatically for /media/photos/<id>/ URLs."
        )
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="URL of any image in the sequence, for example .../00031.webp",
    )
    parser.add_argument("-o", "--output", help="Output PDF path")
    parser.add_argument("--start", type=int, default=1, help="First page number")
    parser.add_argument("--end", type=int, help="Last page number, if known")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2000,
        help="Safety limit; use 0 for unlimited (default: 2000)",
    )
    parser.add_argument(
        "--descramble",
        choices=("auto", "jm", "none"),
        default="auto",
        help="Stripe restoration mode (default: auto)",
    )
    parser.add_argument(
        "--jm-aid",
        type=int,
        help="JM photo/chapter ID when it cannot be read from the URL",
    )
    parser.add_argument(
        "--scramble-id",
        type=int,
        default=DEFAULT_SCRAMBLE_ID,
        help="JM scramble threshold (default: 220980)",
    )
    parser.add_argument(
        "--pdf-mode",
        choices=("pages", "long"),
        default="pages",
        help="One image per PDF page, or one tall PDF page (default: pages)",
    )
    parser.add_argument("--dpi", type=int, default=150, help="PDF DPI")
    parser.add_argument(
        "--long-width",
        type=int,
        help="Pixel width used by --pdf-mode long",
    )
    parser.add_argument(
        "--max-long-pixels",
        type=int,
        default=300000000,
        help="Memory safety limit for long mode (default: 300000000)",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.05,
        help="Delay between successful downloads in seconds",
    )
    parser.add_argument("--referer", help="Custom HTTP Referer header")
    parser.add_argument(
        "--user-agent", default=DEFAULT_USER_AGENT, help="Custom User-Agent"
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Extra HTTP header as 'Name: value'; may be repeated",
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Keep restored PNG pages beside the output PDF",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the requested output path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the first five generated URLs without downloading",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run offline tests using generated color images only",
    )
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.self_test:
        return
    if not args.url:
        parser.error("url is required unless --self-test is used")
    if args.start < 0:
        parser.error("--start must be zero or greater")
    if args.end is not None and args.end < args.start:
        parser.error("--end must be greater than or equal to --start")
    if args.max_pages < 0:
        parser.error("--max-pages must be zero or greater")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.retries < 0:
        parser.error("--retries must be zero or greater")
    if args.delay < 0:
        parser.error("--delay must be zero or greater")
    if args.dpi <= 0:
        parser.error("--dpi must be greater than zero")
    if args.long_width is not None and args.long_width <= 0:
        parser.error("--long-width must be greater than zero")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)

    if args.self_test:
        run_self_test()
        return 0

    try:
        pattern = parse_sequence_url(args.url)
        resolve_descramble_aid(args, pattern)
        parse_extra_headers(args.header)
    except ValueError as exc:
        parser.error(str(exc))

    if args.dry_run:
        print("Input URL: {}".format(pattern.original_url))
        print("Generated sequence starts at:")
        for index in range(args.start, args.start + 5):
            if args.end is not None and index > args.end:
                break
            print("  {}".format(pattern.url_for(index)))
        jm_aid = resolve_descramble_aid(args, pattern)
        print(
            "Stripe restoration: {}".format(
                "JM auto (aid={})".format(jm_aid)
                if jm_aid is not None
                else "off"
            )
        )
        return 0

    output_path = (
        Path(args.output).expanduser()
        if args.output
        else default_output_path(pattern)
    )
    output_path = output_path.resolve()
    if output_path.suffix.lower() != ".pdf":
        output_path = output_path.with_suffix(".pdf")

    if output_path.exists() and not args.overwrite:
        output_path = unique_path(output_path)
        print("Output exists; using {}".format(output_path))

    try:
        requests, Image, _, ImageOps, UnidentifiedImageError = require_runtime()

        if args.keep_images:
            work_dir = output_path.parent / (output_path.stem + "_images")
            work_dir = unique_path(work_dir)
            work_dir.mkdir(parents=True, exist_ok=False)
            page_paths = download_sequence(
                args,
                pattern,
                work_dir,
                requests,
                Image,
                ImageOps,
                UnidentifiedImageError,
            )
            create_pdf(page_paths, output_path, args, Image)
            print("Restored images kept in: {}".format(work_dir))
        else:
            with tempfile.TemporaryDirectory(prefix="image_sequence_") as temp:
                work_dir = Path(temp)
                page_paths = download_sequence(
                    args,
                    pattern,
                    work_dir,
                    requests,
                    Image,
                    ImageOps,
                    UnidentifiedImageError,
                )
                create_pdf(page_paths, output_path, args, Image)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("PDF output was not created")

        print("Done: {} page(s)".format(len(page_paths)))
        print("PDF: {}".format(output_path))
        return 0
    except KeyboardInterrupt:
        print("Cancelled by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print("Error: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

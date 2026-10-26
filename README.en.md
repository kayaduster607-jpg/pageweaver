# PageWeaver

[简体中文](README.md) | [English](README.en.md)

**From one numbered image URL to a PDF with pages in order.**

Archive sequential images such as scanned pages and course handouts: derive subsequent URLs, validate images, normalize dimensions and orientation, and export a multipage PDF. The CLI can also retain PNG files or stitch a long page. A local web interface and CLI share downloading logic, with no model key or database.

[Install](#installation) · [First download](#first-download-preview-then-save) · [Web interface](#use-the-local-web-interface) · [Options](#option-reference) · [URL derivation](#derive-a-sequence-from-one-url) · [Troubleshooting](#common-issues)

## Installation

Prepare Python 3.11+. In Windows PowerShell:

```powershell
git clone https://github.com/kayaduster607-jpg/pageweaver.git
cd pageweaver
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run subsequent commands from the project root. On macOS / Linux, replace the virtual-environment interpreter with `.venv/bin/python`.

## First download: preview, then save

Input must be an **HTTP(S) URL that directly displays an image**, with a trailing page number in the filename, such as `page_0031.webp`. Article pages, reader pages, and existing PDF URLs are not suitable.

### Check numbering without network access

```powershell
.\.venv\Scripts\python.exe image_url_to_pdf.py "https://example.com/book/page_0031.webp" --dry-run --descramble none
```

This only derives addresses. It should print five URLs from `page_0001.webp` to `page_0005.webp` and create no PDF. **The default start is 1; 0031 in the sample determines number width only.** Add `--start 31` to begin at image 31.

### Replace the sample with a real image URL

The example.com URLs below do not host these images. Replace the whole URL with a source you are entitled to access, check the range, then download:

```powershell
.\.venv\Scripts\python.exe image_url_to_pdf.py "https://example.com/book/page_0001.webp" --start 1 --end 20 --descramble none --keep-images -o output/book.pdf
```

After normal completion, check:

```text
output/
├── book.pdf          # 一张图片对应一页
└── book_images/      # 保留下来的处理后 PNG
```

Existing files are not overwritten by default; use the final filename printed by the terminal. Open the PDF and check page count, order, and clarity. Stopping before a specified end page is a failure; a PDF appearing in the directory alone is insufficient.

### Choose another output form

| Goal | Download-command option |
| --- | --- |
| Start at a particular page | `--start 31` |
| Save only the multipage PDF | Remove `--keep-images` |
| Stitch one continuous page | `--pdf-mode long --long-width 1000` |
| Disable stripe restoration for ordinary images | `--descramble none` |
| Source requires Referer | `--referer "https://example.com/reader/"`, using the actual source page |

A long page requires a large canvas and more memory than a multipage PDF. Higher DPI does not add source pixels.

## Use the local web interface

```powershell
.\.venv\Scripts\python.exe image_to_pdf_server.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080), paste the same type of direct image URL, enter the starting number, and click “开始抓取” (start fetching). Watch thumbnails and fetched counts, then click “下载 PDF”. The browser saves `comic_<task_id>.pdf`.

The current web form produces multipage PDFs and has no end-page or long-page controls; use the CLI for exact ranges or long pages. Tasks live only in process memory and disappear on restart. “含错误 / 可能不完整” means the download contains only the earlier contiguous pages that succeeded.

## Downloading and image processing

![Number derivation, image validation, and PDF composition](docs/assets/pageweaver-flow.png)

Core functions are in [image_url_to_pdf.py](image_url_to_pdf.py); the web interface reuses URL parsing, fetching, and stripe restoration. Downloads are sequential, without parallel fetching, a persistent queue, or resumable transfers. See the [SVG](docs/assets/pageweaver-flow.svg) and [drawing source](tools/generate_architecture.py).

## Option reference

| Option | Default | Purpose |
| --- | --- | --- |
| `url` | Required except self-test | Direct URL of any image matching the numbering pattern |
| `-o` / `--output` | Generated | Output path; extension normalized to `.pdf` |
| `--start` | `1` | First number, including 0; does not inherit the sample's number |
| `--end` | Unspecified | Inclusive last number |
| `--max-pages` | `2000` | Maximum successfully downloaded images; 0 disables this limit |
| `--descramble` | `auto` | Stripe restoration: `auto`, `jm`, or `none` |
| `--jm-aid` | Autodetected | Manual chapter ID for forced JM mode |
| `--scramble-id` | `220980` | Starting threshold for stripe rules |
| `--pdf-mode` | `pages` | `pages` for multipage, `long` for one long page |
| `--dpi` | `150` | Base DPI for Pillow and long-page export; adds no pixels |
| `--long-width` | Maximum source width | Common long-page width in pixels |
| `--max-long-pixels` | `300000000` | Long-canvas pixel limit; 0 disables the check |
| `--timeout` | `20.0` | Requests network-wait parameter, seconds |
| `--retries` | `3` | Retries after the first request; up to 4 attempts by default |
| `--delay` | `0.05` | Seconds after each successful image |
| `--referer` | Mode-dependent | Custom source-page header |
| `--user-agent` | Built-in | Custom User-Agent |
| `--header` | Empty list | Repeatable `Name: value`; later values can override a same-name header |
| `--keep-images` | Off | Keep processed PNGs beside the PDF |
| `--overwrite` | Off | Permit PDF replacement; otherwise choose an unused filename |
| `--dry-run` | Off | Print at most the first 5 URLs without downloading |
| `--self-test` | Off | Offline self-test with synthetic images |

Without an output path, files normally go to `output/pdf/<directory name>.pdf`; recognized chapter paths use the chapter ID. Existing names gain a sequence suffix, and retained-image directories independently choose unused names.

`--max-pages` is a stopping condition, not proof of completeness. Once reached, acquired pages are composed even if the specified end is farther away. For a known range, set a sufficiently large limit and verify the actual final count.

## Derive a sequence from one URL

`parse_sequence_url()` accepts only HTTP(S), parsing a trailing “prefix + digits + extension” filename. For example:

```text
input:     https://example.com/book/page_0031.webp?sig=demo&v=2
prefix:    page_
width:     4
extension: .webp
start=1:   https://example.com/book/page_0001.webp?sig=demo&v=2
start=2:   https://example.com/book/page_0002.webp?sig=demo&v=2
```

`SequencePattern.filename_for()` zero-pads to the detected width. `url_for()` replaces the filename while retaining directory, query string, and fragment. Retaining signature parameters does not guarantee newly numbered URLs pass server validation; path-bound signatures still require valid source-provided addresses.

The program does not parse reader HTML, discover image lists, or infer cross-directory sequences, mixed extensions, skipped numbers, or random filenames. `page_0031.webp` supplies a template only; specify `--start 31` to start there.

## Validation and stopping rules

`fetch_image()` reuses connections through a Requests Session. Each image passes these checks:

1. **HTTP status:** 404 and 410 signal sequence end; other HTTP errors enter retry handling.
2. **Redirect result:** recognized common 404-placeholder filenames mean the image does not exist.
3. **Content type:** text / HTML is treated as non-image rather than saved as a page.
4. **Response length:** with Content-Length and no Content-Encoding, downloaded bytes must match; incomplete responses retry.
5. **Actual decoding:** Pillow opens the image and loads pixels; incomplete decoding cannot produce a normal page.

Retry waits are 1, 2, and 4 seconds, capped at 8 seconds for further attempts. Requests timeout limits network waits, not strict total task duration. See [Requests timeouts](https://docs.python-requests.org/en/latest/user/quickstart/#timeouts).

| Situation | CLI behavior | Web behavior |
| --- | --- | --- |
| First image missing / non-image | Fail without creating a PDF | Error, no valid PDF |
| No explicit end; later end signal | Stop normally and compose acquired pages | Same |
| Explicit end; earlier end signal | Fail without composing this run's PDF | Record error; earlier contiguous pages may still be downloadable |
| Network / decoding failure after retries | Fail without composing this run's PDF | Record error and retain the contiguous successful prefix |
| Image-count limit reached | Stop and compose acquired pages | Record limit notice and attempt composition |

Automatic end detection has limits: login and access-restriction pages can return HTML too. With unknown totals, a non-image response may be mistaken for the end. Specify `--end` for known ranges and check counts. Missing pages are not skipped to probe later numbers, and an openable PDF does not prove completeness.

## Image normalization and stripe restoration

### Normalize images for composition

Decoded images are oriented using EXIF and converted to RGB. RGBA and other transparent images are composited over white to avoid black transparent areas in PDFs. Intermediate PNGs preserve page order and support processing.

This does not perform OCR, translation, automatic margin cropping, or enhancement. PDFs primarily contain image pages without an automatically searchable text layer.

### Optional horizontal-stripe restoration

Some sources split pages into horizontal strips and store them in a particular order. `restore_jm_stripes()` crops and reorders strips according to their count, including remainder pixels when height is not divisible by that count. This restores pixel positions; it is not text recognition or cryptographic decryption.

Auto mode extracts a chapter ID from `/media/photos/<id>/` without separately checking site identity. An ordinary source with the same path pattern can trigger it; use CLI `--descramble none` in that case. The web form currently has no disable switch.

`calculate_jm_segment_count()` implements these rules:

| Condition | Current calculation |
| --- | --- |
| ID below scramble threshold | No restoration |
| ID at threshold but below 268850 | 10 strips |
| ID from 268850 to below 421926 | MD5-derived modulo-10 branch |
| ID from 421926 onward | MD5-derived modulo-8 branch |

Derivation concatenates chapter ID and filename stem, takes the character code of the last character of the MD5 hexadecimal string, and computes an even strip count. These are current code rules; revalidate if source storage changes. A matching path alone does not establish that restoration is appropriate.

## PDF layouts and resource use

### Multipage mode

`pages` composes in numeric order, one image per PDF page. The CLI prefers img2pdf and falls back to Pillow only when that module is missing. If installed img2pdf fails conversion, the CLI does not automatically fall back.

The web application requires img2pdf at startup but tries Pillow if img2pdf fails during composition. This does not mean img2pdf can be omitted from web dependencies.

In multipage img2pdf mode, the current function does not pass `--dpi` into layout settings; it mainly affects Pillow fallback and long-page output. Images have already been decoded and converted to PNG, so this is not unchanged embedding of original JPEG bytes or zero-conversion handling of arbitrary input. See [img2pdf](https://gitlab.mister-muffin.de/josch/img2pdf).

### Long-page mode

`long` chooses a common width, scales images proportionally, and stacks them on one vertical canvas. Effective DPI is increased at save time according to canvas dimensions so page sides stay within the code's 14400-point limit.

The default cap is 300 million pixels. The RGB canvas alone theoretically needs about 900 million bytes; peak use also includes decoded images, scaled copies, and encoding buffers. This is not a low-memory mode. Prefer multipage PDFs for many images or reduce `--long-width`.

### Storage

| Data | CLI | Web |
| --- | --- | --- |
| Download response | One complete response at a time | Same |
| Processed images | Temporary PNGs, optionally retained | In-memory PNGs for the task |
| Thumbnails | None | In-memory JPEG, at most 300x400 |
| Final PDF | Output path | In-memory bytes sent through download endpoint |
| Task records | Terminal logs | Process dictionary, no persistence or automatic expiry cleanup |

StreamingResponse sends an already generated PDF. **It does not mean images are encoded while being downloaded, or that the complete PDF never enters memory.** Each web task starts a thread without a shared concurrency cap or cancel endpoint. Process large workloads in batches; restart after downloading to clear memory state.

## Web tasks and API

### Request sequence

```text
Browser
  -> POST /api/start?url=...&start=1&end=20
  <- task_id + numbering template
  -> GET /api/status/{task_id}
  -> GET /api/thumb/{task_id}/{number}
  -> GET /api/download/{task_id}
```

`POST /api/start` takes **query parameters**, not a JSON body, matching the current FastAPI signature. See [FastAPI query parameters](https://fastapi.tiangolo.com/tutorial/query-params/).

Replace the image URL before actually executing this example:

```powershell
$imageUrl = [uri]::EscapeDataString("https://example.com/book/page_0001.png")
$task = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/start?url=$imageUrl&start=1&end=20"
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/status/$($task.task_id)"
```

Example startup response:

```json
{
  "task_id": "00000000000000000000000000000001",
  "template": "https://example.com/book/page_{:04d}.png",
  "num_len": 4,
  "ext": ".png",
  "descramble": "none"
}
```

It means only that the task thread started, not that images or PDF downloaded successfully. Immediately after creation, status may briefly return `not_found`; poll again.

### Routes and status fields

| Route | Purpose |
| --- | --- |
| `GET /` | Built-in webpage, no frontend build |
| `POST /api/start` | Create task; invalid image URL returns 400, invalid page range 422 |
| `GET /api/status/{task_id}` | State, current number, acquired-image information, errors |
| `GET /api/thumb/{task_id}/{num}` | Generated JPEG thumbnail, or 404 |
| `GET /api/download/{task_id}` | Composed PDF, or 404 if missing / not ready |

`current` is the page number recorded during processing. `images` contains successfully processed page numbers, dimensions, and strip counts. `total` updates mainly at task completion; during processing use `images` length rather than interpreting a temporary zero as no progress.

`done=true` means the task ended; **also inspect `error` and actual image count**. Partial web results display error / potentially incomplete download notes. Normal polling is about 800 ms, retrying after about 1500 ms on polling errors. There is no percentage because an unknown end gives no reliable total.

## Local-use boundaries

This tool assumes trusted local users. The web server listens on `127.0.0.1:8080` without accounts, API authentication, user isolation, or automatic task cleanup. It accepts HTTP(S) image URLs and follows redirects without complete internal-target and per-hop checks. Do not directly expose it as a public downloader.

The CLI accepts explicit extra headers but does not automatically read browser login state or grant access beyond your account. The web interface uses built-in headers and has no cookie-import form. Confirm permission before handling sources requiring login, access parameters, or Referer.

The public repository contains tool code, synthetic tests, and documentation only. Paper full text, personal data, downloads, captures, cookies, backups, and environment files are excluded. Process only materials you may access and save.

## Common issues

| Symptom | Cause / action |
| --- | --- |
| Filename must contain a page number | Use a numbered direct image URL, not a detail page, random filename, or PDF |
| Image 31 supplied, but download starts at 1 | The sample defines a pattern; set `--start 31` |
| First page returns 403 | Check required valid access parameters / headers; retries do not establish permission |
| Only the first few pages saved | Inspect missing pages, HTML responses, or limits; validate against a known end |
| Horizontal strips are scrambled | Check whether JM rules apply; use `--descramble none` for ordinary sources |
| Transparency becomes white | Transparent images are deliberately composited onto white RGB |
| Higher DPI is still blurry | DPI adds no pixels; img2pdf multipage mode does not use that layout parameter |
| Long-page pixel / memory error | Reduce `--long-width`, use multipage, or reduce page count |
| Downloadable web PDF reports errors | It contains only the earlier successful prefix, not a complete result |
| Tasks disappear after restart | Download needed PDFs first; state is memory-only |
| Web port occupied | Specify another loopback port with uvicorn and use it in the browser |

Example port change:

```powershell
.\.venv\Scripts\python.exe -m uvicorn image_to_pdf_server:app --host 127.0.0.1 --port 8081
```

## Verification and maintenance

```powershell
.\.venv\Scripts\python.exe image_url_to_pdf.py --self-test
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/verify.py
```

Self-tests create synthetic images and PDFs in temporary directories, then clean them up; they do not leave a readable book. Full verification needs Node.js and covers Python regression, web scripts, and PDF structure. See [docs/verification.md](docs/verification.md) for historical environments, scope, and network behavior offline tests cannot establish.

Prioritize sequence boundaries, error-page recognition, and web-task memory during maintenance. Keep headers, signed URLs, and downloaded personal materials out of the public repository.

"""
图片序列抓取 + PDF 合成 — Web 版本
启动: python image_to_pdf_server.py
然后浏览器打开 http://127.0.0.1:8080
"""

import io
import os
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlunsplit

import img2pdf
import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

try:
    from image_url_to_pdf import (
        DEFAULT_JM_REFERER,
        DEFAULT_USER_AGENT,
        SequenceEnded,
        calculate_jm_segment_count,
        extract_jm_aid,
        fetch_image,
        parse_sequence_url,
        restore_jm_stripes,
    )
except ImportError:
    # Keep compatibility with deployments using the alternate module name.
    from image_sequence_to_pdf import (
        DEFAULT_JM_REFERER,
        DEFAULT_USER_AGENT,
        SequenceEnded,
        calculate_jm_segment_count,
        extract_jm_aid,
        fetch_image,
        parse_sequence_url,
        restore_jm_stripes,
    )


HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Referer": DEFAULT_JM_REFERER,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
MAX_PAGES = 2000

app = FastAPI()
tasks: Dict[str, Dict[str, Any]] = {}
task_lock = threading.Lock()


def pattern_display(url: str) -> Tuple[str, str, int]:
    pattern = parse_sequence_url(url)
    placeholder = "{}{{:0{}d}}{}".format(
        pattern.prefix,
        pattern.number_width,
        pattern.extension,
    )
    template = urlunsplit(
        (
            pattern.scheme,
            pattern.netloc,
            pattern.directory + placeholder,
            pattern.query,
            pattern.fragment,
        )
    )
    return template, pattern.extension, pattern.number_width


def set_task_error(task_id: str, message: str) -> None:
    with task_lock:
        tasks[task_id]["error"] = message


def png_and_thumbnail(image: Any) -> Tuple[bytes, Optional[bytes]]:
    png_buffer = io.BytesIO()
    image.save(png_buffer, format="PNG")

    thumbnail_data: Optional[bytes] = None
    thumbnail = image.copy()
    try:
        thumbnail.thumbnail((300, 400))
        thumbnail_buffer = io.BytesIO()
        thumbnail.save(thumbnail_buffer, format="JPEG", quality=65)
        thumbnail_data = thumbnail_buffer.getvalue()
    finally:
        thumbnail.close()

    return png_buffer.getvalue(), thumbnail_data


def pdf_from_png_pages(pages: List[Tuple[int, bytes, Optional[bytes]]]) -> bytes:
    png_pages = [png for _, png, _ in pages]
    try:
        return img2pdf.convert(png_pages)
    except Exception:
        images: List[Any] = []
        try:
            for png in png_pages:
                with Image.open(io.BytesIO(png)) as opened:
                    opened.load()
                    images.append(opened.convert("RGB"))
            output = io.BytesIO()
            images[0].save(
                output,
                "PDF",
                save_all=True,
                append_images=images[1:],
                resolution=150.0,
            )
            return output.getvalue()
        finally:
            for image in images:
                image.close()


def download_task(
    task_id: str,
    source_url: str,
    start: int,
    end: Optional[int],
) -> None:
    """Download, validate, restore stripes, build thumbnails, then make PDF."""
    pattern = parse_sequence_url(source_url)
    jm_aid = extract_jm_aid(source_url)
    session = requests.Session()
    session.headers.update(HEADERS)
    pages: List[Tuple[int, bytes, Optional[bytes]]] = []
    current = start

    with task_lock:
        tasks[task_id] = {
            "status": "running",
            "images": [],
            "current": start,
            "done": False,
            "error": None,
            "pdf": None,
            "total": 0,
            "_thumbs": {},
        }

    try:
        while True:
            if end is not None and current > end:
                break
            if len(pages) >= MAX_PAGES:
                set_task_error(
                    task_id,
                    "已达到 {} 页安全上限；如确有更多页面，请使用命令行版调整 --max-pages。".format(
                        MAX_PAGES
                    ),
                )
                break

            page_url = pattern.url_for(current)
            try:
                image, _ = fetch_image(
                    session=session,
                    url=page_url,
                    timeout=30.0,
                    retries=3,
                    requests=requests,
                    Image=Image,
                    ImageOps=ImageOps,
                    UnidentifiedImageError=UnidentifiedImageError,
                )
            except SequenceEnded as exc:
                if not pages:
                    set_task_error(
                        task_id,
                        "第 {} 页不存在或不是图片: {}".format(current, exc),
                    )
                elif end is not None:
                    set_task_error(
                        task_id,
                        "图片在第 {} 页提前结束: {}".format(current, exc),
                    )
                break
            except Exception as exc:
                set_task_error(
                    task_id,
                    "下载第 {} 页失败，已停止；仅保留此前连续成功的页面: {}".format(
                        current, exc
                    ),
                )
                break

            segment_count = 0
            if jm_aid is not None:
                filename_stem = os.path.splitext(
                    pattern.filename_for(current)
                )[0]
                segment_count = calculate_jm_segment_count(
                    jm_aid,
                    filename_stem,
                )
                if segment_count > 1:
                    restored = restore_jm_stripes(
                        image,
                        segment_count,
                        Image,
                    )
                    image.close()
                    image = restored

            try:
                png_data, thumbnail_data = png_and_thumbnail(image)
                width, height = image.size
            finally:
                image.close()

            pages.append((current, png_data, thumbnail_data))
            with task_lock:
                tasks[task_id]["images"].append(
                    {
                        "num": current,
                        "width": width,
                        "height": height,
                        "segments": segment_count,
                    }
                )
                tasks[task_id]["current"] = current
                # Publish each thumbnail while downloading so live previews work.
                if thumbnail_data is not None:
                    tasks[task_id]["_thumbs"][current] = thumbnail_data

            current += 1

        pdf_bytes: Optional[bytes] = None
        if pages:
            try:
                pdf_bytes = pdf_from_png_pages(pages)
            except Exception as exc:
                set_task_error(task_id, "PDF 合成失败: {}".format(exc))

        thumbnail_map = {
            number: thumbnail
            for number, _, thumbnail in pages
            if thumbnail is not None
        }
        with task_lock:
            tasks[task_id]["pdf"] = pdf_bytes
            tasks[task_id]["total"] = len(pages)
            tasks[task_id]["_thumbs"] = thumbnail_map
    except Exception as exc:
        set_task_error(task_id, "任务失败: {}".format(exc))
    finally:
        session.close()
        with task_lock:
            tasks[task_id]["status"] = "done"
            tasks[task_id]["done"] = True


# --- API ---

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.post("/api/start")
def api_start(
    url: str,
    start: int = Query(default=1, ge=0),
    end: Optional[int] = Query(default=None, ge=0),
) -> Dict[str, Any]:
    # Reject an invalid range before starting a background task.
    if end is not None and end < start:
        raise HTTPException(status_code=422, detail="end must be >= start")
    try:
        template, extension, number_width = pattern_display(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task_id = uuid.uuid4().hex
    thread = threading.Thread(
        target=download_task,
        args=(task_id, url, start, end),
        daemon=True,
    )
    thread.start()
    return {
        "task_id": task_id,
        "template": template,
        "num_len": number_width,
        "ext": extension,
        "descramble": "jm" if extract_jm_aid(url) is not None else "none",
    }


@app.get("/api/status/{task_id}")
def api_status(task_id: str) -> Dict[str, Any]:
    with task_lock:
        task = tasks.get(task_id)
        if task is None:
            return {"status": "not_found"}
        return {
            "status": task["status"],
            "current": task["current"],
            "total": task.get("total", 0),
            "error": task["error"],
            "done": task["done"],
            "images": list(task["images"]),
        }


@app.get("/api/thumb/{task_id}/{num}")
def api_thumb(task_id: str, num: int) -> Any:
    with task_lock:
        task = tasks.get(task_id)
        if task is None:
            return HTMLResponse(status_code=404)
        thumbnail_data = task.get("_thumbs", {}).get(num)
    if thumbnail_data is None:
        return HTMLResponse(status_code=404)
    return StreamingResponse(
        io.BytesIO(thumbnail_data),
        media_type="image/jpeg",
    )


@app.get("/api/download/{task_id}")
def api_download(task_id: str) -> Any:
    with task_lock:
        task = tasks.get(task_id)
        if task is None or task.get("pdf") is None:
            return HTMLResponse("PDF not ready", status_code=404)
        pdf_data = task["pdf"]
    return StreamingResponse(
        io.BytesIO(pdf_data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=comic_{}.pdf".format(
                task_id
            )
        },
    )


# --- HTML ---

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PageWeaver - 图片序列转 PDF</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:#1a1a2e;color:#eee;min-height:100vh;
  display:flex;flex-direction:column;align-items:center;
}
.header{
  width:100%;background:#16213e;padding:20px;
  text-align:center;border-bottom:2px solid #0f3460;
}
.header h1{font-size:1.5rem;color:#e94560}
.form-box{
  margin-top:24px;display:flex;gap:12px;flex-wrap:wrap;
  justify-content:center;align-items:center;padding:0 20px;
}
.form-box input{
  padding:12px 16px;border:2px solid #0f3460;border-radius:8px;
  background:#16213e;color:#eee;font-size:14px;outline:none;
  transition:border .2s;
}
.form-box input:focus{border-color:#e94560}
#url-input{width:520px;max-width:85vw}
.start-num{width:80px;text-align:center}
.form-box button{
  padding:12px 28px;border:none;border-radius:8px;
  background:#e94560;color:#fff;font-size:14px;font-weight:600;
  cursor:pointer;transition:background .2s,transform .1s;
}
.form-box button:hover{background:#d63850}
.form-box button:active{transform:scale(.97)}
.form-box button:disabled{background:#555;cursor:not-allowed}
.progress{
  margin-top:16px;font-size:14px;color:#aaa;text-align:center;
  min-height:20px;
}
.progress code{color:#e94560;font-size:13px}
.gallery{
  display:flex;flex-wrap:wrap;gap:8px;
  justify-content:center;padding:20px;max-width:1240px;
}
.card{
  background:#16213e;border-radius:6px;overflow:hidden;
  width:150px;text-align:center;animation:fadeIn .3s ease;
}
.card img{width:100%;display:block;min-height:100px}
.card .label{padding:4px 0;font-size:12px;color:#aaa}
@keyframes fadeIn{
  from{opacity:0;transform:translateY(8px)}
  to{opacity:1;transform:translateY(0)}
}
#download-btn{
  margin:16px 0 40px;display:none;
}
#download-btn.show{display:inline-block}
.info-row{
  display:flex;gap:24px;font-size:13px;color:#888;margin-top:6px;
  flex-wrap:wrap;justify-content:center;
}
</style>
</head>
<body>
<div class="header">
  <h1>PageWeaver - 图片序列转 PDF</h1>
  <div class="info-row">
    <span>支持 .webp / .jpg / .png</span>
    <span>自动识别编号模式</span>
    <span>自动还原横条乱序</span>
    <span>从起始编号连续抓取</span>
  </div>
</div>

<div class="form-box">
  <input type="url" id="url-input"
    placeholder="输入任意一张图片的URL，例如 https://cdn-xxx.../00031.webp"
    value="">
  <input type="number" id="start-input" class="start-num" value="1" min="0">
  <button id="go-btn" onclick="startTask()">开始抓取</button>
</div>

<div class="progress" id="progress"></div>

<div class="gallery" id="gallery"></div>

<div style="text-align:center">
  <button class="form-box button" id="download-btn" onclick="downloadPdf()">下载 PDF</button>
</div>

<script>
let taskId = null;
let lastCount = 0;
let pollTimer = null;

async function startTask() {
  const url = document.getElementById('url-input').value.trim();
  const parsedStart = parseInt(document.getElementById('start-input').value, 10);
  const start = Number.isInteger(parsedStart) ? parsedStart : 1;
  if (!url) return alert('请输入URL');

  document.getElementById('gallery').innerHTML = '';
  document.getElementById('progress').textContent = '正在初始化...';
  document.getElementById('download-btn').classList.remove('show');
  document.getElementById('go-btn').disabled = true;
  lastCount = 0;

  try {
    const params = new URLSearchParams({ url, start });
    const resp = await fetch('/api/start?' + params, { method: 'POST' });
    const data = await resp.json();
    taskId = data.task_id;
    const restoreMode = data.descramble === 'jm' ? ' | 横条还原: 已启用' : '';
    // Treat a user-controlled URL template as text, never as HTML.
    document.getElementById('progress').textContent =
      '模板: ' + data.template + ' | 从第 ' + start + ' 张开始抓取...' + restoreMode;
    pollTask();
  } catch (e) {
    document.getElementById('progress').textContent = '请求失败: ' + e;
    document.getElementById('go-btn').disabled = false;
  }
}

async function pollTask() {
  if (!taskId) return;
  try {
    const resp = await fetch('/api/status/' + taskId);
    const data = await resp.json();

    const gallery = document.getElementById('gallery');
    const newImages = data.images.slice(lastCount);
    for (const img of newImages) {
      const card = document.createElement('div');
      card.className = 'card';
      card.id = 'card-' + img.num;
      const src = '/api/thumb/' + taskId + '/' + img.num;
      const dims = img.width + 'x' + img.height;
      const restored = img.segments > 1 ? ' | 复原' + img.segments + '条' : '';
      card.innerHTML = '<img src="' + src + '" loading="lazy" onerror="this.parentElement.style.opacity=0.4">'
        + '<div class="label">#' + String(img.num).padStart(5,'0')
        + ' <span style="font-size:11px">' + dims + restored + '</span></div>';
      gallery.appendChild(card);
    }
    lastCount = data.images.length;

    if (data.done) {
      document.getElementById('progress').textContent =
        (data.error ? '任务结束（含错误）' : '完成') + '，共获取 ' + data.total + ' 张图片';
      document.getElementById('go-btn').disabled = false;
      if (data.total > 0) {
        document.getElementById('download-btn').classList.add('show');
        document.getElementById('download-btn').textContent =
          data.error ? '下载已获取页面（可能不完整）' : '下载 PDF';
      }
      if (data.error) {
        document.getElementById('progress').textContent += ' | 错误: ' + data.error;
      }
      return;
    }

    document.getElementById('progress').innerHTML =
      '抓取中... 已获取 <span style="color:#e94560;font-weight:bold">' + data.images.length
      + '</span> 张 (当前 #' + data.current + ')';
    pollTimer = setTimeout(pollTask, 800);
  } catch (e) {
    pollTimer = setTimeout(pollTask, 1500);
  }
}

function downloadPdf() {
  if (!taskId) return;
  const a = document.createElement('a');
  a.href = '/api/download/' + taskId;
  a.download = 'comic_' + taskId + '.pdf';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
</script>
</body>
</html>"""

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)

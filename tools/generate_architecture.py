"""Render one shared diagram model to a crisp PNG and editable SVG."""

from html import escape
from pathlib import Path
import os

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SIZE = (1600, 960)
BACKGROUND = "#F6F7FA"
INK = "#142237"
MUTED = "#526277"
BLUE = "#245FE8"
FONT = Path(os.environ.get("PAGEWEAVER_DIAGRAM_FONT", r"C:\Windows\Fonts\msyh.ttc"))


class Canvas:
    """Keep vector and bitmap geometry in sync instead of drawing twice by hand."""

    def __init__(self):
        self.image = Image.new("RGB", SIZE, BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="960" viewBox="0 0 1600 960">',
                    f'<rect width="1600" height="960" fill="{BACKGROUND}"/>']

    def rectangle(self, box, fill, outline=None, radius=20):
        x1, y1, x2, y2 = box
        self.draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)
        stroke = f' stroke="{outline}" stroke-width="2"' if outline else ""
        self.svg.append(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" rx="{radius}" fill="{fill}"{stroke}/>')

    def text(self, position, value, size=25, fill=INK):
        x, y = position
        font = ImageFont.truetype(str(FONT), size)
        self.draw.text(position, value, font=font, fill=fill, anchor="lt")
        self.svg.append(f'<text x="{x}" y="{y}" dominant-baseline="text-before-edge" font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" font-size="{size}" fill="{fill}">{escape(value)}</text>')

    def line(self, points, color=BLUE, width=3, arrow=False):
        self.draw.line(points, fill=color, width=width, joint="curve")
        self.svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{width}"/>')
        if arrow:
            x, y = points[-1]
            polygon = [(x, y), (x - 11, y - 6), (x - 11, y + 6)]
            self.draw.polygon(polygon, fill=color)
            self.svg.append(f'<polygon points="{" ".join(f"{a},{b}" for a,b in polygon)}" fill="{color}"/>')


def entry(canvas, box, label, title, detail):
    x, y, _, _ = box
    canvas.rectangle(box, "#FFFFFF", "#DCE2EC")
    canvas.text((x + 26, y + 24), label, 18, BLUE)
    canvas.text((x + 26, y + 62), title, 29)
    canvas.text((x + 26, y + 110), detail, 21, MUTED)


def draw_diagram():
    canvas = Canvas()
    canvas.text((72, 48), "PAGEWEAVER / SYSTEM MAP", 19, BLUE)
    canvas.text((70, 93), "把连续的图片，编织成一本 PDF", 48)
    canvas.text((73, 172), "两个本地入口，共用一套编号、下载与图像处理逻辑。", 25, MUTED)
    canvas.text((72, 247), "01  INPUT", 18, MUTED)
    canvas.text((526, 247), "02  SHARED PIPELINE", 18, MUTED)
    canvas.text((1184, 247), "03  OUTPUT", 18, MUTED)
    entry(canvas, (70, 288, 400, 468), "COMMAND LINE", "命令行任务", "范围 / 重试 / 保留图片")
    entry(canvas, (70, 506, 400, 686), "LOCAL WEB :8080", "浏览器操作", "进度 / 缩略图 / 下载")
    canvas.rectangle((520, 288, 1055, 686), "#142237")
    stages = [("01", "识别编号规则", "前缀、补零位数、扩展名与查询串"),
              ("02", "下载并验证响应", "状态码 / 长度 / 图片解码 / 重试"),
              ("03", "统一图像与可选还原", "EXIF校正 / RGB / 横条排列恢复"),
              ("04", "按编号保留页面", "CLI临时PNG / Web内存PNG")]
    for index, (number, title, detail) in enumerate(stages):
        y = 315 + index * 91
        canvas.text((550, y + 4), number, 18, "#92B7FF")
        canvas.text((600, y), title, 27, "#FFFFFF")
        canvas.text((600, y + 42), detail, 19, "#B8C8E0")
    entry(canvas, (1180, 288, 1530, 468), "PAGES / CLI + WEB", "多页 PDF", "每张图片对应一页")
    entry(canvas, (1180, 506, 1530, 686), "LONG PAGE / CLI", "长页 PDF", "统一宽度后纵向拼接")
    canvas.line([(400, 378), (460, 378), (460, 487), (520, 487)], arrow=True)
    canvas.line([(400, 596), (460, 596), (460, 487)])
    canvas.line([(1055, 487), (1118, 487), (1118, 378), (1180, 378)], arrow=True)
    canvas.line([(1118, 487), (1118, 596), (1180, 596)], arrow=True)
    canvas.rectangle((70, 756, 1530, 891), "#EAF0FC", radius=14)
    canvas.text((100, 782), "LOCAL BY DESIGN", 18, BLUE)
    canvas.text((100, 823), "输入是有权访问的图片直链。无需模型 API Key；网页任务随服务重启清空。", 25)
    return canvas


def main():
    if not FONT.is_file():
        raise SystemExit("Set PAGEWEAVER_DIAGRAM_FONT to a CJK TrueType font path.")
    canvas = draw_diagram()
    assets = ROOT / "docs/assets"
    assets.mkdir(parents=True, exist_ok=True)
    canvas.image.save(assets / "pageweaver-flow.png")
    (assets / "pageweaver-flow.svg").write_text("\n".join(canvas.svg + ["</svg>"]), encoding="utf-8")
    print("Generated architecture PNG and SVG.")


if __name__ == "__main__":
    main()

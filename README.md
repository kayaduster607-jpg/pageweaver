# PageWeaver

**给出一张带编号的图片直链，把连续页面下载、整理并合成为 PDF。**

Python 3.11+ / Requests / Pillow / img2pdf / FastAPI

[快速开始](#3-快速开始) | [命令行](#4-命令行用法) | [实现原理](#5-从一条链接推导整组图片) | [图片处理](#7-图像归一化与横条还原) | [网页接口](#9-网页任务与-api) | [故障排查](#11-常见问题) | [验证](#12-验证与代码导航)

PageWeaver 是一个本地图片序列归档工具。面对扫描页、课程讲义或其他有权保存的图片资料，只要图片地址遵循连续编号规则，就可以从一条样例链接生成后续地址，检查每张响应，按页码组织内容，最后导出多页 PDF 或单张长页 PDF。

项目提供**命令行和本地网页两个入口，共用下载与图像处理逻辑**。命令行适合明确页码范围、调整请求头和批量执行；网页适合粘贴链接、查看进度及缩略图后下载。基础功能不使用大模型，不需要模型 API Key，也不要求外部数据库。

输入应当是**图片文件的 HTTP(S) 直链**，例如 `https://example.com/book/page_0031.webp`，不是文章页面、论文详情页或现成 PDF 链接。示例域名与参数只用于说明，请替换成自己的合法来源。

## 先用一次：输入什么图片链接，输出哪一个PDF

| 入口 | 输入 | 输出 |
| --- | --- | --- |
| 命令行 | 任意一张末尾带编号的图片直链，加起止页和PDF路径 | 指定路径的多页PDF；可选长页、PNG目录 |
| 本地网页 | 图片直链和起始编号 | 浏览器下载的 `comic_<task_id>.pdf` |
| `--dry-run` | 一条符合编号格式的示例URL | 终端打印前5个待访问地址，不联网、不生成PDF |

### 无需真实网站，先确认自己理解了输入规则

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 image_url_to_pdf.py "https://example.com/book/page_0031.png" --dry-run --descramble none
```

你会看到从 `page_0001.png` 到 `page_0005.png` 的地址，而不是从31开始。样例链接只用于推导编号模板；要从31开始，显式加 `--start 31`。

### 真正下载一组有权访问的图片

1. 按[快速开始](#3-快速开始)安装依赖，找到真实来源的一张图片直链。把链接在浏览器打开后，应直接显示图片，而不是文章/阅读器页面。
2. 先用dry-run检查生成的页码、前缀和扩展名。已知总页数时写清 `--end`；普通图片使用 `--descramble none`。
3. 下载命令格式如下。必须把example.com地址换成你的真实来源；该示例域名不提供这些图片。

```powershell
.\.venv\Scripts\python.exe -X utf8 image_url_to_pdf.py "https://example.com/book/page_0001.png" --start 1 --end 20 --descramble none --keep-images -o output/book.pdf
```

4. 正常完成后，打开 `output/book.pdf`；PNG位于PDF旁的 `book_images` 目录。路径已存在时程序可能增加序号，最终位置以终端打印为准。
5. 想用网页时启动 `image_to_pdf_server.py`，访问 `http://127.0.0.1:8080`，输入同类链接后抓取，结束后点击“下载 PDF”。网页默认只输出多页PDF，不提供长页选项。

**确认成功：**页数应符合实际范围，每页图片能够打开。网页出现“含错误/可能不完整”时，拿到的可能只是已成功获取的前缀页面。`--self-test`生成的是临时测试PDF，检查后会清理，不会给你留一份待阅读的书籍文件。

## 1. 为什么做这个工具

逐张保存一组图片时，真正容易出错的地方不只是下载：补零编号可能丢失，错误页可能被保存成图片，页面可能存在横条乱序，不同尺寸和透明背景也会影响合成结果。PageWeaver 将这些步骤连成一条可检查的流程。

| 问题 | 具体处理 |
| --- | --- |
| 从第31张拿到链接，却想从第1张开始 | 保留文件名前缀、编号宽度与扩展名，默认从1生成序列 |
| 查询串中有访问参数 | 更换文件编号时保留原查询串的顺序与编码，不自行重排 |
| 请求成功，但下载到的是错误页 | 检查HTTP状态、常见占位图文件名、内容类型、响应长度和图片解码 |
| 网络偶发失败 | 超时与下载异常按次数重试，采用退避等待 |
| 已知总页数，不能接受中途少页 | 命令行可指定结束页，提前结束时报告失败 |
| 某类图片按横条逆序存储 | 识别指定路径规则，可选恢复横条排列 |
| 想像翻书一样阅读 | 每张图片对应一页PDF |
| 想连续向下阅读 | 命令行统一图片宽度，拼接为一张长页PDF |

### 两个入口的能力差别

| 能力 | 命令行 | 本地网页 |
| --- | --- | --- |
| 输入样例图片URL、自动编号 | 支持 | 支持 |
| 起始页 | `--start`，默认1，允许0 | 表单输入，默认1，允许0 |
| 结束页 | `--end` | API支持 `end`；当前表单未提供该输入框 |
| 多页PDF | 支持 | 支持 |
| 单张长页PDF | 支持 | 当前未提供 |
| 自定义请求头、超时与重试 | 提供参数 | 使用代码内的固定配置 |
| 横条还原开关和参数 | 可调整 | 根据路径自动选择 |
| 保留处理后的PNG | `--keep-images` | 无独立图片导出入口 |
| 页面缩略图与任务进度 | 终端日志 | 网页展示 |

## 2. 架构与数据流

![PageWeaver架构与图片处理流程](docs/assets/pageweaver-flow.png)

[查看可编辑SVG](docs/assets/pageweaver-flow.svg)。图像由仓库内的[绘图脚本](tools/generate_architecture.py)生成，不依赖远程图床或Mermaid渲染。

核心逻辑集中在 [image_url_to_pdf.py](image_url_to_pdf.py)。网页入口 [image_to_pdf_server.py](image_to_pdf_server.py) 复用其中的URL解析、图片抓取和横条还原函数，再加入后台线程、任务状态、缩略图与下载接口。

```text
Sample image URL
  -> parse_sequence_url()
  -> SequencePattern.url_for(page_number)
  -> fetch_image()
  -> EXIF correction + RGB normalization
  -> optional stripe restoration
  -> ordered PNG pages
  -> pages PDF / long-page PDF
```

命令行将处理后的PNG放在临时目录，合成完成后清理；网页把图片、缩略图和PDF保存在进程内存里。当前下载按页顺序执行，**没有并行下载、持久化任务队列或断点续传的实现**。

## 3. 快速开始

### 3.1 安装

当前发布依赖要求 **Python 3.11或更新版本**，已在Windows、Python 3.13.5验证。原始核心脚本使用较早的Python语法，但不能据此认为本次固定依赖也兼容Python 3.9。Node.js仅用于网页脚本测试，运行下载器不需要安装Node。

PowerShell中执行：

```powershell
git clone https://github.com/kayaduster607-jpg/pageweaver.git
cd pageweaver
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

不需要创建环境文件或填写模型密钥。源码没有自动读取项目环境文件的配置步骤。

### 3.2 先预览编号，再真正下载

下面的预览只打印地址，不联网，也不下载图片：

```powershell
.\.venv\Scripts\python.exe image_url_to_pdf.py "https://example.com/book/page_0031.webp" --dry-run
```

默认打印从 `page_0001.webp` 开始的前5条地址。确认编号规则后，将示例替换为实际图片直链，明确范围下载：

```powershell
.\.venv\Scripts\python.exe image_url_to_pdf.py "https://example.com/book/page_0031.webp" --start 1 --end 20 --descramble none -o output/book.pdf
```

这里用 `--descramble none` 表示普通图片不执行横条还原。图片编号范围和文件名必须与实际来源一致。

### 3.3 启动本地网页

```powershell
.\.venv\Scripts\python.exe image_to_pdf_server.py
```

打开 [http://127.0.0.1:8080](http://127.0.0.1:8080)，输入图片直链与起始编号，点击“开始抓取”。也可以双击 [start_server.bat](start_server.bat)，启动脚本会优先选择本目录的虚拟环境。

服务只监听本机回环地址。任务结束后，核对总张数与错误提示，再下载PDF。若显示“可能不完整”，下载得到的是此前成功获取的连续页面，不能当成整组资料已经完整抓取。

## 4. 命令行用法

### 4.1 常见操作

从指定页开始，一直抓到检测到序列结束：

```powershell
python image_url_to_pdf.py "https://example.com/book/page_0031.webp" --start 31 --descramble none -o output/book.pdf
```

明确下载范围，同时保留处理后的PNG：

```powershell
python image_url_to_pdf.py "https://example.com/book/00001.jpg" --start 1 --end 80 --keep-images --descramble none -o output/book.pdf
```

生成长页PDF，限制拼接宽度：

```powershell
python image_url_to_pdf.py "https://example.com/book/00001.png" --end 20 --pdf-mode long --long-width 1000 --descramble none -o output/book-long.pdf
```

为自己有权访问的来源提供Referer，并调整网络等待：

```powershell
python image_url_to_pdf.py "https://example.com/book/00001.webp" --end 20 --referer "https://example.com/reader/" --timeout 30 --retries 4 --delay 0.2 --descramble none
```

以上短命令假设当前Python环境已安装依赖；未激活虚拟环境时，请将 `python` 换成 `.\.venv\Scripts\python.exe`。不要把真实Cookie、访问令牌或带签名的完整链接放进公开命令样例、截图和Issue。

### 4.2 参数说明

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `url` | 必填，自测除外 | 任意一张符合编号规则的图片直链 |
| `-o` / `--output` | 自动生成 | 指定PDF路径；扩展名会统一为 `.pdf` |
| `--start` | `1` | 从哪个编号开始，允许0；不会自动采用样例图的编号 |
| `--end` | 未指定 | 最后编号，包含该页 |
| `--max-pages` | `2000` | 最多成功下载的图片数；0表示不设此上限 |
| `--descramble` | `auto` | `auto`、`jm`、`none` 三种横条还原模式 |
| `--jm-aid` | 自动识别 | 强制JM模式时可手动提供章节ID |
| `--scramble-id` | `220980` | 横条排列规则的起始阈值 |
| `--pdf-mode` | `pages` | `pages`多页，`long`单张长页 |
| `--dpi` | `150` | Pillow导出与长页的基础DPI；不会增加图像像素 |
| `--long-width` | 源图最大宽度 | 长页统一宽度，单位像素 |
| `--max-long-pixels` | `300000000` | 长页画布像素上限；0关闭这项检查 |
| `--timeout` | `20.0` | Requests网络等待参数，单位秒 |
| `--retries` | `3` | 首次请求以外的重试次数；默认最多4次尝试 |
| `--delay` | `0.05` | 每张成功下载后的等待，单位秒 |
| `--referer` | 按模式选择 | 自定义来源页请求头 |
| `--user-agent` | 内置值 | 自定义User-Agent |
| `--header` | 空列表 | 可重复传入 `Name: value`，后写入的值可覆盖同名头 |
| `--keep-images` | 关闭 | 在PDF旁保留处理后的PNG目录 |
| `--overwrite` | 关闭 | 允许覆盖PDF；否则自动选择未占用文件名 |
| `--dry-run` | 关闭 | 打印起始的最多5条地址，不下载 |
| `--self-test` | 关闭 | 使用合成图片执行离线自测 |

没有指定输出路径时，一般保存到 `output/pdf/<目录名>.pdf`；可识别的章节路径则使用章节ID命名。文件名已存在时会增加序号，保留图片目录也会独立选择未占用名称。

`--max-pages`是停止条件，不是完整性证明：达到上限后会合成已经获取的页面，即使指定的结束页更远也不会继续下载。对于已知范围，应使该上限覆盖预期页数，并核对最后的实际页数。

## 5. 从一条链接推导整组图片

`parse_sequence_url()`只接受HTTP(S)地址，解析末尾的“前缀 + 数字 + 扩展名”。例如：

```text
input:     https://example.com/book/page_0031.webp?sig=demo&v=2
prefix:    page_
width:     4
extension: .webp
start=1:   https://example.com/book/page_0001.webp?sig=demo&v=2
start=2:   https://example.com/book/page_0002.webp?sig=demo&v=2
```

`SequencePattern.filename_for()`用数字宽度补零；`url_for()`替换文件名，保留目录、查询串和fragment。保留已有签名参数并不保证新编号的URL也通过服务端校验；若签名按文件路径绑定，仍需来源端提供有效地址。

当前不解析阅读器HTML，不自动查找图片列表，也不推断跨目录、混合扩展名、跳号或随机文件名。给出 `page_0031.webp` 只是提供编号模板，程序默认从1开始；想接着31下载必须明确写 `--start 31`。

## 6. 下载校验与停止规则

`fetch_image()`通过Requests Session复用连接。每张图片要经过以下检查：

1. **HTTP状态。** 404或410作为序列结束信号；其他HTTP错误进入异常处理与重试。
2. **重定向结果。** 最终文件名若是内置的常见404占位图名称，视为不存在。
3. **内容类型。** 文本或HTML响应被视为非图片，不当作正常页面保存。
4. **响应长度。** 有Content-Length且没有Content-Encoding时，比较下载字节数；不完整响应重试。
5. **真实解码。** 由Pillow打开并加载像素，不能完整解码的数据不会成为正常页面。

失败重试的等待依次为1、2、4秒，继续增加时上限为8秒。Requests的timeout约束网络等待，并非严格的整项任务总时长。[Requests超时说明](https://docs.python-requests.org/en/latest/user/quickstart/#timeouts)

| 情况 | 命令行行为 | 网页行为 |
| --- | --- | --- |
| 第一张就不存在或返回非图片 | 失败，不生成PDF | 任务含错误，无有效PDF |
| 未指定结束页，后续出现结束信号 | 正常停止，合成已有页面 | 正常结束，合成已有页面 |
| 指定结束页，但提前遇到结束信号 | 失败，不合成本次PDF | 记录错误，仍可能提供此前连续页面的PDF |
| 网络或解码失败，重试耗尽 | 失败，不合成本次PDF | 记录错误，保留此前连续成功部分 |
| 达到图片数上限 | 停止并合成已有页面 | 记录上限提示，再尝试合成已有页面 |

“自动判断结束”存在边界：登录页、访问限制页也可能返回HTML。因此未知总页数时，非图片响应可能被当成结束；已知范围应指定 `--end`，并核对输出张数。程序不会跳过缺失页继续尝试后面的编号，也不能单凭PDF成功打开证明资料完整。

## 7. 图像归一化与横条还原

### 7.1 先统一可合成的图像格式

图片解码后先依据EXIF调整方向，再统一成RGB。RGBA等带透明通道的图片会放到白色背景上，减少透明区域在PDF里变黑的情况。中间结果使用PNG，便于保持页面顺序和继续处理。

这一步不会执行OCR、翻译、自动裁白边或画质增强，生成的PDF主要是图像页面，不自动获得可搜索的文字层。

### 7.2 可选的横条排列恢复

部分来源将一页切成若干水平条带，按特定顺序保存。`restore_jm_stripes()`根据条带数重新裁切与排列，并处理图像高度不能整除条带数的余数。它恢复的是像素条带位置，不是文字识别或密码学解密。

当前自动模式根据路径 `/media/photos/<id>/` 提取章节ID，不同时验证站点身份。普通来源恰好使用相似路径时，也可能触发自动规则；这时应使用命令行 `--descramble none`。网页当前未提供关闭开关。

条带数量规则由 `calculate_jm_segment_count()`实现：

| 条件 | 当前计算方式 |
| --- | --- |
| ID小于scramble阈值 | 不还原 |
| ID达到阈值但小于268850 | 使用10条 |
| ID从268850起且小于421926 | MD5派生，使用模10的分支 |
| ID从421926起 | MD5派生，使用模8的分支 |

派生输入为章节ID与图片文件名主干的连接，取MD5十六进制结果最后一个字符的字符码，计算偶数条带数量。这里记录的是现有代码规则；来源改变存储方式后，需要重新验证，不能保证所有带该路径的图片都应套用它。

## 8. 两种PDF布局与资源占用

### 8.1 多页模式

`pages`按编号顺序合成，每张图对应一个PDF页面。命令行优先使用img2pdf；缺少该模块时才回退到Pillow。命令行中img2pdf已经安装但转换报错时，不会自动转入Pillow分支。

网页启动时依赖img2pdf包；合成过程中若img2pdf失败，会再尝试Pillow。这与“网页可以不安装img2pdf”是两回事。

多页模式使用img2pdf时，当前函数没有将 `--dpi` 传入布局设置；该参数主要影响Pillow回退和长页导出。整个流程已经将图片解码并转成PNG，因此不宣称“原始JPEG字节原样嵌入”或“任意输入零转换”。[img2pdf项目说明](https://gitlab.mister-muffin.de/josch/img2pdf)

### 8.2 长页模式

`long`先选择统一宽度，等比例缩放每页，再依次贴到同一张纵向画布上。为避免PDF单页尺寸过大，保存时会按画布尺寸提高有效DPI，使页面边长不超过代码中的14400点限制。

默认长页上限是3亿像素。仅RGB画布理论上就约需9亿字节，实际峰值还包含解码图、缩放副本和编码缓冲；这不是小内存模式。图片较多时，优先多页PDF，或通过 `--long-width` 缩小宽度。

### 8.3 数据保存在哪里

| 数据 | 命令行 | 网页 |
| --- | --- | --- |
| 下载响应 | 每次读取一张完整响应 | 每次读取一张完整响应 |
| 处理后的图片 | 临时PNG；可选择永久保留 | 本次任务的内存PNG |
| 缩略图 | 无 | 内存JPEG，最大300x400 |
| 最终PDF | 输出路径 | 内存字节，通过下载接口发送 |
| 任务记录 | 终端日志 | 进程内字典，无持久化和自动过期清理 |

网页使用StreamingResponse发送已生成的PDF，**不表示图片边下载边编码成PDF，也不表示完整PDF从未进入内存**。当前网页每个任务启动一个线程，没有统一并发上限或取消接口；大量或大型任务应分批处理，结束后重启服务可清空内存状态。

## 9. 网页任务与 API

### 9.1 请求顺序

```text
Browser
  -> POST /api/start?url=...&start=1&end=20
  <- task_id + numbering template
  -> GET /api/status/{task_id}
  -> GET /api/thumb/{task_id}/{number}
  -> GET /api/download/{task_id}
```

`POST /api/start`使用**查询参数**，不是JSON请求体。这与当前FastAPI函数签名一致。[FastAPI查询参数说明](https://fastapi.tiangolo.com/tutorial/query-params/)

下面是调用格式示例，真实执行前必须更换图片地址：

```powershell
$imageUrl = [uri]::EscapeDataString("https://example.com/book/page_0001.png")
$task = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/start?url=$imageUrl&start=1&end=20"
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/status/$($task.task_id)"
```

启动成功的响应示意：

```json
{
  "task_id": "00000000000000000000000000000001",
  "template": "https://example.com/book/page_{:04d}.png",
  "num_len": 4,
  "ext": ".png",
  "descramble": "none"
}
```

这个响应只表示任务线程已经启动，不代表图片或PDF已经下载成功。任务刚创建时，状态接口也可能短暂返回 `not_found`，随后再轮询。

### 9.2 路由和状态字段

| 路由 | 作用 |
| --- | --- |
| `GET /` | 内置网页，不需要前端打包 |
| `POST /api/start` | 创建任务；无效图片URL返回400，无效页码范围返回422 |
| `GET /api/status/{task_id}` | 当前状态、页码、已获取图片信息与错误 |
| `GET /api/thumb/{task_id}/{num}` | 已生成的JPEG缩略图；不存在时404 |
| `GET /api/download/{task_id}` | 下载已合成PDF；不存在或尚未就绪时404 |

状态中的 `current` 是正在处理流程中记录的页号；`images`包含已经成功处理的页号、宽高与条带数。`total`主要在任务收尾时更新，处理中应参考 `images` 长度，不要把暂时的0当成没有进度。

`done=true`表示任务结束，**还要检查 `error` 和实际张数**。网页保留部分结果时会展示“含错误”和“可能不完整”的下载说明。页面正常轮询间隔约800毫秒，轮询异常后约1500毫秒再次尝试；当前没有进度百分比，因为未知结束页时没有可靠总量。

## 10. 本地运行边界

这是面向可信本机用户的工具。网页监听 `127.0.0.1:8080`，没有账号系统、API鉴权、按用户隔离或任务自动清理。当前允许用户输入HTTP(S)图片地址并跟随重定向，没有完整的内网目标与重定向逐跳校验，因此不应直接改成公网下载服务。

CLI可显式设置额外请求头，但不会自动读取浏览器登录态，也不会获得原账号之外的访问权限。网页对请求头使用内置配置，没有表单级Cookie导入。来源需要登录、访问参数或特定Referer时，需先确认自己有权获取该内容，再选择合适的入口。

公开仓库只包含工具代码、合成测试与文档。论文正文、个人资料、下载成果、抓包、Cookie、备份文件及环境文件均不属于发布内容。请仅处理有权访问和保存的资料。

## 11. 常见问题

| 表现 | 可能原因与处理 |
| --- | --- |
| 提示文件名必须带页码 | 输入了详情页、随机文件名或直接PDF；需要带编号的图片直链 |
| 输入第31张，却下载第1张 | 样例URL用于推导模板；使用 `--start 31` 指定起点 |
| 第一页就403 | 来源要求有效访问参数或请求头；不要反复重试冒充已获权限 |
| 只得到前几页 | 遇到缺失页、HTML响应或上限；检查日志，并用已知结束页验证 |
| 生成的图片横条错乱 | 检查是否应该启用JM规则；普通来源使用 `--descramble none` |
| 透明区域在结果里变白 | 当前设计会把透明图合成到白底RGB |
| 调高DPI仍然不清晰 | DPI不增加原始像素；img2pdf多页分支也没有使用该布局参数 |
| 长页报像素上限或内存不足 | 缩小 `--long-width`，改用多页或减少单次页数 |
| 网页PDF可下载但提示含错误 | 仅保存了此前连续成功的部分，不能当成完整结果 |
| 任务重启后消失 | 任务只在内存；先下载需要保留的PDF |
| 网页端口被占用 | 用uvicorn显式指定其他回环端口；浏览器同步访问该端口 |

切换端口示例：

```powershell
.\.venv\Scripts\python.exe -m uvicorn image_to_pdf_server:app --host 127.0.0.1 --port 8081
```

## 12. 验证与代码导航

### 12.1 已执行的验证

本次整理日期为2026-10-25。使用独立虚拟环境，从依赖文件全新安装，完成：

| 检查 | 结果 |
| --- | --- |
| Python回归 | 15项通过，覆盖编号、失败边界、实际PDF页数及网页接口 |
| 网页脚本回归 | 3项通过，覆盖URL按文本展示、0起始页和部分结果提示 |
| 原有离线自测 | 通过，使用生成的色块图片检查编号、横条恢复和PDF输出 |
| PDF结构 | 使用pikepdf重新打开合成结果，检查多页和长页的实际页数 |
| 架构图 | 导出PNG/SVG，并检查PNG排版 |

测试仅使用合成图片和模拟上游响应，拒绝环境文件读取及外网连接；没有访问真实下载站点。浏览器脚本测试使用模拟DOM，不等于所有真实浏览器均完成端到端验收。详细环境与结果见[验证记录](docs/verification.md)和[机器可读结果](docs/verification.json)。

安装测试依赖后运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/verify.py
```

此入口需要Node.js执行3项网页脚本检查；仅检查原有核心能力时可运行：

```powershell
.\.venv\Scripts\python.exe image_url_to_pdf.py --self-test
```

### 12.2 文件职责

| 文件 | 职责 |
| --- | --- |
| [image_url_to_pdf.py](image_url_to_pdf.py) | URL编号、HTTP抓取、图像处理、PDF导出和CLI |
| [image_to_pdf_server.py](image_to_pdf_server.py) | 本地网页、后台线程、状态与缩略图、PDF下载 |
| [requirements.txt](requirements.txt) | 固定直接运行依赖版本 |
| [requirements-dev.txt](requirements-dev.txt) | 测试所需HTTP客户端与PDF读取器 |
| [tests/test_pageweaver.py](tests/test_pageweaver.py) | 15项Python回归 |
| [tests/web-ui.test.cjs](tests/web-ui.test.cjs) | 实际内嵌网页脚本的行为检查 |
| [tools/verify.py](tools/verify.py) | 拒绝环境文件和外网访问的验证入口 |
| [tools/generate_architecture.py](tools/generate_architecture.py) | PNG与SVG架构图生成 |
| [NOTICE.md](NOTICE.md) | 发布来源与第三方依赖说明 |

### 12.3 维护时优先考虑什么

修改编号规则时，同时验证前缀、补零、查询串和起始页；修改结束判断时，同时验证CLI严格范围与网页部分结果；修改PDF导出时，检查实际页数和图像顺序，而不只检查文件头。

后续适合优先补充任务清理与取消、网页请求选项、响应大小限制和更明确的任务状态。如果未来需要多人共享或公网运行，应先重新设计URL访问控制、身份认证、并发限额与持久化。现有项目不把这些规划写成已实现能力。

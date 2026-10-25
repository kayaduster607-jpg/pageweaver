# 来源与发布范围

本项目根据使用者提供的两个顶层Python脚本整理：`image_url_to_pdf.py`与`image_to_pdf_server.py`。
公开版本补充依赖声明、启动脚本、合成测试、架构图和技术说明，并修正端口、实时缩略图、
URL文本展示、起始页和部分结果提示等本地使用问题。

仓库不附带论文、个人资料、真实下载图片、视频、浏览器抓包、登录数据或环境文件。
原始材料中未提供独立LICENSE，本次未自行添加一份替原材料授予权利的许可证。

主要第三方组件如下，具体许可及版权以对应项目为准：

| 组件 | 项目 |
| --- | --- |
| Requests | https://github.com/psf/requests |
| Pillow | https://github.com/python-pillow/Pillow |
| img2pdf | https://gitlab.mister-muffin.de/josch/img2pdf |
| FastAPI | https://github.com/fastapi/fastapi |
| Uvicorn | https://github.com/Kludex/uvicorn |
| pikepdf | https://github.com/pikepdf/pikepdf |
| HTTPX | https://github.com/encode/httpx |

# Bili Downloader 3

一个运行在 Android Termux 上的 Bilibili 网页下载工具。项目使用 Python + Flask + 原生 HTML/CSS/JavaScript，不依赖 yt-dlp。

> 当前仓库是首版开发基线。B站接口、扫码登录和 DASH 播放链路需要在真实网络和账号权限下验证；接口返回可选画质不代表账号一定有权播放，也不把未真机验证的功能当作已验证完成。

## 设计目标

- 识别 BV 号、AV 号、B站视频链接和 b23.tv 短链接。
- 读取视频标题、UP主、简介、封面、分P和统计数据。
- 根据 B站播放接口返回值动态生成清晰度列表，不写死最高 1080P。
- 支持 B站扫码登录，登录 Cookie 只保存在运行本机的 data/ 目录，不上传到第三方。
- 支持 DASH 视频/音频分别下载、备用 CDN、临时文件和 FFmpeg 无损封装合并。
- 提供任务状态、下载进度、历史记录和手机端适配界面。

## Termux 安装

    pkg update -y
    pkg install -y python ffmpeg
    git clone https://github.com/sxsbsxs/bili-downloader3.git
    cd bili-downloader3
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    chmod +x run.sh
    ./run.sh

首次启动后，在手机浏览器打开 http://127.0.0.1:8765

局域网访问时，可设置 HOST=0.0.0.0，并仅在可信网络内使用。当前版本没有面向公网的多用户隔离层，不建议直接暴露到互联网。

## 依赖与外部程序

- Python 3
- Flask
- requests
- qrcode + Pillow（生成扫码二维码）
- FFmpeg（DASH 音视频合并；由 Termux 的 pkg install ffmpeg 安装）

项目不会调用 yt-dlp。FFmpeg 只负责把已下载的音视频轨道封装为 MP4，不负责解析视频链接。

## 隐私和账号安全

- Cookie 保存在本机 data/auth.json，文件权限限制为当前 Termux 用户可读写。
- 不要分享 data/、日志或扫码授权截图；不要把 Cookie 提交到 Git。
- 退出登录后会删除本地 Cookie。
- 扫码登录权限由 B站账号本身决定；大会员、版权地区和视频自身限制仍然有效。

## 当前限制

- B站网页接口可能调整；WBI 签名、二维码轮询和播放地址获取失败时，界面会显示具体错误。
- 需要登录才能播放的画质不会因本工具而获得授权。
- DASH 合并需要 FFmpeg。未安装时会保留音视频轨道并报告错误，不会伪装成可播放的 MP4。
- DRM、付费/受限内容及账号无权访问的内容不在支持范围内。
- 首版尚未承诺完成真机端到端验证；请在自己的 Termux 环境中实际测试。

## API

- GET /api/health：运行状态
- POST /api/parse：解析视频并获取可用清晰度
- GET /api/login/qrcode：生成扫码二维码
- GET /api/login/poll?key=...：轮询扫码状态
- POST /api/login/logout：退出登录
- POST /api/download：创建下载任务
- GET /api/tasks：任务列表
- GET /api/tasks/<id>：任务详情
- GET /api/history：下载历史
- GET /api/files/<name>：下载文件

## License

MIT

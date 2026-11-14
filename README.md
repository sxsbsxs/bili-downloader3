# Bili Downloader 3

一个运行在 Android Termux 上的 Bilibili 网页下载工具。项目使用 Python + Flask + 原生 HTML/CSS/JavaScript，不依赖 yt-dlp。

> 当前仓库是首版开发基线。B站接口、扫码登录和 DASH 播放链路需要在真实网络和账号权限下验证；接口返回可选画质不代表账号一定有权播放，也不把未真机验证的功能当作已验证完成。

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

浏览器打开 http://127.0.0.1:8765 。默认仅监听本机；局域网访问可设置 HOST=0.0.0.0，但当前版本没有公网多用户隔离，不建议暴露到互联网。

## 功能

- BV、AV、B站视频 URL、b23.tv 短链接识别。
- 视频信息、封面、UP主、简介和分P。
- 由 B站播放接口动态返回真实可用画质；不会写死最高 1080P。
- B站 APP 扫码登录；Cookie 仅保存在本机 data/auth.json。
- DASH 音视频分轨下载、备用 CDN 回退、临时文件 Range 续传和 FFmpeg 无损封装。
- 最终文件使用 ffprobe 检查视频流和时长，完成后才标记 100%。
- 下载任务、阶段进度、历史记录和移动端适配网页 UI。

## 依赖

Python 3、Flask、requests、qrcode/Pillow 和 Termux FFmpeg。FFmpeg 仅用于音视频封装，不承担链接解析。项目不调用 yt-dlp。

## 隐私与限制

不要分享 data/ 目录，不要把 Cookie 提交到 Git。扫码登录权限由 B站账号本身决定；大会员、版权地区和视频限制仍然有效。DRM、付费/受限内容和账号无权访问的内容不在支持范围内。接口可能变化，首版尚未完成真机端到端验证，必须在实际 Termux 环境测试。

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests
from werkzeug.utils import secure_filename

from .auth import read_cookie
from .bili import BiliClient, BiliError, USER_AGENT
from .config import DOWNLOAD_DIR, REQUEST_TIMEOUT

def _safe_title(title):
    value = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", str(title or "Bilibili Video"))
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = value[:90] or "Bilibili Video"
    return secure_filename(value.replace(" ", "_")) or "Bilibili_Video"

def _track_urls(track):
    urls = []
    primary = track.get("baseUrl") or track.get("base_url") or track.get("url")
    if primary:
        urls.append(primary)
    backups = track.get("backupUrl") or track.get("backup_url") or []
    for item in backups:
        if item and item not in urls:
            urls.append(item)
    if not urls:
        raise BiliError("B站没有返回有效的下载地址")
    return urls

def _download_stream(urls, target, progress_callback, start, span):
    target = Path(target)
    part = target.with_suffix(target.suffix + ".part")
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept": "*/*",
    }
    last_error = None
    for url in urls:
        try:
            offset = part.stat().st_size if part.exists() else 0
            request_headers = dict(headers)
            if offset:
                request_headers["Range"] = "bytes=" + str(offset) + "-"
            with requests.get(url, headers=request_headers, stream=True,
                              timeout=REQUEST_TIMEOUT) as response:
                if response.status_code not in (200, 206):
                    response.raise_for_status()
                    raise BiliError("CDN 返回 HTTP " + str(response.status_code))
                if offset and response.status_code != 206:
                    offset = 0
                content_length = int(response.headers.get("Content-Length") or 0)
                total = offset + content_length if content_length else 0
                mode = "ab" if offset else "wb"
                received = offset
                with part.open(mode) as output:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        output.write(chunk)
                        received += len(chunk)
                        if total > 0:
                            fraction = min(1.0, received / total)
                            progress_callback(start + span * fraction,
                                              "正在接收数据", "已接收 " + _format_bytes(received))
                        else:
                            progress_callback(min(start + span * 0.82, start + 12),
                                              "正在接收数据", "已接收 " + _format_bytes(received))
                    output.flush()
                    os.fsync(output.fileno())
            if not part.exists() or part.stat().st_size == 0:
                raise BiliError("下载内容为空")
            os.replace(part, target)
            return target
        except Exception as exc:
            last_error = exc
    raise BiliError("主 CDN 和备用 CDN 均下载失败：" + str(last_error))

def _format_bytes(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return (str(int(value)) if unit == "B" else ("%.1f" % value)) + " " + unit
        value /= 1024
    return "%.1f GB" % value

def _merge_tracks(video_path, audio_path, output_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise BiliError("没有找到 FFmpeg。请在 Termux 执行：pkg install ffmpeg")
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path)]
    if audio_path:
        command += ["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"]
    command += ["-c", "copy", "-movflags", "+faststart", str(output_path)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=900)
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1024:
        detail = (result.stderr or "FFmpeg 没有生成有效文件").strip()[-900:]
        raise BiliError("音视频封装失败：" + detail)
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        check = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30
        )
        try:
            duration = float(check.stdout.strip())
        except (TypeError, ValueError):
            duration = 0
        if check.returncode != 0 or duration <= 0:
            output_path.unlink(missing_ok=True)
            raise BiliError("封装文件未通过 ffprobe 时长校验")
    return output_path

def run_download(task_id, store, payload):
    raw_input = payload.get("input")
    qn = int(payload.get("qn") or 0)
    cid = int(payload.get("cid") or 0)
    if qn <= 0 or qn > 127:
        raise BiliError("清晰度参数无效")

    client = BiliClient(cookie=read_cookie())
    ref = client.resolve_input(raw_input)
    video = client.get_video_info(ref)
    allowed_cids = {int(item["cid"]) for item in video["pages"] if item.get("cid")}
    if cid not in allowed_cids:
        raise BiliError("分P编号不属于该视频，请重新解析后选择")
    play = client.get_play_info(video, cid, qn)
    actual_qn = int(play.get("quality") or 0)
    if actual_qn and actual_qn != qn:
        raise BiliError("B站实际返回的画质与所选画质不一致，请重新解析画质列表")
    base_name = _safe_title(video["title"])
    prefix = task_id + "_" + base_name
    output = DOWNLOAD_DIR / (prefix + ".mp4")

    def progress(value, phase, detail):
        store.update(task_id, status="downloading", progress=int(value),
                     phase=phase, detail=detail)

    dash = play.get("dash") or {}
    if dash.get("video"):
        candidates = dash.get("video") or []
        selected = next((item for item in candidates if int(item.get("id") or 0) == qn), None)
        if selected is None:
            raise BiliError("所选清晰度没有返回对应 DASH 视频轨道，请重新解析")
        audios = dash.get("audio") or []
        audio_track = max(audios, key=lambda item: int(item.get("id") or 0)) if audios else None
        video_file = DOWNLOAD_DIR / (prefix + ".video.m4s")
        audio_file = DOWNLOAD_DIR / (prefix + ".audio.m4s") if audio_track else None

        store.update(task_id, status="downloading", progress=5,
                     phase="准备下载", detail="正在获取 DASH 视频与音频轨道")
        _download_stream(_track_urls(selected), video_file,
                         lambda p, ph, de: progress(5 + p * 0.43, ph + "（视频）", de),
                         0, 100)
        if audio_track:
            _download_stream(_track_urls(audio_track), audio_file,
                             lambda p, ph, de: progress(48 + p * 0.39, ph + "（音频）", de),
                             0, 100)
        store.update(task_id, status="merging", progress=92,
                     phase="正在封装文件", detail="音视频数据接收完成，正在由 FFmpeg 合并")
        temporary_output = output.with_name(output.stem + ".merging.mp4")
        try:
            _merge_tracks(video_file, audio_file, temporary_output)
            os.replace(temporary_output, output)
        finally:
            temporary_output.unlink(missing_ok=True)
        video_file.unlink(missing_ok=True)
        if audio_file:
            audio_file.unlink(missing_ok=True)
    else:
        durls = play.get("durl") or []
        if not durls:
            raise BiliError("B站没有返回可下载的视频流")
        extension = "mp4" if str(play.get("format") or "").lower() == "mp4" else "flv"
        output = DOWNLOAD_DIR / (prefix + "." + extension)
        part_file = output.with_suffix(output.suffix + ".part")
        for index, segment in enumerate(durls):
            progress_base = 8 + int(index * 78 / max(1, len(durls)))
            segment_file = DOWNLOAD_DIR / (prefix + ".seg" + str(index))
            _download_stream(_track_urls(segment), segment_file,
                             lambda p, ph, de: progress(progress_base + p * 0.72 / max(1, len(durls)), ph, de),
                             0, 100)
            with segment_file.open("rb") as source, part_file.open("ab") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            segment_file.unlink(missing_ok=True)
        if not part_file.exists() or part_file.stat().st_size < 1024:
            raise BiliError("视频文件过小，下载可能不完整")
        os.replace(part_file, output)
        store.update(task_id, status="merging", progress=96,
                     phase="检查文件", detail="正在检查下载文件")

    if not output.exists() or output.stat().st_size < 1024:
        raise BiliError("最终文件不存在或大小异常")
    store.complete(task_id, output.name, video["title"], output.stat().st_size)

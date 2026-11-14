import base64
import io
import time
from threading import RLock
from urllib.parse import parse_qs, urlparse

import qrcode
import requests
from flask import Blueprint, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from .auth import clear_cookie, login_status, read_cookie, save_cookie
from .bili import BiliClient, BiliError, USER_AGENT
from .config import DOWNLOAD_DIR, WEB_DIR, MAX_VIDEO_INPUT
from .downloader import run_download
from .tasks import task_store

api = Blueprint("api", __name__, url_prefix="/api")
QR_SESSIONS = {}
QR_LOCK = RLock()

def _error(message, status=400):
    return jsonify({"ok": False, "error": str(message)}), status

def _make_qr_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    })
    response = session.get(
        "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
        timeout=(10, 25)
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") != 0:
        raise BiliError(body.get("message") or "B站二维码生成失败")
    data = body.get("data") or {}
    key = str(data.get("qrcode_key") or "")
    url = str(data.get("url") or "")
    if not key or not url:
        raise BiliError("B站没有返回二维码参数")
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    with QR_LOCK:
        QR_SESSIONS[key] = {"session": session, "created": time.time()}
    return key, "data:image/png;base64," + encoded

@api.get("/health")
def health():
    import shutil
    return jsonify({
        "ok": True,
        "app": "Bili Downloader 3",
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "login": login_status(),
    })

@api.post("/parse")
def parse_video():
    body = request.get_json(silent=True) or {}
    raw = str(body.get("input") or "").strip()
    if not raw or len(raw) > MAX_VIDEO_INPUT:
        return _error("请粘贴有效的 B站视频链接或 BV/AV 号")
    try:
        client = BiliClient(cookie=read_cookie())
        ref = client.resolve_input(raw)
        video = client.get_video_info(ref)
        selected_cid = int(body.get("cid") or (video["pages"][0]["cid"] if video["pages"] else 0))
        if selected_cid not in {int(page["cid"]) for page in video["pages"] if page.get("cid")}:
            return _error("所选分P不属于该视频")
        play_error = ""
        try:
            play = client.get_play_info(video, selected_cid, 127)
            qualities = client.qualities(play)
            current_quality = int(play.get("quality") or 0)
        except BiliError as exc:
            qualities = []
            current_quality = 0
            play_error = str(exc)
        return jsonify({
            "ok": True,
            "video": video,
            "qualities": qualities,
            "current_quality": current_quality,
            "quality_error": play_error,
            "login": login_status(),
        })
    except BiliError as exc:
        return _error(str(exc), 422)
    except (ValueError, TypeError):
        return _error("参数格式错误")

@api.get("/login/status")
def get_login_status():
    return jsonify({"ok": True, **login_status()})

@api.get("/login/qrcode")
def login_qrcode():
    try:
        key, image = _make_qr_session()
        return jsonify({"ok": True, "key": key, "image": image})
    except Exception as exc:
        return _error("生成扫码二维码失败：" + str(exc), 502)

@api.get("/login/poll")
def login_poll():
    key = str(request.args.get("key") or "")
    if not key or len(key) > 128:
        return _error("二维码会话无效")
    with QR_LOCK:
        entry = QR_SESSIONS.get(key)
    if not entry:
        return _error("二维码已失效，请重新生成")
    if time.time() - entry["created"] > 180:
        with QR_LOCK:
            QR_SESSIONS.pop(key, None)
        return jsonify({"ok": True, "state": "expired", "message": "二维码已过期"})

    try:
        session = entry["session"]
        response = session.get(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": key}, timeout=(10, 20)
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data") or {}
        code = int(data.get("code", -1))
        if code == 86101:
            return jsonify({"ok": True, "state": "waiting", "message": "请使用 B站 APP 扫码"})
        if code == 86090:
            return jsonify({"ok": True, "state": "scanned", "message": "已扫码，请在手机上确认登录"})
        if code == 86038:
            return jsonify({"ok": True, "state": "expired", "message": "二维码已过期"})
        if code != 0:
            return jsonify({"ok": True, "state": "waiting", "message": data.get("message") or "等待扫码确认"})

        cookie_values = session.cookies.get_dict()
        if not cookie_values and data.get("url"):
            query = parse_qs(urlparse(data["url"]).query)
            for name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                if query.get(name):
                    cookie_values[name] = query[name][0]
        cookie = "; ".join(name + "=" + value for name, value in cookie_values.items())
        if not cookie:
            return _error("登录成功回调未包含 Cookie，请重新扫码", 502)
        nav = BiliClient(cookie=cookie).get_nav()
        if not nav.get("isLogin"):
            return _error("B站登录状态校验失败，请重新扫码", 502)
        save_cookie(cookie)
        with QR_LOCK:
            QR_SESSIONS.pop(key, None)
        return jsonify({
            "ok": True, "state": "success", "message": "登录成功",
            "username": nav.get("uname") or "",
        })
    except Exception as exc:
        return _error("扫码状态查询失败：" + str(exc), 502)

@api.post("/login/logout")
def logout():
    clear_cookie()
    return jsonify({"ok": True, "message": "已退出登录"})

@api.post("/download")
def start_download():
    body = request.get_json(silent=True) or {}
    raw = str(body.get("input") or "").strip()
    if not raw or len(raw) > MAX_VIDEO_INPUT:
        return _error("请先解析一个有效视频")
    try:
        qn = int(body.get("qn") or 0)
        cid = int(body.get("cid") or 0)
        if not 1 <= qn <= 127 or cid <= 0:
            return _error("请先选择分P和清晰度")
        title = str(body.get("title") or "Bilibili 视频")[:160]
        task = task_store.create(run_download, {"input": raw, "cid": cid, "qn": qn}, title=title)
        return jsonify({"ok": True, "task": task}), 202
    except (ValueError, TypeError):
        return _error("清晰度或分P参数无效")

@api.get("/tasks")
def tasks():
    return jsonify({"ok": True, "tasks": task_store.list()})

@api.get("/tasks/<task_id>")
def task_detail(task_id):
    item = task_store.get(task_id)
    if not item:
        return _error("没有找到该任务", 404)
    return jsonify({"ok": True, "task": item})

@api.get("/history")
def history():
    return jsonify({"ok": True, "history": task_store.history()})

@api.get("/files/<path:filename>")
def download_file(filename):
    safe = secure_filename(filename)
    if not safe or safe != filename or "/" in filename or "\\" in filename:
        return _error("文件名无效", 400)
    path = DOWNLOAD_DIR / safe
    if not path.is_file():
        return _error("文件不存在", 404)
    return send_from_directory(DOWNLOAD_DIR, safe, as_attachment=True)

def register_web_routes(app):
    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(WEB_DIR / "assets", filename)

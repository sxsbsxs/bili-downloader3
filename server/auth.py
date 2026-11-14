import json
import os
import tempfile
from threading import RLock

from .config import DATA_DIR
from .bili import BiliClient

AUTH_FILE = DATA_DIR / "auth.json"
_lock = RLock()

def read_cookie():
    with _lock:
        if not AUTH_FILE.exists():
            return ""
        try:
            saved = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            return str(saved.get("cookie", "")).strip()
        except (OSError, ValueError, TypeError):
            return ""

def save_cookie(cookie):
    cookie = str(cookie or "").strip()
    if not cookie:
        raise ValueError("登录 Cookie 为空")
    payload = json.dumps({"cookie": cookie}, ensure_ascii=False)
    with _lock:
        fd, temp_name = tempfile.mkstemp(prefix="auth-", dir=str(DATA_DIR))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, AUTH_FILE)
            os.chmod(AUTH_FILE, 0o600)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

def clear_cookie():
    with _lock:
        try:
            AUTH_FILE.unlink()
        except FileNotFoundError:
            pass

def login_status():
    cookie = read_cookie()
    if not cookie:
        return {"logged_in": False, "username": ""}
    try:
        nav = BiliClient(cookie=cookie).get_nav()
        if not nav.get("isLogin"):
            clear_cookie()
            return {"logged_in": False, "username": ""}
        return {"logged_in": True, "username": nav.get("uname", "")}
    except Exception:
        return {"logged_in": False, "username": ""}

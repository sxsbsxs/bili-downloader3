from pathlib import Path
import os

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DOWNLOAD_DIR = ROOT_DIR / "downloads"
LOG_DIR = ROOT_DIR / "logs"
WEB_DIR = ROOT_DIR / "web"

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
MAX_WORKERS = max(1, min(int(os.environ.get("MAX_DOWNLOAD_WORKERS", "2")), 4))
REQUEST_TIMEOUT = (12, 40)
MAX_VIDEO_INPUT = 2048

def ensure_directories():
    for directory in (DATA_DIR, DOWNLOAD_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

ensure_directories()

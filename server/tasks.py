import json
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .config import DATA_DIR, MAX_WORKERS

HISTORY_FILE = DATA_DIR / "history.json"

class TaskStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.tasks = {}
        self.pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="bili-download")

    def create(self, worker, *args, **kwargs):
        task_id = uuid.uuid4().hex[:12]
        record = {
            "id": task_id, "status": "queued", "progress": 0,
            "phase": "等待中", "detail": "任务已加入队列",
            "filename": "", "error": "", "title": kwargs.pop("title", "Bilibili 视频"),
            "created_at": int(time.time()), "updated_at": int(time.time()),
        }
        with self.lock:
            self.tasks[task_id] = record
        self.pool.submit(self._run, task_id, worker, args, kwargs)
        return dict(record)

    def _run(self, task_id, worker, args, kwargs):
        try:
            worker(task_id, self, *args, **kwargs)
        except Exception as exc:
            self.fail(task_id, str(exc))

    def update(self, task_id, **fields):
        with self.lock:
            item = self.tasks.get(task_id)
            if not item:
                return
            item.update(fields)
            item["updated_at"] = int(time.time())
            if "progress" in item:
                item["progress"] = max(0, min(99, int(item["progress"])))

    def complete(self, task_id, filename, title, size):
        with self.lock:
            item = self.tasks.get(task_id)
            if not item:
                return
            item.update({
                "status": "completed", "progress": 100, "phase": "已完成",
                "detail": "文件已封装并校验，可以下载",
                "filename": filename, "size": int(size), "updated_at": int(time.time()),
            })
            history = self._read_history()
            history.insert(0, {
                "id": task_id, "title": title, "filename": filename,
                "size": int(size), "created_at": item["created_at"],
            })
            self._write_history(history[:100])

    def fail(self, task_id, error):
        with self.lock:
            item = self.tasks.get(task_id)
            if item:
                item.update({
                    "status": "failed", "phase": "失败",
                    "detail": "任务未完成", "error": str(error)[:600],
                    "updated_at": int(time.time()),
                })

    def get(self, task_id):
        with self.lock:
            item = self.tasks.get(task_id)
            return dict(item) if item else None

    def list(self):
        with self.lock:
            return [dict(x) for x in sorted(
                self.tasks.values(), key=lambda item: item["created_at"], reverse=True
            )]

    def _read_history(self):
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _write_history(self, data):
        fd, temp_name = tempfile.mkstemp(prefix="history-", dir=str(DATA_DIR))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(temp_name, HISTORY_FILE)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def history(self):
        with self.lock:
            return self._read_history()

task_store = TaskStore()

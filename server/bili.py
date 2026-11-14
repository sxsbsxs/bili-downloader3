import hashlib
import re
import time
from urllib.parse import urlencode, urljoin, urlparse

import requests

from .config import REQUEST_TIMEOUT

API = "https://api.bilibili.com"
REFERER = "https://www.bilibili.com/"
USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36"
ALLOWED_LINK_HOSTS = {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv", "www.b23.tv"}

MIXIN_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59,  6, 63, 57, 62, 11, 36, 20, 34, 44, 52
]

class BiliError(Exception):
    pass

def _clean_host(host):
    return (host or "").lower().split(":")[0].strip(".")

class BiliClient:
    def __init__(self, cookie=""):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
        })
        self.cookie = str(cookie or "").strip()
        self._mixin_key = None
        # Scope authorization cookies to Bilibili only. Never attach them as
        # a global Cookie header because short-link resolution visits b23.tv.
        for item in self.cookie.split(";"):
            if "=" not in item:
                continue
            name, value = item.strip().split("=", 1)
            name = name.strip()
            if name:
                self.session.cookies.set(name, value.strip(),
                                         domain=".bilibili.com", path="/")

    def _get_json(self, url, params=None, allow_redirects=True):
        try:
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT,
                                        allow_redirects=allow_redirects)
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            raise BiliError("连接 B站接口失败：" + str(exc)) from exc
        except ValueError as exc:
            raise BiliError("B站接口返回的不是有效 JSON") from exc
        if not isinstance(body, dict):
            raise BiliError("B站接口返回格式异常")
        if body.get("code", 0) != 0:
            raise BiliError(str(body.get("message") or body.get("msg") or "B站接口拒绝请求"))
        return body.get("data") or {}

    def get_nav(self):
        return self._get_json(API + "/x/web-interface/nav")

    def _get_mixin_key(self):
        if self._mixin_key:
            return self._mixin_key
        nav = self.get_nav()
        wbi = nav.get("wbi_img") or {}
        img = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
        sub = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
        original = img + sub
        if len(original) < 64:
            raise BiliError("无法从 B站获取 WBI 签名密钥")
        self._mixin_key = "".join(original[index] for index in MIXIN_TABLE)[:32]
        return self._mixin_key

    def _signed_params(self, params):
        values = dict(params)
        values["wts"] = int(time.time())
        for key, value in list(values.items()):
            values[key] = re.sub(r"[!'()*]", "", str(value))
        query = urlencode(sorted(values.items()))
        signature = hashlib.md5((query + self._get_mixin_key()).encode("utf-8")).hexdigest()
        values["w_rid"] = signature
        return values

    def resolve_input(self, raw):
        raw = str(raw or "").strip()
        if not raw or len(raw) > 2048:
            raise BiliError("请粘贴有效的 B站视频链接或 BV/AV 号")
        match = re.search(r"(BV[0-9A-Za-z]{10}|av\d+)", raw, re.I)
        if match:
            value = match.group(1)
            return {"bvid": value if value.lower().startswith("bv") else "",
                    "aid": int(value[2:]) if value.lower().startswith("av") else 0}

        candidate = raw if "://" in raw else "https://" + raw
        parsed = urlparse(candidate)
        host = _clean_host(parsed.netloc)
        if host not in ALLOWED_LINK_HOSTS or parsed.scheme not in {"http", "https"}:
            raise BiliError("目前只接受 B站视频地址、b23.tv 短链接或 BV/AV 号")
        if parsed.port not in (None, 80, 443):
            raise BiliError("不接受带自定义端口的视频地址")
        if parsed.scheme == "http":
            candidate = parsed._replace(scheme="https", netloc=parsed.netloc.split(":")[0]).geturl()

        current = candidate
        response = None
        finished = False
        for _ in range(7):
            try:
                response = self.session.get(current, timeout=REQUEST_TIMEOUT,
                                            allow_redirects=False)
            except requests.RequestException as exc:
                raise BiliError("解析短链接失败：" + str(exc)) from exc
            if response.is_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise BiliError("B站短链接返回了无效的跳转")
                target = urljoin(current, location)
                target_parts = urlparse(target)
                target_host = _clean_host(target_parts.netloc)
                if (target_parts.scheme != "https" or target_host not in ALLOWED_LINK_HOSTS
                        or target_parts.port not in (None, 443)):
                    raise BiliError("短链接跳转到了非 B站域名，已阻止请求")
                current = target
                continue
            finished = True
            break
        if not finished or response is None:
            raise BiliError("短链接重定向次数过多")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BiliError("解析短链接失败：" + str(exc)) from exc
        final = urlparse(response.url)
        final_host = _clean_host(final.netloc)
        if final_host not in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}:
            raise BiliError("短链接没有跳转到 B站视频页面")
        match = re.search(r"(BV[0-9A-Za-z]{10}|av\d+)", response.url, re.I)
        if not match:
            match = re.search(r"(BV[0-9A-Za-z]{10}|av\d+)", response.text[:200000], re.I)
        if not match:
            raise BiliError("没有从链接中找到 BV/AV 视频编号")
        value = match.group(1)
        return {"bvid": value if value.lower().startswith("bv") else "",
                "aid": int(value[2:]) if value.lower().startswith("av") else 0}

    def get_video_info(self, ref):
        params = {"bvid": ref["bvid"]} if ref.get("bvid") else {"aid": ref["aid"]}
        data = self._get_json(API + "/x/web-interface/view", params=params)
        pages = []
        for page in data.get("pages") or []:
            pages.append({
                "page": page.get("page", len(pages) + 1),
                "cid": page.get("cid"),
                "part": page.get("part") or ("P" + str(len(pages) + 1)),
                "duration": page.get("duration", 0),
            })
        if not pages and data.get("cid"):
            pages = [{"page": 1, "cid": data["cid"], "part": "P1",
                      "duration": data.get("duration", 0)}]
        return {
            "aid": data.get("aid"),
            "bvid": data.get("bvid"),
            "cid": data.get("cid"),
            "title": data.get("title") or "Bilibili 视频",
            "description": data.get("desc") or "",
            "cover": data.get("pic") or "",
            "owner": (data.get("owner") or {}).get("name", ""),
            "owner_mid": (data.get("owner") or {}).get("mid"),
            "duration": data.get("duration", 0),
            "pubdate": data.get("pubdate"),
            "stat": data.get("stat") or {},
            "pages": pages,
        }

    def get_play_info(self, video, cid, qn=127):
        params = {
            "bvid": video["bvid"],
            "avid": video["aid"],
            "cid": int(cid),
            "qn": int(qn),
            "fnver": 0,
            "fnval": 4048,
            "fourk": 1,
        }
        try:
            return self._get_json(API + "/x/player/wbi/playurl",
                                  params=self._signed_params(params))
        except BiliError as first_error:
            try:
                fallback = dict(params)
                fallback.pop("avid", None)
                return self._get_json(API + "/x/player/playurl", params=fallback)
            except BiliError:
                raise first_error

    @staticmethod
    def qualities(play_data):
        ids = play_data.get("accept_quality") or []
        labels = play_data.get("accept_description") or []
        available = []
        for index, qn in enumerate(ids):
            label = labels[index] if index < len(labels) else ("画质 " + str(qn))
            available.append({"id": int(qn), "label": str(label)})
        if not available and play_data.get("quality"):
            available.append({"id": int(play_data["quality"]), "label": "当前画质"})
        return available

"""
Universal Link Parser API
支持抖音、B站、小红书、TikTok、YouTube 等平台的链接解析与下载
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from random import choice

from dotenv import load_dotenv

load_dotenv()

# ======================================================================
# 配置
# ======================================================================

BASE_DIR = Path(__file__).parent
PORT = int(os.getenv("MF_PORT", "9000"))
PREFIX = os.getenv("MF_PREFIX", "").rstrip("/")
FFMPEG_PATH = os.getenv("MF_FFMPEG_PATH", "")
DOWNLOADS_DIR = os.getenv("MF_DOWNLOADS_DIR", "")
PROXY = os.getenv("MF_PROXY", "")
LOG_LEVEL = os.getenv("MF_LOG_LEVEL", "INFO").upper()
CLEANUP_CRON = os.getenv("MF_CLEANUP_CRON", "").strip()

# 下载目录（支持相对路径，相对于项目目录）
if DOWNLOADS_DIR:
    _dl_path = Path(DOWNLOADS_DIR)
    DOWNLOAD_DIR = _dl_path if _dl_path.is_absolute() else BASE_DIR / _dl_path
else:
    DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

THUMB_DIR = DOWNLOAD_DIR / "_thumbs"
THUMB_MAX_WIDTH = 400
THUMB_QUALITY = 80

# --- 定时清理 ---

def _cleanup_files():
    """删除下载目录中所有文件（含缩略图）"""
    count = 0
    size = 0
    for f in DOWNLOAD_DIR.rglob("*"):
        if f.is_file():
            size += f.stat().st_size
            f.unlink()
            count += 1
    # 清理空目录（从深到浅）
    for d in sorted(DOWNLOAD_DIR.rglob("*"), key=lambda p: str(p), reverse=True):
        if d.is_dir() and d != THUMB_DIR and not any(d.iterdir()):
            d.rmdir()
    logger.info(f"[清理] 已删除 {count} 个文件，释放 {size / 1024 / 1024:.1f} MB")


def _cleanup_loop():
    """后台线程：按 cron 表达式定时清理"""
    if not CLEANUP_CRON:
        return
    from croniter import croniter
    cron = croniter(CLEANUP_CRON, datetime.now())
    logger.info(f"[清理] 已启用定时清理，cron: {CLEANUP_CRON}")
    while True:
        next_run = cron.get_next(datetime)
        wait = max(0, (next_run - datetime.now()).total_seconds())
        if wait > 0:
            time.sleep(wait)
        logger.info("[清理] 开始执行定时清理...")
        try:
            _cleanup_files()
        except Exception as e:
            logger.error(f"[清理] 失败: {e}")


def start_cleanup_thread():
    if CLEANUP_CRON:
        t = threading.Thread(target=_cleanup_loop, daemon=True)
        t.start()

CACHE_FILE = DOWNLOAD_DIR / "_cache.json"

# ffmpeg 路径发现（支持相对路径，相对于项目目录）
_FFMPEG_CANDIDATES = []
if FFMPEG_PATH:
    _p = Path(FFMPEG_PATH)
    if not _p.is_absolute():
        _p = BASE_DIR / _p
    if _p.is_file():
        os.environ["PATH"] = str(_p.parent) + os.pathsep + os.environ.get("PATH", "")
        os.environ["FFMPEG_LOCATION"] = str(_p)
    elif _p.is_dir():
        _FFMPEG_CANDIDATES.append(_p)
else:
    _FFMPEG_CANDIDATES.extend([
        BASE_DIR / "ffmpeg-master-latest-win64-gpl" / "bin",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe" / "ffmpeg-8.1.1-full_build" / "bin",
    ])

for _d in _FFMPEG_CANDIDATES:
    if (_d / "ffmpeg.exe").exists():
        os.environ["PATH"] = str(_d) + os.pathsep + os.environ.get("PATH", "")
        os.environ["FFMPEG_LOCATION"] = str(_d / "ffmpeg.exe")
        break

import httpx
import yt_dlp
from PIL import Image
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# ======================================================================
# Logging + 内存日志收集
# ======================================================================

LOG_BUFFER: deque[dict] = deque(maxlen=500)


class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        LOG_BUFFER.append({
            "time": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
        })


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), MemoryLogHandler()],
)
logger = logging.getLogger("parser")

app = FastAPI(title="Universal Link Parser", version="1.0.0", root_path=PREFIX)

# CORS 跨域支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
_STATIC_DIR = BASE_DIR / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def _get_client_ip(request: Request) -> str:
    """获取客户端真实 IP，优先从 EO-Connecting-IP 获取"""
    return request.headers.get("EO-Connecting-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.headers.get("X-Real-IP") or (request.client.host if request.client else "unknown")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/thumb/"):
        return await call_next(request)
    client_ip = _get_client_ip(request)
    logger.info(f">>> {request.method} {path}  query={dict(request.query_params)}  client={client_ip}")
    resp = await call_next(request)
    logger.info(f"<<< {request.method} {path}  status={resp.status_code}")
    return resp


IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
    "Mobile/15E148 Safari/604.1"
)
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 15; SM-G998B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Mobile Safari/537.36"
)
PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36"
)


# ======================================================================
# Cache: URL -> 解析结果去重
# ======================================================================

def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_key(url: str) -> str:
    """用原始 URL 做缓存 key（短链场景用 resolved_url）"""
    return url


def _check_cache(url: str) -> dict | None:
    cache = _load_cache()
    key = _cache_key(url)
    if key not in cache:
        return None
    entry = cache[key]
    # 校验文件是否都还在
    files = entry.get("files", [])
    valid_files = []
    for f in files:
        fpath = DOWNLOAD_DIR / f.get("relative_path", "")
        if fpath.exists():
            valid_files.append(f)
    if not valid_files:
        logger.info(f"[缓存] 命中但文件已丢失，重新下载: {key[:60]}")
        return None
    logger.info(f"[缓存] 命中: {key[:60]}")
    entry["files"] = valid_files
    entry["cached"] = True
    entry["success"] = True
    return entry


def _update_cache(url: str, result: dict):
    cache = _load_cache()
    key = _cache_key(url)
    meta = _load_meta()
    # 为 files 补充 width/height，同时写入 _meta.json
    enriched_files = []
    for f in result.get("files", []):
        rel = f["relative_path"]
        m = meta.get(rel, {})
        w, h = m.get("width", 0), m.get("height", 0)
        enriched_files.append({**f, "width": w, "height": h})
        _save_meta(DOWNLOAD_DIR / rel, w, h,
                   title=result.get("title", ""), author=result.get("author", ""),
                   platform=result.get("platform", ""), type=result.get("type", ""),
                   duration=result.get("duration", 0), original_url=result.get("original_url", ""))
    cache[key] = {
        "platform": result.get("platform", ""),
        "title": result.get("title", ""),
        "author": result.get("author", ""),
        "type": result.get("type", ""),
        "duration": result.get("duration", 0),
        "original_url": result.get("original_url", ""),
        "resolved_url": result.get("resolved_url", ""),
        "client_ip": result.get("client_ip", ""),
        "files": enriched_files,
    }
    _save_cache(cache)


# ======================================================================
# 文件路径: downloads/yyyymmdd/platform/timestamp_random.ext
# ======================================================================

def _make_download_path(platform: str, suffix: str, url: str = "") -> Path:
    """生成分层下载路径: downloads/20260526/抖音/1234567890_a1b2c3.mp4"""
    today = datetime.now().strftime("%Y%m%d")
    ts = int(time.time() * 1000)  # 毫秒级时间戳，避免同秒冲突
    seed = f"{ts}{platform}{suffix}{url}"
    rand = hashlib.md5(seed.encode()).hexdigest()[:6]
    fname = f"{ts}_{rand}{suffix}"
    subdir = DOWNLOAD_DIR / today / platform
    subdir.mkdir(parents=True, exist_ok=True)
    return subdir / fname


def _relative_path(fpath: Path) -> str:
    """相对于 DOWNLOAD_DIR 的路径"""
    return str(fpath.relative_to(DOWNLOAD_DIR)).replace("\\", "/")


def _file_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def extract_url(text: str) -> str:
    """从剪贴板分享文案中提取 URL"""
    m = re.search(r"https?://[^\s]+", text)
    if m:
        url = m.group(0).rstrip("/")
        url = re.sub(r"[，。！？、；：）】》​]+$", "", url)
        logger.info(f"[提取] 从文案中提取到 URL: {url}")
        return url
    logger.warning(f"[提取] 未找到 URL，原文: {text[:80]}")
    return text.strip()


# ======================================================================
# Douyin Parser
# ======================================================================

async def resolve_short_link(url: str, client: httpx.AsyncClient) -> str:
    logger.info(f"[短链] 解析: {url}")
    resp = await client.get(url, follow_redirects=False, headers={"User-Agent": PC_UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    logger.info(f"[短链] 状态码: {resp.status_code}")
    if resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get("Location", url)
        logger.info(f"[短链] 重定向到: {location}")
        return location
    logger.warning(f"[短链] 未收到重定向，返回原 URL")
    return url


def extract_douyin_id(url: str) -> tuple[str, str] | None:
    patterns = [
        r"douyin\.com/(?:video|note|slides)/(\d+)",
        r"iesdouyin\.com/share/(?:slides|video|note)/(\d+)",
        r"m\.douyin\.com/share/(?:slides|video|note)/(\d+)",
        r"jingxuan\.douyin\.com/m/(?:slides|video|note)/(\d+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            vid = m.group(1)
            if "slides" in url:
                return vid, "slides"
            elif "note" in url:
                return vid, "note"
            return vid, "video"
    return None


async def parse_douyin_video(url: str, client: httpx.AsyncClient) -> dict:
    logger.info(f"[抖音] 解析页面: {url}")
    resp = await client.get(url, follow_redirects=True)
    logger.info(f"[抖音] 页面状态码: {resp.status_code}, 内容长度: {len(resp.text)}")
    resp.raise_for_status()
    text = resp.text

    m = re.search(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", text, re.DOTALL)
    if not m:
        raise ValueError("无法从页面提取 _ROUTER_DATA")

    logger.info("[抖音] 成功提取 _ROUTER_DATA")
    data = json.loads(m.group(1).strip())

    video_data = None
    loader = data.get("loaderData", {})
    for key in ("video_(id)/page", "note_(id)/page"):
        page = loader.get(key)
        if page:
            info_res = page.get("videoInfoRes", {})
            items = info_res.get("item_list", [])
            if items:
                video_data = items[0]
                logger.info(f"[抖音] 从 {key} 提取到数据")
                break

    if not video_data:
        raise ValueError("无法提取视频数据")

    author = video_data.get("author", {})
    desc = video_data.get("desc", "")
    create_time = video_data.get("create_time", 0)

    images = video_data.get("images")
    if images:
        image_urls = []
        for img in images:
            urls = img.get("url_list", [])
            if urls:
                image_urls.append(choice(urls))
        logger.info(f"[抖音] 图文, 图片数: {len(image_urls)}, 作者: {author.get('nickname')}")
        return {
            "type": "slides",
            "title": desc,
            "author": author.get("nickname", ""),
            "timestamp": create_time,
            "image_urls": image_urls,
            "video_url": None,
        }

    video = video_data.get("video")
    if video:
        play_addr = video.get("play_addr", {})
        url_list = play_addr.get("url_list", [])
        video_url = None
        for u in url_list:
            video_url = u.replace("playwm", "play")
            break

        cover_url = None
        cover = video.get("cover", {})
        cover_list = cover.get("url_list", [])
        if cover_list:
            cover_url = choice(cover_list)

        duration = video.get("duration", 0)
        logger.info(f"[抖音] 视频, 时长: {duration}s, 作者: {author.get('nickname')}")
        return {
            "type": "video",
            "title": desc,
            "author": author.get("nickname", ""),
            "timestamp": create_time,
            "video_url": video_url,
            "cover_url": cover_url,
            "duration": duration,
            "image_urls": [],
        }

    raise ValueError("无法识别内容类型")


async def parse_douyin_slides_api(vid: str, client: httpx.AsyncClient) -> dict:
    logger.info(f"[抖音] API 解析 slides, ID: {vid}")
    url = "https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/"
    params = {"aweme_ids": f"[{vid}]", "request_source": "200"}
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    details = data.get("aweme_details", [])
    if not details:
        raise ValueError("无法获取图文数据")

    item = details[0]
    author = item.get("author", {})
    desc = item.get("desc", "")
    create_time = item.get("create_time", 0)

    image_urls = []
    dynamic_urls = []
    for img in item.get("images", []):
        urls = img.get("url_list", [])
        if urls:
            image_urls.append(choice(urls))
        vid_info = img.get("video")
        if vid_info:
            play = vid_info.get("play_addr", {})
            play_urls = play.get("url_list", [])
            if play_urls:
                dynamic_urls.append(choice(play_urls))

    return {
        "type": "slides",
        "title": desc,
        "author": author.get("nickname", ""),
        "timestamp": create_time,
        "image_urls": image_urls,
        "dynamic_urls": dynamic_urls,
        "video_url": None,
    }


async def parse_douyin_iteminfo_api(vid: str, client: httpx.AsyncClient) -> dict:
    """通过 iteminfo API 解析抖音视频/图文"""
    logger.info(f"[抖音] iteminfo API 解析, ID: {vid}")
    url = "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/"
    params = {"item_ids": vid}
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    items = data.get("item_list", [])
    if not items:
        raise ValueError("iteminfo API 无数据")

    item = items[0]
    author = item.get("author", {})
    desc = item.get("desc", "")
    create_time = item.get("create_time", 0)

    images = item.get("images")
    if images:
        image_urls = []
        for img in images:
            urls = img.get("url_list", [])
            if urls:
                image_urls.append(choice(urls))
        return {
            "type": "slides",
            "title": desc,
            "author": author.get("nickname", ""),
            "timestamp": create_time,
            "image_urls": image_urls,
            "video_url": None,
        }

    video = item.get("video")
    if video:
        play_addr = video.get("play_addr", {})
        url_list = play_addr.get("url_list", [])
        video_url = None
        for u in url_list:
            video_url = u.replace("playwm", "play")
            break
        cover_url = None
        cover = video.get("cover", {})
        cover_list = cover.get("url_list", [])
        if cover_list:
            cover_url = choice(cover_list)
        duration = video.get("duration", 0)
        return {
            "type": "video",
            "title": desc,
            "author": author.get("nickname", ""),
            "timestamp": create_time,
            "video_url": video_url,
            "cover_url": cover_url,
            "duration": duration,
            "image_urls": [],
        }

    raise ValueError("无法识别内容类型")


# ======================================================================
# Generic Parser (yt-dlp)
# ======================================================================

def parse_with_ytdlp(url: str) -> dict:
    logger.info(f"[yt-dlp] 解析: {url}")
    opts = {
        "quiet": True,
        "skip_download": True,
        "http_headers": {"User-Agent": PC_UA},
    }
    if PROXY and any(d in url for d in ("tiktok.com", "youtube.com", "youtu.be", "twitter.com", "x.com")):
        opts["proxy"] = PROXY
        logger.info(f"[yt-dlp] 使用代理: {PROXY}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise ValueError("yt-dlp 无法解析该链接")

    title = info.get("title", "")
    author = info.get("uploader", info.get("channel", ""))
    logger.info(f"[yt-dlp] 解析成功: {title} by {author}")
    return {
        "type": "video",
        "title": title,
        "author": author,
        "timestamp": info.get("timestamp", 0),
        "video_url": info.get("url") or None,
        "cover_url": info.get("thumbnail"),
        "duration": info.get("duration", 0),
        "image_urls": [],
        "formats": info.get("formats", []),
    }


# ======================================================================
# Download helpers
# ======================================================================

async def download_file(url: str, suffix: str, client: httpx.AsyncClient, platform: str = "未知") -> tuple[Path, str]:
    """下载文件，返回 (绝对路径, 相对路径)"""
    fpath = _make_download_path(platform, suffix, url)
    logger.info(f"[下载] 开始: {url[:80]}... -> {fpath.name}")
    resp = await client.get(url, follow_redirects=True)
    resp.raise_for_status()
    fpath.write_bytes(resp.content)
    size_mb = len(resp.content) / 1024 / 1024
    rel = _relative_path(fpath)
    _generate_thumb(fpath)
    logger.info(f"[下载] 完成: {rel} ({size_mb:.2f} MB)")
    return fpath, rel


# --- 文件元数据缓存 ---

META_PATH = DOWNLOAD_DIR / "_meta.json"


def _load_meta() -> dict:
    if META_PATH.exists():
        try:
            return json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_meta(fpath: Path, width: int, height: int, **extra):
    meta = _load_meta()
    rel = _relative_path(fpath)
    meta[rel] = {"width": width, "height": height, **extra}
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _probe_video(fpath: Path) -> tuple[int, int] | None:
    """用 ffprobe 获取视频宽高"""
    import shutil
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(fpath)],
            capture_output=True, text=True, timeout=10)
        if result.stdout.strip():
            w, h = result.stdout.strip().split(",")
            return int(w), int(h)
    except Exception:
        pass
    return None


def _generate_thumb(original: Path):
    """为图片/视频生成缩略图，存储在 THUMB_DIR 下，同时记录尺寸到 _meta.json"""
    suffix = original.suffix.lower()
    thumb_path = THUMB_DIR / _relative_path(original)
    if thumb_path.exists():
        return

    # 图片缩略图
    if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        try:
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            img = Image.open(original)
            w, h = img.size
            _save_meta(original, w, h)
            if img.width > THUMB_MAX_WIDTH:
                ratio = THUMB_MAX_WIDTH / img.width
                new_size = (THUMB_MAX_WIDTH, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(thumb_path, "JPEG", quality=THUMB_QUALITY, optimize=True)
            logger.info(f"[缩略图] 生成: {thumb_path.name}")
        except Exception as e:
            logger.warning(f"[缩略图] 生成失败: {original.name} - {e}")

    # 视频缩略图（FFmpeg 截取第 1 秒，统一保存为 .jpg）
    elif suffix in (".mp4", ".mkv", ".webm", ".flv", ".mov", ".avi"):
        import shutil
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.warning("[缩略图] FFmpeg 未找到，跳过视频缩略图")
            return
        thumb_path = thumb_path.with_suffix(".jpg")
        if thumb_path.exists():
            return
        try:
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [ffmpeg, "-ss", "1", "-i", str(original),
                 "-vframes", "1", "-vf", f"scale={THUMB_MAX_WIDTH}:-1",
                 "-q:v", "3", "-y", str(thumb_path)],
                capture_output=True, text=True, timeout=60)
            if thumb_path.exists():
                logger.info(f"[缩略图] 生成: {thumb_path.name}")
                # 从 ffprobe 获取视频尺寸
                dim = _probe_video(original)
                if dim:
                    _save_meta(original, dim[0], dim[1])
            else:
                logger.warning(f"[缩略图] 视频转换失败: {result.stderr[:120]}")
        except Exception as e:
            logger.warning(f"[缩略图] 生成失败: {original.name} - {e}")


def download_with_ytdlp(url: str, platform: str = "未知") -> tuple[Path, str]:
    """使用 yt-dlp 下载，返回 (绝对路径, 相对路径)"""
    fpath = _make_download_path(platform, ".mp4", url)
    outtmpl = str(fpath.with_suffix(".%(ext)s"))
    logger.info(f"[yt-dlp 下载] 开始: {url[:80]}...")

    opts = {
        "outtmpl": outtmpl,
        "format": "bv*+ba/b/bv*/ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "http_headers": {"User-Agent": PC_UA},
        "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
    }
    if PROXY and any(d in url for d in ("tiktok.com", "youtube.com", "youtu.be", "twitter.com", "x.com")):
        opts["proxy"] = PROXY
        logger.info(f"[yt-dlp 下载] 使用代理: {PROXY}")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        logger.warning(f"[yt-dlp 下载] 首次失败: {e}, 尝试仅视频流")
        opts["format"] = "bv/b"
        opts.pop("merge_output_format", None)
        opts.pop("postprocessors", None)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    # 检查输出文件
    if fpath.exists():
        size_mb = fpath.stat().st_size / 1024 / 1024
        rel = _relative_path(fpath)
        _generate_thumb(fpath)
        logger.info(f"[yt-dlp 下载] 完成: {rel} ({size_mb:.2f} MB)")
        return fpath, rel

    # yt-dlp 可能改了扩展名
    candidates = sorted(fpath.parent.glob(f"{fpath.stem}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        actual = candidates[0]
        size_mb = actual.stat().st_size / 1024 / 1024
        rel = _relative_path(actual)
        _generate_thumb(actual)
        logger.info(f"[yt-dlp 下载] 完成: {rel} ({size_mb:.2f} MB)")
        return actual, rel

    raise FileNotFoundError("下载失败")


# ======================================================================
# Platform detection
# ======================================================================

def _detect_platform(url: str) -> str:
    if "douyin.com" in url or "iesdouyin.com" in url:
        return "抖音"
    if "bilibili.com" in url or "b23.tv" in url:
        return "B站"
    if "xiaohongshu.com" in url or "xhslink.com" in url:
        return "小红书"
    if "tiktok.com" in url:
        return "TikTok"
    if "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    if "twitter.com" in url or "x.com" in url:
        return "Twitter"
    if "weibo.com" in url:
        return "微博"
    if "kuaishou.com" in url:
        return "快手"
    return "其他"


# ======================================================================
# 前端配置注入
# ======================================================================

def _write_config_js():
    content = f"window.BASE_PATH = '{PREFIX}';\n"
    (_STATIC_DIR / "config.js").write_text(content, encoding="utf-8")

_write_config_js()

_INDEX_HTML_CACHE = ""
_startup_ts = int(time.time())

def _get_index_html() -> str:
    global _INDEX_HTML_CACHE
    if not _INDEX_HTML_CACHE:
        raw = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
        s = f"{PREFIX}/static"
        html = raw.replace('href="favicon.svg"', f'href="{s}/favicon.svg"')
        html = html.replace('href="tailwind.min.css"', f'href="{s}/tailwind.min.css"')
        html = html.replace('href="style.css"', f'href="{s}/style.css"')
        html = html.replace('src="config.js"', f'src="{s}/config.js?v={_startup_ts}"')
        html = html.replace('src="app.js"', f'src="{s}/app.js?v={_startup_ts}"')
        _INDEX_HTML_CACHE = html
    return _INDEX_HTML_CACHE


# ======================================================================
# API Routes
# ======================================================================

@app.get("/")
async def index():
    return HTMLResponse(_get_index_html())

@app.get("/files")
@app.get("/history")
@app.get("/logs")
@app.get("/docs")
async def spa_routes():
    return HTMLResponse(_get_index_html())


# --- 日志、统计、缓存 ---

@app.get("/api/logs")
async def get_logs(limit: int = Query(100, ge=1, le=500)):
    """返回最近 N 条日志"""
    items = list(LOG_BUFFER)[-limit:]
    return {"logs": items, "total": len(LOG_BUFFER)}


@app.get("/api/stats")
async def get_stats():
    """统计信息"""
    total_files = 0
    total_size = 0
    by_platform: dict[str, int] = {}
    by_date: dict[str, int] = {}

    for f in DOWNLOAD_DIR.rglob("*"):
        if f.is_file():
            total_files += 1
            total_size += f.stat().st_size
            parts = f.relative_to(DOWNLOAD_DIR).parts
            if len(parts) >= 2:
                date_part = parts[0]
                platform_part = parts[1]
                by_date[date_part] = by_date.get(date_part, 0) + 1
                by_platform[platform_part] = by_platform.get(platform_part, 0) + 1

    cache_count = len(_load_cache())

    return {
        "total_files": total_files,
        "total_size": total_size,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "by_platform": by_platform,
        "by_date": by_date,
        "cache_count": cache_count,
    }


@app.get("/api/cache")
async def get_cache(page: int = 1, page_size: int = 20):
    """返回缓存条目（分页）"""
    cache = _load_cache()
    entries = []
    for url, data in cache.items():
        entries.append({
            "url": url,
            "platform": data.get("platform", ""),
            "title": data.get("title", ""),
            "author": data.get("author", ""),
            "type": data.get("type", ""),
            "duration": data.get("duration", 0),
            "original_url": data.get("original_url", ""),
            "client_ip": data.get("client_ip", ""),
            "files": data.get("files", []),
        })
    entries.sort(key=lambda e: e["files"][0]["relative_path"] if e["files"] else "", reverse=True)
    total = len(entries)
    start = (page - 1) * page_size
    end = start + page_size
    return {"entries": entries[start:end], "total": total, "page": page, "page_size": page_size, "has_more": end < total}


# --- 解析 ---


@app.post("/api/parse")
async def parse_link_post(request: Request):
    """支持 url 或 text 字段，会自动从文案中提取链接"""
    content_type = request.headers.get("content-type", "")
    client_ip = _get_client_ip(request)
    logger.info(f"[POST] Content-Type: {content_type}, IP: {client_ip}")

    body = await request.body()
    text = body.decode("utf-8", errors="replace")
    logger.info(f"[POST] 原始 body: {text[:200]}")

    raw = ""

    if "application/json" in content_type:
        try:
            data = json.loads(text)
            raw = data.get("url", "") or data.get("text", "")
        except json.JSONDecodeError:
            logger.warning("[POST] JSON 解析失败")
    elif "application/x-www-form-urlencoded" in content_type:
        raw = text
    else:
        raw = text

    raw = raw.strip()
    if not raw:
        raise HTTPException(400, "缺少 url 或 text 参数")

    logger.info(f"[POST] 提取到: {raw[:120]}")
    return await _do_parse(raw, client_ip)


@app.post("/api/batch-parse")
async def batch_parse_post(request: Request):
    """批量解析，支持 JSON 数组或多行文本"""
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    text = body.decode("utf-8", errors="replace")

    urls = []
    if "application/json" in content_type:
        try:
            data = json.loads(text)
            if isinstance(data, list):
                urls = [str(u).strip() for u in data if u]
            elif isinstance(data, dict):
                raw = data.get("urls", []) or data.get("text", "")
                if isinstance(raw, list):
                    urls = [str(u).strip() for u in raw if u]
                elif isinstance(raw, str):
                    urls = [line.strip() for line in raw.splitlines() if line.strip()]
        except json.JSONDecodeError:
            raise HTTPException(400, "无效的 JSON")
    else:
        urls = [line.strip() for line in text.splitlines() if line.strip()]

    if not urls:
        raise HTTPException(400, "缺少 url 参数")

    logger.info(f"[批量解析] 共 {len(urls)} 个链接")
    results = []
    for url in urls:
        try:
            result = await _do_parse(url)
            results.append(result)
        except Exception as e:
            results.append({"success": False, "url": url, "error": str(e)})

    return {"total": len(urls), "results": results}


@app.get("/api/parse")
async def parse_link_get(request: Request, url: str = Query(..., description="链接或包含链接的文案")):
    client_ip = _get_client_ip(request)
    return await _do_parse(url.strip(), client_ip)


async def _do_parse(raw: str, client_ip: str = "unknown") -> dict:
    url = extract_url(raw)
    if not url.startswith("http"):
        url = "https://" + url

    logger.info(f"{'='*60}")
    logger.info(f"[解析] 原文: {raw[:120]}")
    logger.info(f"[解析] 提取后: {url}")
    logger.info(f"[解析] IP: {client_ip}")

    async with httpx.AsyncClient(
        timeout=30,
        headers={"User-Agent": IOS_UA},
        follow_redirects=False,
    ) as client:
        # Step 1: 短链
        resolved_url = url
        if any(d in url for d in ("v.douyin.com", "jx.douyin.com", "b23.tv", "xhslink.com")):
            resolved_url = await resolve_short_link(url, client)
            logger.info(f"[解析] 短链解析后: {resolved_url}")

        # Step 2: 查缓存（用 resolved_url 做 key）
        cached = _check_cache(resolved_url)
        if cached:
            return cached

        # Step 3: 平台判断 + 解析
        platform = _detect_platform(resolved_url)
        info = None
        downloaded_files = []

        if "douyin.com" in resolved_url or "iesdouyin.com" in resolved_url:
            logger.info(f"[解析] 平台: 抖音")
            vid_info = extract_douyin_id(resolved_url)
            if vid_info:
                vid, vtype = vid_info
                try:
                    urls_to_try = [
                        f"https://m.douyin.com/share/{vtype}/{vid}",
                        f"https://www.douyin.com/{vtype}/{vid}",
                    ]
                    for u in urls_to_try:
                        try:
                            info = await parse_douyin_video(u, client)
                            break
                        except Exception as e:
                            logger.warning(f"[抖音] {u} 解析失败: {e}")
                            continue
                    if not info:
                        logger.warning("[抖音] 页面解析全部失败, 尝试 API")
                        try:
                            info = await parse_douyin_slides_api(vid, client)
                        except Exception as e2:
                            logger.warning(f"[抖音] slides API 失败: {e2}, 尝试 iteminfo API")
                            info = await parse_douyin_iteminfo_api(vid, client)
                except Exception as e:
                    logger.error(f"[抖音] 所有方式失败: {e}")
                    try:
                        info = parse_with_ytdlp(resolved_url)
                    except Exception:
                        raise HTTPException(500, f"抖音解析失败: {str(e)}")
            else:
                try:
                    info = parse_with_ytdlp(resolved_url)
                except Exception as e:
                    raise HTTPException(500, f"解析失败: {str(e)}")
        else:
            logger.info(f"[解析] 平台: {platform}, 使用 yt-dlp")
            try:
                info = parse_with_ytdlp(resolved_url)
            except Exception as e:
                raise HTTPException(500, f"解析失败: {str(e)}")

        if not info:
            raise HTTPException(500, "解析结果为空")

        # Step 4: 下载
        try:
            if info["type"] == "slides" and info.get("image_urls"):
                logger.info(f"[下载] 图文模式, 共 {len(info['image_urls'])} 张图片")
                for i, img_url in enumerate(info["image_urls"]):
                    try:
                        fpath, rel = await download_file(img_url, ".jpg", client, platform)
                        downloaded_files.append({
                            "type": "image",
                            "filename": fpath.name,
                            "relative_path": rel,
                            "url": f"{PREFIX}/api/download/{rel}",
                            "thumb": f"{PREFIX}/api/thumb/{rel}",
                        })
                    except Exception as e:
                        logger.error(f"[下载] 图片 {i} 失败: {e}")
                        continue
            elif info.get("video_url"):
                if "douyin.com" in resolved_url or "iesdouyin.com" in resolved_url:
                    logger.info("[下载] 抖音视频直接下载")
                    fpath, rel = await download_file(info["video_url"], ".mp4", client, platform)
                    downloaded_files.append({
                        "type": "video",
                        "filename": fpath.name,
                        "relative_path": rel,
                        "url": f"{PREFIX}/api/download/{rel}",
                    })
                else:
                    logger.info("[下载] yt-dlp 下载")
                    try:
                        fpath, rel = download_with_ytdlp(resolved_url, platform)
                        downloaded_files.append({
                            "type": "video",
                            "filename": fpath.name,
                            "relative_path": rel,
                            "url": f"{PREFIX}/api/download/{rel}",
                        })
                    except Exception:
                        if info.get("video_url"):
                            fpath, rel = await download_file(info["video_url"], ".mp4", client, platform)
                            downloaded_files.append({
                                "type": "video",
                                "filename": fpath.name,
                                "relative_path": rel,
                                "url": f"{PREFIX}/api/download/{rel}",
                            })
            elif info.get("formats"):
                logger.info("[下载] yt-dlp 格式列表下载")
                fpath, rel = download_with_ytdlp(resolved_url, platform)
                downloaded_files.append({
                    "type": "video",
                    "filename": fpath.name,
                    "relative_path": rel,
                    "url": f"{PREFIX}/api/download/{rel}",
                })
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[下载] 异常: {e}", exc_info=True)
            raise HTTPException(500, f"下载失败: {str(e)}")

    result = {
        "success": True,
        "platform": platform,
        "title": info.get("title", ""),
        "author": info.get("author", ""),
        "type": info.get("type", ""),
        "duration": info.get("duration", 0),
        "original_url": url,
        "resolved_url": resolved_url,
        "files": downloaded_files,
        "client_ip": client_ip,
    }

    # 写入缓存
    _update_cache(resolved_url, result)

    logger.info(f"[完成] {json.dumps(result, ensure_ascii=False)}")
    logger.info(f"{'='*60}")
    return result


# --- 缩略图 ---

@app.get("/api/thumb/{file_path:path}")
async def thumb_file_endpoint(file_path: str):
    thumb_path = THUMB_DIR / file_path
    # 视频缩略图为同名 .jpg
    suffix = Path(file_path).suffix.lower()
    if suffix in (".mp4", ".mkv", ".webm", ".flv", ".mov", ".avi"):
        thumb_path = thumb_path.with_suffix(".jpg")
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/jpeg", filename=thumb_path.name)
    # 无缩略图时重定向到原图
    return RedirectResponse(url=f"{PREFIX}/api/download/{file_path}", status_code=302)


# --- 文件下载 ---

@app.get("/api/download/{file_path:path}")
async def api_download_file_endpoint(file_path: str):
    fpath = DOWNLOAD_DIR / file_path
    if not fpath.exists():
        raise HTTPException(404, "文件不存在")
    suffix = fpath.suffix.lower()
    media_types = {
        ".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
        ".mp3": "audio/mpeg", ".flac": "audio/flac",
    }
    media_type = media_types.get(suffix, "application/octet-stream")
    logger.info(f"[下载接口] 返回: {file_path} ({media_type})")
    return FileResponse(fpath, media_type=media_type, filename=fpath.name)


# --- 文件列表 ---

@app.get("/api/files")
async def list_files(page: int = 1, page_size: int = 20, platform: str = "", date: str = ""):
    files = []
    all_platforms = set()
    all_dates = set()
    meta = _load_meta()
    for f in sorted(DOWNLOAD_DIR.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file():
            rel = _relative_path(f)
            if rel.startswith("_"):
                continue
            parts = rel.split("/")
            file_date = parts[0] if len(parts) > 0 else ""
            file_platform = parts[1] if len(parts) > 1 else ""
            if file_platform:
                all_platforms.add(file_platform)
            if file_date:
                all_dates.add(file_date)
            if platform and file_platform != platform:
                continue
            if date and file_date != date:
                continue
            entry = {
                "filename": f.name,
                "relative_path": rel,
                "size": f.stat().st_size,
                "url": f"{PREFIX}/api/download/{rel}",
            }
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif",
                                   ".mp4", ".mkv", ".webm", ".flv", ".mov", ".avi"):
                entry["thumb"] = f"{PREFIX}/api/thumb/{rel}"
            if rel in meta:
                m = meta[rel]
                for k in ("width", "height", "title", "author", "platform", "type", "duration", "original_url"):
                    if m.get(k):
                        entry[k] = m[k]
            files.append(entry)
    total = len(files)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "files": files[start:end], "total": total, "page": page, "page_size": page_size, "has_more": end < total,
        "platforms": sorted(all_platforms), "dates": sorted(all_dates, reverse=True),
    }


@app.delete("/api/files")
async def clear_files():
    """仅列出文件，不删除（文件永久保留）"""
    count = sum(1 for f in DOWNLOAD_DIR.rglob("*") if f.is_file())
    return {"total": count, "message": "文件永久保留，不提供删除接口"}


if __name__ == "__main__":
    import socket
    import uvicorn
    import shutil

    def _get_local_ips():
        ips = []
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip != "127.0.0.1" and ip not in ips:
                ips.append(ip)
        return ips

    ffmpeg_path = shutil.which("ffmpeg")
    prefix_display = PREFIX or "/"
    local_url = f"http://localhost:{PORT}{prefix_display}".rstrip("/") + "/"
    network_urls = [f"http://{ip}:{PORT}{prefix_display}".rstrip("/") + "/" for ip in _get_local_ips()]

    print()
    print("  MediaFetch 媒体抓取")
    print()
    print(f"  -> Local:   {local_url}")
    for url in network_urls:
        print(f"  -> Network: {url}")
    print()
    print("  配置:")
    print(f"    端口       {PORT}")
    print(f"    路径前缀   {PREFIX or '/'}")
    print(f"    下载目录   {DOWNLOAD_DIR}")
    print(f"    FFmpeg     {ffmpeg_path or '未找到'}")
    print(f"    代理       {PROXY or '未配置'}")
    print(f"    定时清理   {CLEANUP_CRON or '未启用'}")
    print()

    start_cleanup_thread()

    try:
        uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，正在退出...")
    finally:
        os._exit(0)

"""批量生成历史文件缩略图

扫描 downloads/ 目录下所有图片和视频，为缺少缩略图的文件生成缩略图。
缩略图存储在 downloads/_thumbs/ 下，目录结构与原文件一致。

用法:
    python gen_thumbs.py                # 只处理缺失的缩略图
    python gen_thumbs.py --force        # 强制重新生成所有缩略图
    python gen_thumbs.py --dry-run      # 仅预览，不实际生成
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("错误: 需要 Pillow，请运行 pip install Pillow")
    sys.exit(1)

# 配置（与 server.py 一致）
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / os.getenv("MF_DOWNLOADS_DIR", "downloads")
THUMB_DIR = DOWNLOAD_DIR / "_thumbs"
THUMB_MAX_WIDTH = 400
THUMB_QUALITY = 80

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".flv", ".mov", ".avi"}
ALL_EXTS = IMAGE_EXTS | VIDEO_EXTS


def find_media_files() -> list[Path]:
    """找出所有媒体文件（排除 _thumbs 目录）"""
    files = []
    for f in sorted(DOWNLOAD_DIR.rglob("*")):
        if f.is_file() and f.suffix.lower() in ALL_EXTS:
            rel = f.relative_to(DOWNLOAD_DIR)
            if str(rel).startswith("_thumbs"):
                continue
            files.append(f)
    return files


def thumb_path_for(original: Path) -> Path:
    """根据原文件路径计算缩略图路径"""
    rel = original.relative_to(DOWNLOAD_DIR)
    return THUMB_DIR / rel


def generate_image_thumb(original: Path, thumb_path: Path, force: bool = False) -> bool:
    """生成图片缩略图，返回是否成功"""
    if thumb_path.exists() and not force:
        return False
    try:
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(original)
        if img.width > THUMB_MAX_WIDTH:
            ratio = THUMB_MAX_WIDTH / img.width
            new_size = (THUMB_MAX_WIDTH, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(thumb_path, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return True
    except Exception as e:
        print(f"  [失败] {original.name}: {e}")
        return False


def generate_video_thumb(original: Path, thumb_path: Path, force: bool = False) -> bool:
    """生成视频缩略图，返回是否成功"""
    if thumb_path.exists() and not force:
        return False
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print(f"  [跳过] {original.name}: FFmpeg 未找到")
        return False
    try:
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [ffmpeg, "-ss", "1", "-i", str(original),
             "-vframes", "1", "-vf", f"scale={THUMB_MAX_WIDTH}:-1",
             "-q:v", "3", "-y", str(thumb_path)],
            capture_output=True, text=True, timeout=60)
        if thumb_path.exists():
            return True
        print(f"  [失败] {original.name}: {result.stderr[:120]}")
        return False
    except Exception as e:
        print(f"  [失败] {original.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="批量生成历史文件缩略图")
    parser.add_argument("--force", action="store_true", help="强制重新生成所有缩略图")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际生成")
    args = parser.parse_args()

    if not DOWNLOAD_DIR.exists():
        print(f"下载目录不存在: {DOWNLOAD_DIR}")
        sys.exit(1)

    media_files = find_media_files()
    print(f"扫描到 {len(media_files)} 个媒体文件")

    to_generate = []
    for f in media_files:
        tp = thumb_path_for(f)
        if args.force or not tp.exists():
            to_generate.append(f)

    if not to_generate:
        print("所有缩略图已存在，无需生成")
        return

    print(f"需要生成 {len(to_generate)} 个缩略图")

    if args.dry_run:
        for f in to_generate:
            kind = "图片" if f.suffix.lower() in IMAGE_EXTS else "视频"
            print(f"  [预览] {kind}: {f.relative_to(DOWNLOAD_DIR)}")
        return

    success = 0
    failed = 0
    for i, f in enumerate(to_generate, 1):
        tp = thumb_path_for(f)
        kind = "图片" if f.suffix.lower() in IMAGE_EXTS else "视频"
        print(f"[{i}/{len(to_generate)}] {kind}: {f.relative_to(DOWNLOAD_DIR)}", end=" ... ")
        if f.suffix.lower() in IMAGE_EXTS:
            ok = generate_image_thumb(f, tp, force=args.force)
        else:
            ok = generate_video_thumb(f, tp, force=args.force)
        if ok:
            print("OK")
            success += 1
        else:
            failed += 1

    print(f"\n完成: 成功 {success}, 失败 {failed}, 跳过 {len(media_files) - len(to_generate)}")


if __name__ == "__main__":
    main()

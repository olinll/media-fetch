"""
聚合脚本：将 downloads/{日期}/{平台}/ 目录下的所有文件合并到一个文件夹中

用法: python merge_downloads.py
输出: downloads_all/ 目录，所有文件平铺，重复文件名自动加数字后缀
"""

import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
MERGE_DIR = BASE_DIR / "downloads_all"


def merge_files():
    MERGE_DIR.mkdir(exist_ok=True)

    count = 0
    skipped = 0

    for f in DOWNLOADS_DIR.rglob("*"):
        if not f.is_file():
            continue

        dest = MERGE_DIR / f.name

        # 文件名重复时添加数字后缀
        if dest.exists():
            stem = f.stem
            suffix = f.suffix
            i = 1
            while dest.exists():
                dest = MERGE_DIR / f"{stem}_{i}{suffix}"
                i += 1

        shutil.copy2(f, dest)
        count += 1
        print(f"复制: {f.relative_to(DOWNLOADS_DIR)} -> {dest.name}")

    print(f"\n完成！共复制 {count} 个文件到 {MERGE_DIR}")


if __name__ == "__main__":
    if not DOWNLOADS_DIR.exists():
        print("downloads 文件夹不存在")
    else:
        merge_files()

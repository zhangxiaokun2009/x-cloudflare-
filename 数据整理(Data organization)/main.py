#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_all.py —— 把爬虫产出的所有 JSON 合并成 all.json
(merge_all.py — Merge all JSON files produced by the crawler into all.json)

只保留三个字段：title / cover / video_url
(Only keeps three fields: title / cover / video_url)
自动去重（按 video_url），自动跳过 all.json 自身。
(Auto-deduplicates by video_url, and automatically skips all.json itself.)

用法 (Usage)：
    python merge_all.py                # 扫当前目录 (scan the current directory)
    python merge_all.py ./data         # 扫指定目录 (scan the specified directory)
"""

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- #
# 配置 (Configuration)
# ---------------------------------------------------------------- #
SRC_DIR  = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
OUT_FILE = SRC_DIR / "all.json"
EXCLUDE  = {"all.json"}


# ---------------------------------------------------------------- #
# 单条规范化 (Normalize a single item)
# ---------------------------------------------------------------- #
def norm(item):
    """把一个 dict 尝试转成 {title, cover, video_url}，不行就返回 None
       (Try to convert a dict into {title, cover, video_url}; return None if not possible)"""
    if not isinstance(item, dict):
        return None

    # 标题：兼容 title / text / full_text
    # (Title: compatible with title / text / full_text)
    title = item.get("title")
    if title is None:
        title = item.get("text") or item.get("full_text") or ""

    # 封面：兼容 cover / thumbnail / media_url
    # (Cover: compatible with cover / thumbnail / media_url)
    cover = item.get("cover") or item.get("thumbnail") or item.get("media_url") or ""

    # 视频：兼容 video_url / url / m3u8 / play_url
    # (Video: compatible with video_url / url / m3u8 / play_url)
    video = (
        item.get("video_url")
        or item.get("m3u8")
        or item.get("play_url")
        or item.get("url")
        or ""
    )
    video = str(video).strip()
    if not video:
        return None

    # 标题压平换行 / 多余空白
    # (Flatten newlines / excess whitespace in the title)
    title = " ".join(str(title).split())

    return {
        "title": title,
        "cover": str(cover).strip(),
        "video_url": video,
    }


# ---------------------------------------------------------------- #
# 递归遍历任意 JSON 结构 (Recursively traverse any JSON structure)
# ---------------------------------------------------------------- #
def walk(node, out):
    if isinstance(node, dict):
        n = norm(node)
        if n:
            out.append(n)
        for v in node.values():
            walk(v, out)
    elif isinstance(node, list):
        for v in node:
            walk(v, out)


# ---------------------------------------------------------------- #
# 主流程 (Main flow)
# ---------------------------------------------------------------- #
def main():
    print("=" * 64)
    print("  JSON 合并工具 (JSON Merge Tool)")
    print("=" * 64)
    print(f"扫描目录 (Scanning directory)：{SRC_DIR}\n")

    if not SRC_DIR.is_dir():
        print(f"目录不存在 (Directory does not exist)：{SRC_DIR}")
        sys.exit(1)

    files = sorted(
        f for f in SRC_DIR.glob("*.json")
        if f.name not in EXCLUDE and not f.name.startswith(".")
    )

    if not files:
        print("没找到任何 JSON 文件。 (No JSON files found.)")
        sys.exit(1)

    items = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [跳过 (skip)] {f.name}：{e}")
            continue

        before = len(items)
        walk(data, items)
        print(f"  [读取 (read)] {f.name:<32} +{len(items) - before}")

    if not items:
        print("\n所有文件里都没抽到有效条目。 (No valid entries extracted from any file.)")
        sys.exit(1)

    # 按 video_url 去重 (Deduplicate by video_url)
    seen, uniq = set(), []
    for it in items:
        key = it["video_url"]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    OUT_FILE.write_text(
        json.dumps(uniq, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("=" * 64)
    print(f"完成！原始 {len(items)} 条  ->  去重后 {len(uniq)} 条 (Done! Raw {len(items)} items -> {len(uniq)} after dedup)")
    print(f"输出 (Output)：{OUT_FILE}")
    print("=" * 64)

    # 简单抽样预览 (Simple sample preview)
    print("\n示例（前 2 条） (Sample: first 2 items)：")
    print(json.dumps(uniq[:2], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
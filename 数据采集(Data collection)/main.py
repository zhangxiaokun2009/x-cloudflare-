"""
X (Twitter) 视频采集工具 (X (Twitter) Video Collector)

支持 7 种模式 (Supports 7 modes)：
  1. 搜索标签 -> 按热度排序 -> 自动收藏最火的视频帖
     (Search hashtag -> sort by popularity -> auto-bookmark the hottest video posts)
  2. 采集收藏夹内容（标题 + 封面 + m3u8）
     (Collect bookmarks content: title + cover + m3u8)
  3. 搜索标签 + 自动收藏 + 采集收藏夹（连招）
     (Search hashtag + auto-bookmark + collect bookmarks — combo)
  4. 搜索关键词/名字（不限于标签）-> 按热度排序 -> 自动收藏最火的视频帖
     (Search keyword/name (not limited to hashtags) -> sort by popularity -> auto-bookmark the hottest video posts)
  5. 搜索关键词/名字 + 自动收藏 + 采集收藏夹（连招）
     (Search keyword/name + auto-bookmark + collect bookmarks — combo)
  6. 采集某个用户所有带视频的帖子
     (Collect all video posts from a specific user)
  7. 采集单个帖子
     (Collect a single tweet)

依赖 (Dependencies)：
  pip install playwright
  用系统自带的 Edge 就行，不用再 playwright install 装 Chromium
  (Just use the system-provided Edge; no need to run playwright install to download Chromium)
"""

import asyncio
import json
import os
import re
import sys
from urllib.parse import quote

from playwright.async_api import async_playwright


# ==== 可调参数 (Adjustable parameters) ====
HEADLESS       = False
BROWSER        = "msedge"
USER_DATA_DIR  = "./x_profile"
OUTPUT_DIR     = "./output"
SCROLL_PAUSE   = 1500
BOOKMARK_PAUSE = 2500
# ==================


SAVED_FILES = []


# ---------------------------------------------------------------- #
# 工具函数 (Utility functions)
# ---------------------------------------------------------------- #
def _extract_media_from_legacy(legacy):
    media = (legacy.get("extended_entities") or {}).get("media", [])
    if not media:
        media = (legacy.get("entities") or {}).get("media", [])
    return media or []


def _video_from_media(media):
    for m in media:
        if m.get("type") in ("video", "animated_gif"):
            cover = m.get("media_url_https", "")
            variants = m.get("video_info", {}).get("variants", [])
            m3u8, best_mp4, best_br = None, None, -1
            for v in variants:
                ct = (v.get("content_type") or "").lower()
                u = v.get("url", "")
                if not u:
                    continue
                if "mpegurl" in ct and ".m3u8" in u.lower():
                    m3u8 = u
                elif "mp4" in ct:
                    br = v.get("bitrate", 0)
                    if br > best_br:
                        best_br, best_mp4 = br, u
            return cover, (m3u8 or best_mp4)
    return "", ""


def _find_video_media(result, depth=0):
    """本层 + 转推 + 引推，都能找到视频媒体
       (Find video media in this level + retweet + quoted tweet)"""
    if depth > 3 or not isinstance(result, dict):
        return "", ""

    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})

    legacy = result.get("legacy") or {}

    cover, url = _video_from_media(_extract_media_from_legacy(legacy))
    if url:
        return cover, url

    for key in ("retweeted_status_result", "quoted_status_result"):
        sub = legacy.get(key)
        if isinstance(sub, dict) and sub.get("result"):
            cover, url = _find_video_media(sub["result"], depth + 1)
            if url:
                return cover, url

    return "", ""


def parse_tweet(result):
    try:
        if result.get("__typename") == "TweetWithVisibilityResults":
            result = result.get("tweet", {})

        legacy = result.get("legacy") or {}
        tid = result.get("rest_id") or legacy.get("id_str")
        if not tid:
            return None

        text = (legacy.get("full_text") or "").strip()
        likes = legacy.get("favorite_count", 0)
        rts = legacy.get("retweet_count", 0)

        is_reply = bool(
            legacy.get("in_reply_to_status_id_str")
            or legacy.get("in_reply_to_user_id_str")
        )

        views = 0
        try:
            views = int(result.get("views", {}).get("count", 0))
        except Exception:
            pass

        cover, video_url = _find_video_media(result)

        return {
            "id": str(tid),
            "text": text,
            "cover": cover,
            "video_url": video_url,
            "has_video": bool(video_url),
            "likes": likes,
            "retweets": rts,
            "views": views,
            "is_reply": is_reply,
        }
    except Exception:
        return None


def walk_collect(node, out):
    if isinstance(node, dict):
        if "tweet_results" in node:
            tr = node["tweet_results"]
            if isinstance(tr, dict) and tr.get("result"):
                item = parse_tweet(tr["result"])
                if item:
                    out.append(item)
        for v in node.values():
            walk_collect(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_collect(v, out)


def collect_from_responses(responses, filter_replies=False):
    tweets = []
    seen = set()
    for r in responses:
        items = []
        walk_collect(r, items)
        for t in items:
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            if filter_replies and t.get("is_reply"):
                continue
            tweets.append(t)
    return tweets


def extract_from_initial_state(html_or_obj):
    """
    从页面 HTML / window.__INITIAL_STATE__ 里抽推文。
    (Extract tweets from page HTML / window.__INITIAL_STATE__.)
    X 的首屏数据经常是内嵌在 <script> 里的，不走 GraphQL。
    (X's first-screen data is often embedded inside <script> tags, not via GraphQL.)
    """
    texts = []
    if isinstance(html_or_obj, str):
        texts = [html_or_obj]
    else:
        texts = [json.dumps(html_or_obj, ensure_ascii=False)]

    tweets = []
    for text in texts:
        # 粗暴找出所有 {"tweet_results":...} 片段
        # (Crudely find all {"tweet_results":...} fragments)
        for m in re.finditer(r'"tweet_results"', text):
            # 往前/后取一段，用 JSON 的启发式拆出对象不容易，改用整段 dump 后 walk
            # (Take a slice before/after; JSON heuristic extraction is hard — instead dump the whole thing and walk it)
            pass
    # 直接走 JSON 路径 (Just use the JSON path directly)
    if isinstance(html_or_obj, (dict, list)):
        out = []
        walk_collect(html_or_obj, out)
        return out
    return []


async def ensure_login(page):
    print("\n检查登录状态… (Checking login status...)")
    await page.goto("https://x.com/home", wait_until="domcontentloaded",
                    timeout=60000)
    await page.wait_for_timeout(3000)

    if "login" in page.url.lower() or "/i/flow" in page.url.lower():
        print("\n未登录！在浏览器窗口里手动登一下。 (Not logged in! Please log in manually in the browser window.)")
        print("（登完脚本会自动继续，不用重启） (The script will continue automatically after you log in — no need to restart)")
        for _ in range(180):
            await asyncio.sleep(2)
            if "login" not in page.url.lower() and "/i/flow" not in page.url.lower():
                print("登录成功。 (Login successful.)")
                await page.wait_for_timeout(3000)
                return
        raise RuntimeError("登录超时 (Login timeout)")
    else:
        print("已登录。 (Already logged in.)")


async def scroll_page(page, max_times, pause_ms, captured, label=""):
    """
    改进的滚动 (Improved scrolling)：
      - scrollTo 到最底，比 scrollBy 稳
        (scrollTo to the bottom — more stable than scrollBy)
      - 到底后再补滚一屏，让 X 触发下一批请求
        (After reaching the bottom, scroll one more screen to trigger X to fetch the next batch)
      - 连续 8 次没新响应才停
        (Only stop after 8 consecutive rounds with no new responses)
    """
    last, no_new = 0, 0
    for i in range(max_times):
        try:
            await page.evaluate(
                "() => { const h = Math.max("
                "  document.body.scrollHeight,"
                "  document.documentElement.scrollHeight"
                "); window.scrollTo(0, h); }"
            )
            await page.wait_for_timeout(pause_ms)
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(400)
        except Exception:
            pass

        cur = len(captured)
        if cur > last:
            print(f"  [{i+1}/{max_times}] 累计响应 (cumulative responses) {cur}")
            last = cur
            no_new = 0
        else:
            no_new += 1
            if no_new >= 8 and i > 5:
                print(f"  {label}刷到底了（连续 {no_new} 次无新响应） (reached bottom — {no_new} consecutive rounds with no new responses)")
                break

    print(f"  {label}滚动结束，共捕获响应 {len(captured)} 条 (scrolling finished, total captured responses)")


def save_json(data, filename):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, filename)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    SAVED_FILES.append(out)
    return out


def tweets_to_export(tweets):
    return [
        {
            "title": t["text"],
            "cover": t["cover"],
            "video_url": t["video_url"],
        }
        for t in tweets
    ]


def print_preview(videos, n=2):
    print(f"\n示例（前 {min(n, len(videos))} 条） (Sample: first {min(n, len(videos))} items)：")
    print(json.dumps(videos[:n], ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- #
# 模式 1 / 4 共用：搜索 + 收藏
# (Modes 1 / 4 shared: search + bookmark)
# ---------------------------------------------------------------- #
async def search_and_bookmark(context, use_hashtag):
    label = "标签 (hashtag)" if use_hashtag else "关键词/名字 (keyword/name)"
    print("\n" + "=" * 64)
    print(f"  搜索{label}，收藏最火的视频帖 (Search {label} and bookmark the hottest video posts)")
    print("=" * 64)

    if use_hashtag:
        raw = input("请输入标签（不用带 #）：(Enter hashtag, without the #): ").strip().lstrip("#")
    else:
        raw = input("请输入搜索关键词/名字（可含空格）：(Enter search keyword/name, spaces allowed): ").strip()

    if not raw:
        print("没输入，退出。 (No input, exiting.)")
        return

    n_str = input("要收藏多少个？（默认 50）：(How many to bookmark? default 50): ").strip()
    n = int(n_str) if n_str.isdigit() else 50

    metric = input(
        "按什么排序？likes / retweets / views（默认 likes）：(Sort by which metric? likes / retweets / views, default likes): "
    ).strip().lower() or "likes"
    if metric not in ("likes", "retweets", "views"):
        metric = "likes"

    sort_type = input(
        "搜索类型？top=热门 / live=最新（默认 top）：(Search type? top=popular / live=latest, default top): "
    ).strip().lower() or "top"
    if sort_type not in ("top", "live"):
        sort_type = "top"

    search_q = f"#{raw}" if use_hashtag else raw

    print(f"\n搜索词 (Search query): {search_q}  |  排序 (Sort): {metric}  |  类型 (Type): {sort_type}  |  目标 (Target): {n}")

    page = await context.new_page()
    try:
        await ensure_login(page)

        captured = []

        async def on_resp(resp):
            if "SearchTimeline" in resp.url:
                try:
                    captured.append(await resp.json())
                except Exception:
                    pass

        page.on("response", on_resp)

        url = f"https://x.com/search?q={quote(search_q)}&src=typed_query&f={sort_type}"
        print(f"\n打开搜索页… (Opening search page...)")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        print(f"\n滚动加载搜索结果… (Scrolling to load search results...)")
        await scroll_page(page, 60, SCROLL_PAUSE, captured, "搜索 (Search)")

        page.remove_listener("response", on_resp)

        tweets = collect_from_responses(captured)
        print(f"\n共收集 {len(tweets)} 条帖子 (total tweets collected)")

        video_tweets = [t for t in tweets if t["has_video"]]
        print(f"其中含视频：{len(video_tweets)} 条 (of which contain video)")

        if not video_tweets:
            print("没有带视频的帖子。 (No posts with video.)")
            return

        video_tweets.sort(key=lambda t: t[metric], reverse=True)
        top = video_tweets[:n]

        print(f"\n最火 {len(top)} 条 (hottest {len(top)} posts)：")
        for i, t in enumerate(top[:10], 1):
            print(f"  {i:>2}. {t[metric]:>8} | {t['text'][:55]}")

        print(f"\n开始收藏 {len(top)} 条（每条间隔 {BOOKMARK_PAUSE/1000:.1f}s）… (Starting to bookmark {len(top)} posts, interval {BOOKMARK_PAUSE/1000:.1f}s each)")
        collected = []
        for i, t in enumerate(top, 1):
            tweet_url = f"https://x.com/i/status/{t['id']}"
            try:
                await page.goto(tweet_url, wait_until="domcontentloaded",
                                timeout=30000)
                await page.wait_for_timeout(2500)

                if await page.locator('[data-testid="removeBookmark"]').count() > 0:
                    print(f"  [{i}/{len(top)}] 已经收藏过了，跳过 (already bookmarked, skipping)")
                    collected.append(t["id"])
                    continue

                btn = page.locator('[data-testid="bookmark"]').first
                if await btn.count() == 0:
                    print(f"  [{i}/{len(top)}] 找不到书签按钮 (bookmark button not found)")
                    continue

                await btn.click(timeout=5000)
                await page.wait_for_timeout(1200)
                print(f"  [{i}/{len(top)}] 收藏成功 (bookmarked successfully) | {t[metric]:>8} | {t['text'][:45]}")
                collected.append(t["id"])
                await asyncio.sleep(BOOKMARK_PAUSE / 1000)
            except Exception as e:
                print(f"  [{i}/{len(top)}] 收藏失败 (bookmark failed)：{e}")

        result = {
            "query": search_q,
            "query_type": "hashtag" if use_hashtag else "keyword",
            "metric": metric,
            "sort_type": sort_type,
            "target_count": n,
            "collected_count": len(collected),
            "collected_ids": collected,
            "top_tweets": [
                {
                    "id": t["id"],
                    "text": t["text"],
                    "cover": t["cover"],
                    "video_url": t["video_url"],
                    "likes": t["likes"],
                    "retweets": t["retweets"],
                    "views": t["views"],
                }
                for t in top
            ],
        }
        out = save_json(result, "collected_ids.json")
        print()
        print("=" * 64)
        print(f"完成！成功收藏 {len(collected)} / {len(top)} 条 (Done! Successfully bookmarked)")
        print(f"记录已保存 (Record saved)：{out}")
        print("=" * 64)

    finally:
        await page.close()


async def mode1_search_bookmark(context):
    await search_and_bookmark(context, use_hashtag=True)


async def mode4_search_bookmark_keyword(context):
    await search_and_bookmark(context, use_hashtag=False)


# ---------------------------------------------------------------- #
# 模式 2：导出收藏夹 (Mode 2: Export bookmarks)
# ---------------------------------------------------------------- #
async def mode2_export_bookmarks(context):
    print("\n" + "=" * 64)
    print("  模式 2：导出收藏夹里的视频 (Mode 2: Export videos from bookmarks)")
    print("=" * 64)

    page = await context.new_page()
    try:
        await ensure_login(page)

        captured = []

        async def on_resp(resp):
            if "/graphql/" in resp.url and "Bookmark" in resp.url:
                try:
                    captured.append(await resp.json())
                except Exception:
                    pass

        page.on("response", on_resp)

        print(f"\n打开收藏夹… (Opening bookmarks...)")
        await page.goto("https://x.com/i/bookmarks", wait_until="domcontentloaded",
                        timeout=60000)
        await page.wait_for_timeout(5000)

        print(f"\n滚动加载收藏夹… (Scrolling to load bookmarks...)")
        await scroll_page(page, 80, SCROLL_PAUSE, captured, "收藏夹 (Bookmarks)")

        page.remove_listener("response", on_resp)

        videos = [t for t in collect_from_responses(captured) if t["has_video"]]

        if not videos:
            print("\n没找到视频。 (No videos found.)")
            return

        out_videos = tweets_to_export(videos)
        out = save_json(out_videos, "bookmarks_videos.json")

        print()
        print("=" * 64)
        print(f"完成！共 {len(out_videos)} 条视频 (Done! Total videos)")
        print(f"已保存 (Saved)：{out}")
        print("=" * 64)
        print_preview(out_videos)

    finally:
        await page.close()


async def mode3_search_bookmark_and_export(context):
    print("\n" + "=" * 64)
    print("  模式 3：搜索标签 + 收藏 + 导出收藏夹（一步到位） (Mode 3: Search hashtag + bookmark + export bookmarks — all in one)")
    print("=" * 64)

    await mode1_search_bookmark(context)

    print("\n" + "-" * 64)
    print("  接着跑导出收藏夹… (Now running export bookmarks...)")
    print("-" * 64)
    await mode2_export_bookmarks(context)


async def mode5_search_keyword_bookmark_and_export(context):
    print("\n" + "=" * 64)
    print("  模式 5：搜索关键词/名字 + 收藏 + 导出收藏夹（一步到位） (Mode 5: Search keyword/name + bookmark + export bookmarks — all in one)")
    print("=" * 64)

    await mode4_search_bookmark_keyword(context)

    print("\n" + "-" * 64)
    print("  接着跑导出收藏夹… (Now running export bookmarks...)")
    print("-" * 64)
    await mode2_export_bookmarks(context)


# ---------------------------------------------------------------- #
# 模式 6：采某个用户的所有视频帖（重点修复） (Mode 6: Collect all video posts from a user — key fix)
# ---------------------------------------------------------------- #
async def mode6_export_user(context):
    print("\n" + "=" * 64)
    print("  模式 6：采集用户的所有视频帖 (Mode 6: Collect all video posts from a user)")
    print("=" * 64)

    ui = input("请输入用户名（如 IGN）或用户主页 URL：(Enter username (e.g. IGN) or user profile URL): ").strip()
    if not ui:
        print("没输入，退出。 (No input, exiting.)")
        return

    # 滚动次数由用户决定，默认 200
    # (Scroll count is decided by the user, default 200)
    s_str = input(
        "预计要往下滚动加载多少次？（默认 200，每次约 20 条推文；"
        "往大了输没关系，到底了会自动停）："
        "(How many scrolls down to load? default 200, about 20 tweets per scroll; "
        "entering a large number is fine — it will auto-stop at the bottom): "
    ).strip()
    max_scroll = int(s_str) if s_str.isdigit() and int(s_str) > 0 else 200

    if ui.startswith("http"):
        url = ui.rstrip("/")
    else:
        username = ui.lstrip("@")
        url = f"https://x.com/{username}"

    for suffix in ("/with_replies", "/media", "/likes", "/search"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]

    print(f"\n目标 (Target)：{url}")
    print(f"滚动上限 (Scroll limit)：{max_scroll} 次 (times)")

    page = await context.new_page()
    try:
        await ensure_login(page)

        captured = []
        captured_urls = set()
        html_snapshots = []

        # 抓所有 /graphql/ 响应，不再靠接口名筛
        # (Capture all /graphql/ responses; no longer filtering by endpoint name)
        async def on_resp(resp):
            u = resp.url
            if "/graphql/" not in u:
                return
            try:
                name = u.split("/graphql/")[-1].split("?")[0]
                captured_urls.add(name)
            except Exception:
                pass

            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                captured.append(await resp.json())
            except Exception:
                pass

        page.on("response", on_resp)

        print(f"\n打开用户主页… (Opening user profile...)")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        # 首屏 HTML 兜底 (First-screen HTML fallback)
        try:
            state = await page.evaluate(
                "() => window.__INITIAL_STATE__ ? JSON.parse(JSON.stringify(window.__INITIAL_STATE__)) : null"
            )
            if state:
                html_snapshots.append(state)
                print("  （已抓到 window.__INITIAL_STATE__） (captured window.__INITIAL_STATE__)")
        except Exception:
            pass

        print(f"\n滚动加载用户推文… (Scrolling to load user tweets...)")
        await scroll_page(page, max_scroll, SCROLL_PAUSE, captured, "用户主页 (User profile)")

        # 滚动结束再抓一次 __INITIAL_STATE__
        # (Capture __INITIAL_STATE__ once more after scrolling ends)
        try:
            state = await page.evaluate(
                "() => window.__INITIAL_STATE__ ? JSON.parse(JSON.stringify(window.__INITIAL_STATE__)) : null"
            )
            if state:
                html_snapshots.append(state)
        except Exception:
            pass

        page.remove_listener("response", on_resp)

        print(f"\n共捕获 {len(captured)} 条 GraphQL 响应 (total GraphQL responses captured)")
        if captured_urls:
            print("涉及接口（去重后前 12 个） (endpoints involved, first 12 after dedup)：")
            for n in list(captured_urls)[:12]:
                print(f"  - {n}")

        # 来源 1：GraphQL (Source 1: GraphQL)
        tweets = collect_from_responses(captured, filter_replies=True)
        print(f"\n从 GraphQL 响应里抽到 {len(tweets)} 条原创推文 (original tweets extracted from GraphQL responses)")

        # 来源 2：HTML 首屏 (Source 2: HTML first screen)
        if html_snapshots:
            html_tweets = []
            for s in html_snapshots:
                out = []
                walk_collect(s, out)
                html_tweets.extend(out)
            seen = {t["id"] for t in tweets}
            extra = 0
            for t in html_tweets:
                if t["id"] in seen:
                    continue
                if t.get("is_reply"):
                    continue
                seen.add(t["id"])
                tweets.append(t)
                extra += 1
            if extra:
                print(f"从 HTML 首屏里额外抽到 {extra} 条 (extra items extracted from HTML first screen)")

        print(f"\n合计 {len(tweets)} 条原创推文 (total original tweets)")

        videos = [t for t in tweets if t["has_video"]]
        print(f"其中含视频：{len(videos)} 条 (of which contain video)")

        if not videos:
            debug = {
                "user_url": url,
                "max_scroll": max_scroll,
                "responses_count": len(captured),
                "graphql_endpoints": sorted(captured_urls),
                "html_state_found": bool(html_snapshots),
                "tweets_count": len(tweets),
                "first_3_tweets": tweets[:3],
            }
            dbg = save_json(debug, "user_debug.json")
            print("\n没采到视频。已写出诊断文件： (No videos collected. Diagnostic file written:)")
            print(f"  {dbg}")
            print("请把这个文件发我，我看看 X 这次把视频藏哪了。 (Please send me this file so I can see where X hid the videos this time.)")
            return

        out_videos = tweets_to_export(videos)
        out = save_json(out_videos, "user_videos.json")

        print()
        print("=" * 64)
        print(f"完成！共 {len(out_videos)} 条视频 (Done! Total videos)")
        print(f"已保存 (Saved)：{out}")
        print("=" * 64)
        print_preview(out_videos)

    finally:
        await page.close()


# ---------------------------------------------------------------- #
# 模式 7：采单个帖子 (Mode 7: Collect a single tweet)
# ---------------------------------------------------------------- #
async def mode7_export_single(context):
    print("\n" + "=" * 64)
    print("  模式 7：采集单个帖子 (Mode 7: Collect a single tweet)")
    print("=" * 64)

    ui = input("请输入推文 URL（如 https://x.com/IGN/status/xxx）：(Enter tweet URL (e.g. https://x.com/IGN/status/xxx)): ").strip()
    if not ui:
        print("没输入，退出。 (No input, exiting.)")
        return
    if not ui.startswith("http"):
        ui = "https://" + ui

    page = await context.new_page()
    try:
        await ensure_login(page)

        captured = []

        async def on_resp(resp):
            if "/graphql/" in resp.url and "TweetDetail" in resp.url:
                try:
                    captured.append(await resp.json())
                except Exception:
                    pass

        page.on("response", on_resp)

        print(f"\n打开帖子… (Opening tweet...)")
        await page.goto(ui, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        await page.wait_for_timeout(3000)

        # 首屏兜底 (First-screen fallback)
        try:
            state = await page.evaluate(
                "() => window.__INITIAL_STATE__ ? JSON.parse(JSON.stringify(window.__INITIAL_STATE__)) : null"
            )
            if state:
                captured.append(state)
        except Exception:
            pass

        page.remove_listener("response", on_resp)

        tweets = collect_from_responses(captured)
        videos = [t for t in tweets if t["has_video"]]

        if not videos:
            print("\n没找到视频。可能的原因： (No video found. Possible reasons:)")
            print("- 推文是外链视频（YouTube 之类） (- The tweet links to an external video, e.g. YouTube)")
            print("- 推文本身就没视频 (- The tweet itself has no video)")
            print("- 页面结构变了，重新跑一次试试 (- Page structure changed; try running again)")
            return

        out_videos = tweets_to_export(videos)
        out = save_json(out_videos, "single_video.json")

        print()
        print("=" * 64)
        print(f"完成！共 {len(out_videos)} 条 (Done! Total items)")
        print(f"已保存 (Saved)：{out}")
        print("=" * 64)
        print_preview(out_videos)

    finally:
        await page.close()


# ---------------------------------------------------------------- #
# 主入口 (Main entry)
# ---------------------------------------------------------------- #
async def main():
    print()
    print("=" * 64)
    print("   X (Twitter) 视频采集工具 (X (Twitter) Video Collector)")
    print("=" * 64)
    print()
    print("请选择模式 (Please select a mode)：")
    print()
    print("  1. 搜索标签（#xxx），按热度排序，自动收藏最火的视频帖 (Search hashtag (#xxx), sort by popularity, auto-bookmark the hottest video posts)")
    print("  2. 采集收藏夹内容（标题 + 封面 + m3u8） (Collect bookmarks content: title + cover + m3u8)")
    print("  3. 搜索标签 + 自动收藏 + 采集收藏夹（连招） (Search hashtag + auto-bookmark + collect bookmarks — combo)")
    print("  4. 搜索关键词/名字（不限标签），自动收藏最火的视频帖 (Search keyword/name (not limited to hashtags), auto-bookmark the hottest video posts)")
    print("  5. 搜索关键词/名字 + 自动收藏 + 采集收藏夹（连招） (Search keyword/name + auto-bookmark + collect bookmarks — combo)")
    print("  6. 采集某个用户所有带视频的帖子 (Collect all video posts from a specific user)")
    print("  7. 采集单个帖子 (Collect a single tweet)")
    print()

    mode = input("请输入模式编号 (1-7)：(Enter mode number (1-7): )").strip()
    if mode not in ("1", "2", "3", "4", "5", "6", "7"):
        print("无效模式。 (Invalid mode.)")
        sys.exit(1)

    async with async_playwright() as p:
        print("\n启动浏览器… (Launching browser...)")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel=BROWSER,
            headless=HEADLESS,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        try:
            if mode == "1":
                await mode1_search_bookmark(context)
            elif mode == "2":
                await mode2_export_bookmarks(context)
            elif mode == "3":
                await mode3_search_bookmark_and_export(context)
            elif mode == "4":
                await mode4_search_bookmark_keyword(context)
            elif mode == "5":
                await mode5_search_keyword_bookmark_and_export(context)
            elif mode == "6":
                await mode6_export_user(context)
            elif mode == "7":
                await mode7_export_single(context)
        finally:
            await context.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断。 (User interrupted.)")
    except Exception as e:
        print(f"\n运行出错 (Runtime error)：{e}")
        import traceback
        traceback.print_exc()
    finally:
        if SAVED_FILES:
            print()
            print("!" * 64)
            print("  本次运行生成了以下文件 (Files generated during this run)：")
            for f in SAVED_FILES:
                print(f"      - {os.path.abspath(f)}")
            print()
            print("  请尽快【改名】或【转移】到你的数据整理目录， (Please rename or move these files to your data directory ASAP,)")
            print("  否则下次再跑同一个功能，会直接覆盖掉这些文件内容！ (otherwise the next run of the same function will overwrite them directly!)")
            print("!" * 64)
        try:
            input("\n按回车键退出… (Press Enter to exit...)")
        except EOFError:
            pass
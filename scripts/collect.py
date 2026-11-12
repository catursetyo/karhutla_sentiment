#!/usr/bin/env python3
import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
TITLE_RE = re.compile(
    r"karhutla|kebakaran|hutan|lahan|asap|wildfire|forest fire|hotspot|"
    r"titik panas|darurat|bencana|terbakar|membara|api",
    re.I,
)
DEFAULT_QUERIES = [
    "karhutla 2026",
    "karhutla Indonesia",
    "kebakaran hutan Indonesia 2026",
    "asap karhutla",
    "karhutla Kalimantan",
    "karhutla Sumatera",
    "karhutla Papua",
    "karhutla Palangka Raya",
    "karhutla Riau",
    "karhutla Jambi",
    "karhutla Sumatera Selatan",
    "prabowo karhutla",
    "pemerintah karhutla",
    "opini karhutla",
    "komentar karhutla",
    "analisis karhutla",
    "podcast karhutla",
    "vlog karhutla",
    "netizen karhutla",
    "reaksi karhutla",
    "karhutla daftar populer",
    "karhutla kok bisa",
    "kebakaran lahan sawit",
    "hutan terbakar",
    "darurat asap",
    "ISPA karhutla",
    "relawan karhutla",
    "dampak karhutla",
    "penyebab karhutla",
    "solusi karhutla",
    "kebakaran gambut",
    "kabut asap Malaysia",
    "BNPB karhutla",
    "mafia hutan",
    "korporasi sawit karhutla",
    "kualitas udara karhutla",
    "sekolah libur asap",
    "bandara tutup asap",
    "hujan buatan karhutla",
    "relawan pemadam karhutla",
]


def js_runtime_args():
    if shutil.which("node"):
        return ["--js-runtimes", "node"]
    return []


def run_ytdlp(args, timeout):
    cmd = ["yt-dlp", *js_runtime_args(), "--no-warnings", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def search_videos(query, limit, timeout):
    result = run_ytdlp(
        ["--flat-playlist", "--dump-single-json", f"ytsearch{limit}:{query}"],
        timeout,
    )
    if not result.stdout.strip():
        print(f"  search failed: {query}: {result.stderr.strip()[:200]}", file=sys.stderr)
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  invalid search JSON: {query}", file=sys.stderr)
        return []
    entries = []
    for entry in payload.get("entries") or []:
        vid = entry.get("id")
        if vid and VIDEO_ID_RE.match(vid):
            entries.append(
                {
                    "id": vid,
                    "title": entry.get("title") or "",
                    "channel": entry.get("channel") or "",
                    "duration": entry.get("duration"),
                    "query": query,
                }
            )
    return entries


def slim_comment(comment):
    if not isinstance(comment, dict):
        return None
    keep = ("id", "text", "like_count", "parent", "timestamp", "is_pinned")
    return {key: comment.get(key) for key in keep if comment.get(key) is not None}


def log_failure(path, row):
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if not exists:
            writer.writerow(["video_id", "error", "fetched_at", "query"])
        writer.writerow(row)


def fetch_video(video, max_comments, timeout):
    result = run_ytdlp(
        [
            "--skip-download",
            "--write-comments",
            "--extractor-args",
            f"youtube:comment_sort=top;max_comments={max_comments},all,{max_comments},5",
            "--dump-single-json",
            f"https://www.youtube.com/watch?v={video['id']}",
        ],
        timeout,
    )
    if not result.stdout.strip():
        raise RuntimeError(result.stderr.strip()[:300] or "empty yt-dlp output")
    payload = json.loads(result.stdout)
    comments = [
        item for item in (slim_comment(raw) for raw in payload.get("comments") or []) if item
    ]
    meta = {
        "id": payload.get("id") or video["id"],
        "title": payload.get("title") or video["title"],
        "channel": payload.get("channel") or video["channel"],
        "channel_id": payload.get("channel_id"),
        "upload_date": payload.get("upload_date"),
        "duration": payload.get("duration"),
        "view_count": payload.get("view_count"),
        "comment_count": len(comments),
    }
    return meta, comments


def write_json(path, payload):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def count_raw_comments(out_dir):
    total = 0
    for path in (out_dir / "raw").glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        total += len(payload.get("comments") or [])
    return total


def rebuild_comments_csv(out_dir):
    rows = []
    seen = set()
    raw_dir = out_dir / "raw"
    for path in sorted(raw_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        video = payload.get("video") or {}
        for comment in payload.get("comments") or []:
            comment_id = comment.get("id")
            if not comment_id or comment_id in seen:
                continue
            seen.add(comment_id)
            rows.append(
                {
                    "comment_id": comment_id,
                    "video_id": video.get("id") or path.stem,
                    "video_title": video.get("title") or "",
                    "channel": video.get("channel") or "",
                    "text": comment.get("text") or "",
                    "like_count": comment.get("like_count") or 0,
                    "parent": comment.get("parent") or "root",
                    "timestamp": comment.get("timestamp") or "",
                }
            )
    rows.sort(key=lambda row: (row["video_id"], -int(row["like_count"] or 0)))
    csv_path = out_dir / "comments_raw.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "comment_id",
                "video_id",
                "video_title",
                "channel",
                "text",
                "like_count",
                "parent",
                "timestamp",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def rebuild_manifest(out_dir):
    rows = []
    for path in sorted((out_dir / "raw").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        video = payload.get("video") or {}
        rows.append(
            {
                "video_id": video.get("id") or path.stem,
                "status": "ok" if payload.get("comments") else "empty",
                "n_comments": len(payload.get("comments") or []),
                "title": video.get("title") or "",
                "channel": video.get("channel") or "",
                "upload_date": video.get("upload_date") or "",
                "query": payload.get("query") or "",
                "fetched_at": payload.get("fetched_at") or "",
            }
        )
    with (out_dir / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "video_id",
                "status",
                "n_comments",
                "title",
                "channel",
                "upload_date",
                "query",
                "fetched_at",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def parse_video_ids(values):
    ids = []
    for value in values or []:
        match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", value)
        vid = match.group(1) if match else value.strip()
        if VIDEO_ID_RE.match(vid):
            ids.append(vid)
    return ids


def main():
    parser = argparse.ArgumentParser(description="Collect public YouTube comments about karhutla.")
    parser.add_argument("--queries", nargs="+", default=DEFAULT_QUERIES)
    parser.add_argument("--per-query", type=int, default=15)
    parser.add_argument("--max-videos", type=int, default=80)
    parser.add_argument("--max-comments", type=int, default=300)
    parser.add_argument("--target-comments", type=int, default=0)
    parser.add_argument("--min-duration", type=int, default=45)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--video-ids", nargs="+")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-title-filter", action="store_true")
    args = parser.parse_args()

    out_dir = args.out_dir
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_path = out_dir / "failed.csv"

    candidates = []
    if args.video_ids:
        for vid in parse_video_ids(args.video_ids):
            candidates.append({"id": vid, "title": "", "channel": "", "duration": None, "query": "manual"})
    else:
        seen = set()
        for query in args.queries:
            print(f"search: {query}")
            for video in search_videos(query, args.per_query, args.timeout):
                if video["id"] in seen:
                    continue
                seen.add(video["id"])
                candidates.append(video)
            time.sleep(max(0.5, args.sleep / 2))

    filtered = []
    for video in candidates:
        if not args.no_title_filter and video["title"] and not TITLE_RE.search(video["title"]):
            continue
        if video["duration"] is not None and video["duration"] < args.min_duration:
            continue
        filtered.append(video)

    filtered = filtered[: args.max_videos]
    print(f"candidates={len(candidates)} filtered={len(filtered)}")

    fetched = 0
    empty = 0
    errors = 0
    total_comments = count_raw_comments(out_dir)
    if args.target_comments:
        print(f"target_comments={args.target_comments} existing={total_comments}")

    try:
        for index, video in enumerate(filtered, 1):
            if args.target_comments and total_comments >= args.target_comments:
                print(f"target reached: {total_comments}/{args.target_comments}")
                break
            path = raw_dir / f"{video['id']}.json"
            if path.exists() and not args.refresh:
                print(f"[{index}/{len(filtered)}] skip {video['id']} (cached)")
                continue
            print(f"[{index}/{len(filtered)}] fetch {video['id']} | {video['title'][:70]}")
            try:
                meta, comments = fetch_video(video, args.max_comments, args.timeout)
            except subprocess.TimeoutExpired:
                errors += 1
                print("  timeout", file=sys.stderr)
                log_failure(
                    failed_path,
                    [video["id"], "timeout", datetime.now(timezone.utc).isoformat(), video["query"]],
                )
                continue
            except Exception as exc:
                errors += 1
                print(f"  error: {exc}", file=sys.stderr)
                log_failure(
                    failed_path,
                    [video["id"], str(exc)[:200], datetime.now(timezone.utc).isoformat(), video["query"]],
                )
                continue

            payload = {
                "video": meta,
                "comments": comments,
                "query": video["query"],
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            write_json(path, payload)
            total_comments += len(comments)
            if comments:
                fetched += 1
                print(f"  {len(comments)} comments (total {total_comments})")
            else:
                empty += 1
                print("  0 comments (disabled or empty)")
            time.sleep(max(0.5, args.sleep))
    except KeyboardInterrupt:
        print("interrupted; rebuilding outputs")

    total = rebuild_comments_csv(out_dir)
    manifest = rebuild_manifest(out_dir)
    with_comments = sum(1 for row in manifest if row["status"] == "ok")
    print(
        f"done: videos_with_comments={with_comments} empty={empty} errors={errors} "
        f"comments={total} -> {out_dir / 'comments_raw.csv'}"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import csv
import html
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
MENTION_RE = re.compile(r"@\w+")
HASHTAG_RE = re.compile(r"#(\w+)")
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
WHITESPACE_RE = re.compile(r"\s+")
REPEAT_RE = re.compile(r"(.)\1{2,}")
NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
PHONE_RE = re.compile(r"\b\d{7,}\b")
TOPIC_RE = re.compile(
    r"karhutla|kebakaran|kebakar|hutan|lahan|asap|kabut|jerebu|hotspot|"
    r"titik panas|terbakar|membara|pemadam|relawan|gambut|sawit|pohon|"
    r"ispa|polusi|kekeringan|el nino|kemarau|hujan|papua|kalimantan|"
    r"sumatera|riau|jambi|palembang|palangka|banjir|bencana|darurat|"
    r"udara|oksigen|paru|pemerintah|presiden|prabowo|menteri|negara|"
    r"perusahaan|korporasi|pabrik|polisi|aparat",
    re.I,
)
OFFTOPIC_RE = re.compile(
    r"\b(channel|konten|subscribe|subscriber|like|komen|komentar|share|"
    r"upload|video|tugas|sekolah|kuliah|kak|min|bang|guys|hadir|salam|"
    r"support|nonton|izin|ijin|admin)\b",
    re.I,
)
ID_WORDS = {
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "dengan", "untuk",
    "tidak", "tak", "gak", "nggak", "enggak", "saya", "aku", "kami",
    "kita", "mereka", "dia", "ia", "sudah", "belum", "akan", "bisa",
    "harus", "karena", "kalau", "jika", "juga", "sangat", "banget",
    "sekali", "ada", "adalah", "pada", "dalam", "oleh", "sebagai",
    "tapi", "tetapi", "atau", "saat", "ketika", "masih", "hanya", "saja",
    "lebih", "paling", "banyak", "sedikit", "orang", "rakyat", "pemerintah",
    "negara", "hutan", "kebakaran", "asap", "api", "terbakar", "padam",
    "semoga", "ya", "kah", "lah", "pun", "bagi", "secara", "terhadap",
    "hingga", "sampai", "setelah", "sebelum", "selama", "tanpa", "atas",
    "bawah", "luar", "antara", "sebab", "maka", "sehingga", "meskipun",
    "walaupun", "bahwa", "apakah", "bagaimana", "mengapa", "kenapa",
    "siapa", "kapan", "dimana", "mana", "apa", "semua", "setiap",
    "beberapa", "para", "nya", "ku", "mu",
}
EN_WORDS = {
    "the", "and", "is", "are", "was", "were", "of", "to", "in", "for",
    "on", "with", "this", "that", "it", "as", "at", "be", "by", "from",
    "have", "has", "had", "not", "but", "they", "we", "you", "i", "he",
    "she", "will", "would", "can", "could", "should", "about", "what",
    "why", "how", "when", "where", "who", "which", "their", "there",
    "here", "his", "her", "its", "our", "your", "my", "me", "him",
    "them", "us", "do", "does", "did", "been", "being", "just", "very",
    "more", "most", "some", "any", "all", "no", "yes", "if", "then",
    "than", "so", "because", "while", "after", "before", "during",
    "without", "over", "under", "between", "into", "through", "out",
    "up", "down", "off", "again", "once", "don", "doesn", "didn", "isn",
}


def language_ok(text):
    tokens = set(re.findall(r"[a-z]+", text.lower()))
    indonesian = len(tokens & ID_WORDS)
    english = len(tokens & EN_WORDS)
    return not (english >= 2 and english > indonesian)


def clean_text(value):
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text)
    text = EMAIL_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    text = MENTION_RE.sub(" ", text)
    text = HASHTAG_RE.sub(r"\1", text)
    text = ZERO_WIDTH_RE.sub("", text)
    text = PHONE_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def normalize_for_dedup(text):
    value = text.lower()
    value = REPEAT_RE.sub(r"\1", value)
    value = NON_ALNUM_RE.sub(" ", value)
    return WHITESPACE_RE.sub(" ", value).strip()


def alpha_ratio(text):
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0.0
    return sum(char.isalpha() for char in visible) / len(visible)


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def main():
    parser = argparse.ArgumentParser(description="Normalize, filter, and deduplicate collected comments.")
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "comments_raw.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "comments_clean.csv")
    parser.add_argument("--min-chars", type=int, default=10)
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--min-alpha-ratio", type=float, default=0.3)
    parser.add_argument("--min-tokens-fuzzy", type=int, default=8)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--no-offtopic-filter", action="store_true")
    parser.add_argument("--no-language-filter", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"input not found: {args.input}")

    raw_rows = list(read_rows(args.input))
    rows = []
    skipped_reply = skipped_length = skipped_alpha = skipped_offtopic = skipped_language = 0

    for row in raw_rows:
        if not args.include_replies and (row.get("parent") or "root") != "root":
            skipped_reply += 1
            continue
        text = clean_text(row.get("text"))
        if len(text) < args.min_chars or len(text) > args.max_chars:
            skipped_length += 1
            continue
        if alpha_ratio(text) < args.min_alpha_ratio:
            skipped_alpha += 1
            continue
        if (
            not args.no_offtopic_filter
            and OFFTOPIC_RE.search(text)
            and not TOPIC_RE.search(text)
        ):
            skipped_offtopic += 1
            continue
        if not args.no_language_filter and not language_ok(text):
            skipped_language += 1
            continue
        tokens = normalize_for_dedup(text).split()
        if len(tokens) < 2:
            skipped_length += 1
            continue
        rows.append(
            {
                "comment_id": row.get("comment_id") or "",
                "video_id": row.get("video_id") or "",
                "video_title": row.get("video_title") or "",
                "channel": row.get("channel") or "",
                "text": text,
                "text_norm": " ".join(tokens),
                "like_count": int(row.get("like_count") or 0),
                "timestamp": row.get("timestamp") or "",
                "n_words": len(tokens),
            }
        )

    rows.sort(key=lambda item: (-item["like_count"], item["comment_id"]))
    kept = []
    seen_exact = set()
    seen_fuzzy = set()
    duplicate_exact = duplicate_fuzzy = 0
    for row in rows:
        key = row["text_norm"]
        if key in seen_exact:
            duplicate_exact += 1
            continue
        seen_exact.add(key)
        tokens = key.split()
        if len(tokens) >= args.min_tokens_fuzzy:
            fuzzy = " ".join(sorted(set(tokens)))
            if fuzzy in seen_fuzzy:
                duplicate_fuzzy += 1
                continue
            seen_fuzzy.add(fuzzy)
        kept.append(row)

    kept.sort(key=lambda item: (item["video_id"], -item["like_count"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "comment_id",
        "video_id",
        "video_title",
        "channel",
        "text",
        "text_norm",
        "like_count",
        "timestamp",
        "n_words",
    ]
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    print(
        f"raw={len(raw_rows)} kept={len(kept)} "
        f"skipped_reply={skipped_reply} skipped_length={skipped_length} "
        f"skipped_alpha={skipped_alpha} skipped_offtopic={skipped_offtopic} "
        f"skipped_language={skipped_language} "
        f"dup_exact={duplicate_exact} dup_fuzzy={duplicate_fuzzy}"
    )
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()

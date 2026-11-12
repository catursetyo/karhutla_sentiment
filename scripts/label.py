#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import random
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSET_URLS = {
    "positive.tsv": "https://raw.githubusercontent.com/fajri91/InSet/master/positive.tsv",
    "negative.tsv": "https://raw.githubusercontent.com/fajri91/InSet/master/negative.tsv",
}
NEGATIONS = {
    "tidak", "tak", "bukan", "nggak", "gak", "ga", "enggak", "belum",
    "jangan", "tanpa", "kurang", "minim",
}
INTENSIFIERS = {"sangat", "banget", "sekali", "amat", "begitu", "terlalu", "makin", "semakin"}
VALID_LABELS = {"pos", "neg", "neu"}

try:
    from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
    from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory

    _STEMMER = StemmerFactory().create_stemmer()
    _SASTRAWI_STOPWORDS = set(StopWordRemoverFactory().get_stop_words())
except Exception:
    _STEMMER = None
    _SASTRAWI_STOPWORDS = set()

CACHE_VERSION = 3
STEM_PREFIX_RE = re.compile(
    r"^(me|mem|men|meng|meny|di|ter|ber|pe|per|pem|pen|peng|peny|ke|se)[a-z]+$"
)
STEM_SUFFIX_RE = re.compile(r"(kan|an|nya)$")


def normalize_term(value):
    value = value.lower().strip()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def download_lexicon(lexicon_dir):
    lexicon_dir.mkdir(parents=True, exist_ok=True)
    for filename, url in INSET_URLS.items():
        path = lexicon_dir / filename
        if path.exists() and path.stat().st_size > 0:
            continue
        print(f"download: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())


def load_inset(lexicon_dir, min_weight):
    weights = {}
    conflicts = set()
    for filename, sign in (("positive.tsv", 1), ("negative.tsv", -1)):
        path = lexicon_dir / filename
        with path.open(encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                term = normalize_term(parts[0])
                if not term or " " in term:
                    continue
                try:
                    weight = float(parts[1])
                except ValueError:
                    continue
                weight = sign * abs(weight)
                if abs(weight) < min_weight:
                    continue
                if term in weights and (weights[term] > 0) != (weight > 0):
                    conflicts.add(term)
                    continue
                if term not in weights or abs(weight) > abs(weights[term]):
                    weights[term] = weight
    for term in conflicts:
        weights.pop(term, None)
    return weights, conflicts


def load_stopwords(path):
    words = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                value = line.strip().lower()
                if value and not value.startswith("#"):
                    words.add(value)
    return words


def load_domain_lexicon(path):
    if not path.exists():
        return {}
    entries = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2 or parts[0].lower() == "term":
                continue
            term = normalize_term(parts[0])
            try:
                weight = float(parts[1])
            except ValueError:
                continue
            if term:
                entries[term] = weight
    return entries


def make_stemmer(cache_path=None, raw_single=None):
    cache = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    raw_single = raw_single or set()

    def stem(token):
        if _STEMMER is None or not token.isalpha():
            return token
        if token in raw_single or len(token) < 5:
            return token
        if not (
            STEM_PREFIX_RE.match(token)
            or (len(token) >= 8 and STEM_SUFFIX_RE.search(token))
        ):
            return token
        if token not in cache:
            cache[token] = _STEMMER.stem(token)
        return cache[token]

    stem.cache = cache
    return stem


def save_stemmer_cache(stem_token, path):
    if not hasattr(stem_token, "cache"):
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(stem_token.cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def build_lookups(entries, stem_token):
    raw = {}
    stemmed = {}
    for term, weight in entries.items():
        tokens = term.split()
        if not tokens:
            continue
        raw[term] = (weight, term)
        stemmed_key = tuple(stem_token(token) for token in tokens)
        if stemmed_key not in stemmed or abs(weight) > abs(stemmed[stemmed_key][0]):
            stemmed[stemmed_key] = (weight, term)
    max_n = max((len(term.split()) for term in entries), default=1)
    return raw, stemmed, max_n


def cache_signature(lexicon_dir, domain_path, min_weight):
    parts = [f"v={CACHE_VERSION}", f"min={min_weight}"]
    for path in (lexicon_dir / "positive.tsv", lexicon_dir / "negative.tsv", domain_path):
        if path.exists():
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def load_stemmed_cache(path, signature):
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("signature") != signature:
        return None
    return {
        tuple(key.split()): (value[0], value[1])
        for key, value in payload.get("stemmed", {}).items()
    }


def save_stemmed_cache(path, signature, stemmed):
    payload = {
        "signature": signature,
        "stemmed": {" ".join(key): list(value) for key, value in stemmed.items()},
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def score_text(text_norm, raw, stemmed, max_n, stem_token, stopwords, max_signals):
    tokens = text_norm.split()
    if not tokens:
        return 0.0, []
    stems = [stem_token(token) for token in tokens]
    used = [False] * len(tokens)
    signals = []
    seen_terms = set()

    for size in range(min(max_n, len(tokens)), 0, -1):
        for start in range(0, len(tokens) - size + 1):
            if any(used[start : start + size]):
                continue
            if size == 1 and (tokens[start] in stopwords or stems[start] in stopwords):
                continue
            key = " ".join(tokens[start : start + size])
            hit = raw.get(key)
            if hit is None:
                hit = stemmed.get(tuple(stems[start : start + size]))
            if hit is None:
                continue
            weight, term = hit
            if term in seen_terms:
                continue
            seen_terms.add(term)
            context = tokens[max(0, start - 2) : start]
            if any(word in NEGATIONS for word in context):
                weight *= -0.75
            if start > 0 and tokens[start - 1] in INTENSIFIERS:
                weight *= 1.25
            signals.append((weight, term))
            for index in range(start, start + size):
                used[index] = True

    strongest = sorted(signals, key=lambda item: abs(item[0]), reverse=True)[:max_signals]
    return sum(weight for weight, _ in strongest), strongest


def auto_label(score, pos_threshold, neg_threshold):
    if score >= pos_threshold:
        return "pos"
    if score <= neg_threshold:
        return "neg"
    return "neu"


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def stratified_review(rows, size, seed):
    groups = defaultdict(list)
    for row in rows:
        groups[row["label"]].append(row)
    rng = random.Random(seed)
    for items in groups.values():
        rng.shuffle(items)
    labels = [label for label in ("pos", "neg", "neu") if groups.get(label)]
    if not labels:
        return []

    allocation = {label: 0 for label in labels}
    remaining = min(size, len(rows))
    active = list(labels)
    while remaining > 0 and active:
        share = max(1, remaining // len(active))
        progressed = False
        for label in list(active):
            take = min(share, len(groups[label]) - allocation[label], remaining)
            if take > 0:
                allocation[label] += take
                remaining -= take
                progressed = True
            if allocation[label] >= len(groups[label]):
                active.remove(label)
        if not progressed:
            break

    review = []
    for label in labels:
        review.extend(groups[label][: allocation[label]])
    rng.shuffle(review)
    return review[:size]


def main():
    parser = argparse.ArgumentParser(description="Weak-label comments with InSet and a domain lexicon.")
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "comments_clean.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "labeled.csv")
    parser.add_argument("--lexicon-dir", type=Path, default=ROOT / "data" / "lexicon")
    parser.add_argument("--domain-lexicon", type=Path, default=ROOT / "resources" / "domain_lexicon.tsv")
    parser.add_argument("--stopwords", type=Path, default=ROOT / "resources" / "stopwords_id.txt")
    parser.add_argument("--neutral-terms", type=Path, default=ROOT / "resources" / "neutral_terms.txt")
    parser.add_argument("--review-out", type=Path, default=ROOT / "data" / "review_sample.csv")
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--review-size", type=int, default=300)
    parser.add_argument("--pos-threshold", type=float, default=2.5)
    parser.add_argument("--neg-threshold", type=float, default=-2.5)
    parser.add_argument("--min-weight", type=float, default=4.0)
    parser.add_argument("--max-signals", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-stem", action="store_true")
    parser.add_argument("--force-review", action="store_true")
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"input not found: {args.input}")

    download_lexicon(args.lexicon_dir)
    inset, conflicts = load_inset(args.lexicon_dir, args.min_weight)
    domain = load_domain_lexicon(args.domain_lexicon)
    entries = {**inset, **domain}
    stopwords = (
        load_stopwords(args.stopwords)
        | load_stopwords(args.neutral_terms)
        | _SASTRAWI_STOPWORDS
        | NEGATIONS
        | INTENSIFIERS
    )
    token_cache_path = args.lexicon_dir / "token_stems.json"
    raw_single = {term for term in entries if " " not in term}
    stem_token = (
        make_stemmer(token_cache_path, raw_single=raw_single)
        if not args.no_stem
        else (lambda token: token)
    )
    cache_path = args.lexicon_dir / "stemmed_cache.json"
    signature = cache_signature(args.lexicon_dir, args.domain_lexicon, args.min_weight)
    stemmed = None if args.no_stem else load_stemmed_cache(cache_path, signature)
    cache_hit = stemmed is not None
    if stemmed is None:
        raw, stemmed, max_n = build_lookups(entries, stem_token)
        if not args.no_stem and args.lexicon_dir.exists():
            save_stemmed_cache(cache_path, signature, stemmed)
    else:
        raw = {term: (weight, term) for term, weight in entries.items()}
        max_n = max((len(term.split()) for term in entries), default=1)
    print(f"stemmed cache: {'hit' if cache_hit else 'built'}")

    rows = read_csv(args.input)
    for row in rows:
        text_norm = row.get("text_norm") or row.get("text", "").lower()
        score, matched = score_text(
            text_norm, raw, stemmed, max_n, stem_token, stopwords, args.max_signals
        )
        row["label"] = auto_label(score, args.pos_threshold, args.neg_threshold)
        row["score"] = f"{score:.2f}"
        row["matched"] = "; ".join(f"{term}({weight:+.1f})" for weight, term in matched)
        row["label_source"] = "auto"

    manual_applied = 0
    invalid_manual = 0
    if args.review_file and args.review_file.exists():
        review_rows = read_csv(args.review_file)
        manual = {}
        for row in review_rows:
            value = (row.get("manual_label") or "").strip().lower()
            if not value:
                continue
            if value not in VALID_LABELS:
                invalid_manual += 1
                continue
            manual[row["comment_id"]] = value
        for row in rows:
            if row["comment_id"] in manual:
                row["label"] = manual[row["comment_id"]]
                row["label_source"] = "manual"
                manual_applied += 1

    if not args.no_stem:
        save_stemmer_cache(stem_token, token_cache_path)

    fieldnames = [
        "comment_id", "video_id", "video_title", "channel", "text", "text_norm",
        "like_count", "timestamp", "n_words", "label", "score", "matched", "label_source",
    ]
    write_csv(args.output, rows, fieldnames)

    if args.review_file is None or not args.review_file.exists() or args.force_review:
        if args.review_out.exists() and not args.force_review:
            print(f"review sample kept: {args.review_out} (use --force-review to regenerate)")
        else:
            review = stratified_review(rows, args.review_size, args.seed)
            review_rows = [
                {
                    "comment_id": row["comment_id"],
                    "text": row["text"],
                    "auto_label": row["label"],
                    "score": row["score"],
                    "matched": row["matched"],
                    "manual_label": "",
                }
                for row in review
            ]
            write_csv(
                args.review_out,
                review_rows,
                ["comment_id", "text", "auto_label", "score", "matched", "manual_label"],
            )
            print(f"review sample: {args.review_out} ({len(review_rows)} rows)")

    counts = Counter(row["label"] for row in rows)
    sources = Counter(row["label_source"] for row in rows)
    print(f"rows={len(rows)} labels={dict(counts)} sources={dict(sources)}")
    print(
        f"lexicon: inset={len(inset)} domain={len(domain)} conflicts_dropped={len(conflicts)} "
        f"stopwords={len(stopwords)} max_signals={args.max_signals} "
        f"stemming={'off' if args.no_stem or _STEMMER is None else 'on'}"
    )
    if manual_applied:
        print(f"manual labels applied={manual_applied} invalid={invalid_manual}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def allocate(counts, target):
    total = sum(counts.values())
    if total == 0 or target <= 0:
        return {label: 0 for label in counts}
    labels = list(counts)
    allocation = {}
    remainders = []
    for label in labels:
        exact = target * counts[label] / total
        allocation[label] = int(exact)
        remainders.append((exact - allocation[label], label))
    for label in labels:
        if counts[label] > 0 and allocation[label] == 0:
            allocation[label] = 1
    while sum(allocation.values()) > target:
        candidates = [label for label in labels if allocation[label] > 1]
        if not candidates:
            break
        allocation[max(candidates, key=lambda label: allocation[label])] -= 1
    remainders.sort(reverse=True)
    index = 0
    while sum(allocation.values()) < target:
        label = remainders[index % len(remainders)][1]
        if allocation[label] < counts[label]:
            allocation[label] += 1
        index += 1
        if index > target * 3:
            break
    return allocation


def stratified_sample(rows, target, seed):
    groups = defaultdict(list)
    for row in rows:
        groups[row["label"]].append(row)
    rng = random.Random(seed)
    for items in groups.values():
        rng.shuffle(items)
    allocation = allocate({label: len(items) for label, items in groups.items()}, target)
    chosen = []
    for label, items in groups.items():
        chosen.extend(items[: allocation[label]])
    rng.shuffle(chosen)
    return chosen


def main():
    parser = argparse.ArgumentParser(description="Build Kaggle train/test files from labeled comments.")
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "labeled.csv")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data" / "kaggle")
    parser.add_argument("--labels", default="pos,neg")
    parser.add_argument("--test-count", type=int, default=300)
    parser.add_argument("--min-train", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"input not found: {args.input}")

    allowed = {label.strip() for label in args.labels.split(",") if label.strip()}
    rows = read_csv(args.input)
    index_by_key = {}
    filtered = []
    for row in rows:
        if row.get("label") not in allowed:
            continue
        text = (row.get("text") or "").strip()
        key = (row.get("text_norm") or text.lower()).strip()
        if not text:
            continue
        if key in index_by_key:
            current = filtered[index_by_key[key]]
            if row.get("label_source") == "manual" and current.get("label_source") != "manual":
                filtered[index_by_key[key]] = row
            continue
        index_by_key[key] = len(filtered)
        filtered.append(row)

    if len(filtered) < 20:
        sys.exit(f"not enough labeled rows for {sorted(allowed)}: {len(filtered)}")
    neutral_excluded = sum(1 for row in rows if row.get("label") == "neu")
    counts = Counter(row["label"] for row in filtered)
    if len(counts) < 2:
        sys.exit(f"need at least two classes, got {dict(counts)}")
    if min(counts.values()) < 2:
        sys.exit(f"each class needs at least 2 rows, got {dict(counts)}")

    max_test = max(2, len(filtered) - args.min_train)
    target = min(args.test_count, max_test)
    manual = [row for row in filtered if row.get("label_source") == "manual"]
    weak = [row for row in filtered if row.get("label_source") != "manual"]

    if len(manual) >= target:
        test_rows = stratified_sample(manual, target, args.seed)
        test_source = "manual"
    elif manual:
        test_rows = manual
        test_source = "manual_partial"
        print(f"warning: only {len(manual)} manual rows; test set uses all of them", file=sys.stderr)
    else:
        test_rows = stratified_sample(filtered, target, args.seed)
        test_source = "weak"
        print("warning: no manual labels found; test labels are weak estimates", file=sys.stderr)

    test_ids = {row["comment_id"] for row in test_rows}
    train_rows = [row for row in filtered if row["comment_id"] not in test_ids]
    rng = random.Random(args.seed)
    rng.shuffle(train_rows)
    rng.shuffle(test_rows)

    train_out = []
    for index, row in enumerate(train_rows, 1):
        train_out.append({"id": f"kh-{index:05d}", "text": row["text"], "label": row["label"]})
    offset = len(train_out)
    test_out = []
    solution_out = []
    for index, row in enumerate(test_rows, 1):
        test_id = f"kh-{offset + index:05d}"
        test_out.append({"id": test_id, "text": row["text"]})
        solution_out.append({"id": test_id, "label": row["label"]})

    majority = Counter(row["label"] for row in train_out).most_common(1)[0][0]
    submission_out = [{"id": row["id"], "label": majority} for row in test_out]

    out_dir = args.out_dir
    write_csv(out_dir / "train.csv", train_out, ["id", "text", "label"])
    write_csv(out_dir / "test.csv", test_out, ["id", "text"])
    write_csv(out_dir / "solution.csv", solution_out, ["id", "label"])
    write_csv(out_dir / "sample_submission.csv", submission_out, ["id", "label"])

    stats = {
        "date": date.today().isoformat(),
        "total_rows": len(filtered),
        "train_rows": len(train_out),
        "test_rows": len(test_out),
        "test_source": test_source,
        "labels": sorted(allowed),
        "train_distribution": dict(Counter(row["label"] for row in train_rows)),
        "test_distribution": dict(Counter(row["label"] for row in test_rows)),
        "manual_rows_available": len(manual),
        "weak_rows_available": len(weak),
        "neutral_excluded": neutral_excluded,
        "seed": args.seed,
    }
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    description = f"""# Karhutla 2026 — Analisis Sentimen Komentar Publik

Dataset untuk kompetisi klasifikasi sentimen berbahasa Indonesia bertema kebakaran hutan dan lahan (karhutla) 2026.

## Isi

| File | Kolom | Keterangan |
|---|---|---|
| `train.csv` | `id, text, label` | Data latih berlabel |
| `test.csv` | `id, text` | Data uji tanpa label |
| `solution.csv` | `id, label` | Kunci jawaban (jangan dibagikan ke peserta) |
| `sample_submission.csv` | `id, label` | Contoh format submission |

Label: `{", ".join(sorted(allowed))}`.

- `pos` — sentimen positif: dukungan, harapan, apresiasi, solusi.
- `neg` — sentimen negatif: kekecewaan, kemarahan, kritik, keprihatinan.

Baris dengan label `neu` tidak disertakan pada split biner ini ({neutral_excluded} baris).

## Statistik

- Total baris pada file kompetisi: {len(filtered)}
- Train: {len(train_out)} ({dict(Counter(row["label"] for row in train_rows))})
- Test: {len(test_out)} ({dict(Counter(row["label"] for row in test_rows))})
- Sumber label test: {test_source}
- Tanggal dibuat: {date.today().isoformat()}

## Metrik

Macro F1-score. Gunakan `label` yang sama persis dengan daftar label di atas.

## Sumber dan etika

Teks berasal dari komentar publik YouTube tentang karhutla 2026 yang dikumpulkan pada {date.today().isoformat()}. Username, ID kanal komentator, dan metadata pribadi tidak disimpan. Dataset ini untuk riset dan edukasi; teks tetap tunduk pada Ketentuan Layanan YouTube. Jangan publikasikan ulang komentar mentah beserta identitas penggunanya. Untuk kompetisi publik, pertimbangkan membatasi akses atau berkonsultasi soal lisensi.

Label train dihasilkan secara weak supervision (lexicon InSet + lexicon domain) dan dapat mengandung noise. Label test { "diverifikasi manual" if test_source == "manual" else "belum sepenuhnya diverifikasi manual" }.
"""
    (out_dir / "dataset_description.md").write_text(description, encoding="utf-8")

    print(
        f"train={len(train_out)} test={len(test_out)} test_source={test_source} "
        f"train_labels={dict(Counter(row['label'] for row in train_rows))} "
        f"test_labels={dict(Counter(row['label'] for row in test_rows))}"
    )
    print(f"output: {out_dir}")


if __name__ == "__main__":
    main()

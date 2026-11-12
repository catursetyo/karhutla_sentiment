#!/usr/bin/env python3
import argparse
import csv
import sys
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import FeatureUnion, Pipeline

ROOT = Path(__file__).resolve().parent.parent


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description="TF-IDF baseline for the karhutla sentiment competition.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "kaggle")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "kaggle" / "submission_baseline.csv")
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    train_path = args.data_dir / "train.csv"
    test_path = args.data_dir / "test.csv"
    if not train_path.exists() or not test_path.exists():
        sys.exit(f"missing {train_path} or {test_path}")

    train = read_csv(train_path)
    test = read_csv(test_path)
    texts = [row["text"] for row in train]
    labels = [row["label"] for row in train]

    features = FeatureUnion(
        [
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=60000)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=60000)),
        ]
    )
    model = Pipeline(
        [
            ("features", features),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", C=4.0)),
        ]
    )

    folds = min(args.folds, min(labels.count(label) for label in set(labels)))
    if folds >= 2:
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
        predicted = cross_val_predict(model, texts, labels, cv=cv)
        print(classification_report(labels, predicted, digits=3))
        print(f"macro_f1_cv={f1_score(labels, predicted, average='macro'):.4f} folds={folds}")
    else:
        print("warning: too few rows per class for cross-validation", file=sys.stderr)

    model.fit(texts, labels)
    predictions = model.predict([row["text"] for row in test])
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "label"])
        writer.writeheader()
        for row, label in zip(test, predictions):
            writer.writerow({"id": row["id"], "label": label})
    print(f"submission: {args.output} rows={len(test)}")

    solution_path = args.data_dir / "solution.csv"
    if solution_path.exists():
        solution = {row["id"]: row["label"] for row in read_csv(solution_path)}
        truth = [solution[row["id"]] for row in test if row["id"] in solution]
        guesses = [label for row, label in zip(test, predictions) if row["id"] in solution]
        if truth:
            print(f"test_macro_f1={f1_score(truth, guesses, average='macro'):.4f}")


if __name__ == "__main__":
    main()

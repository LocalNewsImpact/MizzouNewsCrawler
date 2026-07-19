import json
import csv
import sys
import os

sys.path.insert(0, "/app")
from src.ml.article_classifier import ArticleClassifier

MODEL = "/app/models/productionmodel.pt"
DATA = "/app/march_rows.json"
OUT = "/app/march_collection_reclassified.csv"
BATCH_SIZE = 32

HEADER = [
    "id", "host", "title", "url", "author", "text",
    "publish_date", "extracted_at", "status", "primary_label", "alternate_label",
    "new_Primary", "new_Primary_confidence", "new_Secondary", "new_Secondary_confidence",
]

print("Loading data...", flush=True)
with open(DATA) as f:
    rows = json.load(f)
total = len(rows)
print(f"Records: {total:,}", flush=True)

# Support resume: count already-written rows (excluding header)
start_batch = 0
if os.path.exists(OUT):
    with open(OUT, encoding="utf-8") as f:
        done_rows = sum(1 for _ in f) - 1  # subtract header
    if done_rows > 0:
        start_batch = (done_rows // BATCH_SIZE) * BATCH_SIZE
        print(f"Resuming from row {start_batch:,} ({done_rows:,} already written)", flush=True)

print("Loading classifier...", flush=True)
classifier = ArticleClassifier(MODEL)
print("Classifier ready.", flush=True)

# Write header only if starting fresh
write_mode = "a" if start_batch > 0 else "w"
with open(OUT, write_mode, newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    if start_batch == 0:
        writer.writerow(HEADER)

    for batch_start in range(start_batch, total, BATCH_SIZE):
        batch = rows[batch_start:batch_start + BATCH_SIZE]
        texts = []
        for r in batch:
            title = (r["title"] or "").strip()
            text = (r["text"] or "").strip()
            combined = (title + " " + text).strip() if text else title
            texts.append(combined if combined else " ")

        preds = classifier.predict_batch(texts, top_k=2)

        batch_rows = []
        for r, pred in zip(batch, preds, strict=False):
            p = pred[0] if len(pred) > 0 else None
            s = pred[1] if len(pred) > 1 else None
            batch_rows.append([
                r["id"], r["host"], r["title"], r["url"], r["author"], r["text"],
                r["pub_date"], r["extracted_at"], r["status"],
                r["primary_label"], r["alternate_label"],
                p.label if p else "",
                round(p.score, 4) if p else "",
                s.label if s else "",
                round(s.score, 4) if s else "",
            ])

        writer.writerows(batch_rows)
        f.flush()  # flush to disk after every batch

        done = min(batch_start + BATCH_SIZE, total)
        print(f"  {done:,}/{total:,}  ({done/total*100:.1f}%)", flush=True)

print("Done.", flush=True)

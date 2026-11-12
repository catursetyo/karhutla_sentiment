# Dataset Sentimen Karhutla 2026

Pipeline untuk mengumpulkan komentar publik YouTube bertema karhutla, membersihkannya, memberi label awal, dan membentuk file kompetisi Kaggle.

## Quickstart

```bash
# 1. Kumpulkan komentar (bisa 10-30 menit; jalankan di tmux)
python3 scripts/collect.py --max-videos 60 --max-comments 300

# 2. Bersihkan, filter, deduplikasi
python3 scripts/clean.py

# 3. Label otomatis + buat sampel review manual
python3 scripts/label.py

# 4. Isi kolom manual_label di data/review_sample.csv (pos/neg/neu)
#    lalu terapkan koreksinya
python3 scripts/label.py --review-file data/review_sample.csv

# 5. Bentuk train/test untuk Kaggle
python3 scripts/split.py
```

Hasil akhir ada di `data/kaggle/`:

- `train.csv` — `id,text,label`
- `test.csv` — `id,text`
- `solution.csv` — `id,label` (jangan diunggah ke peserta)
- `sample_submission.csv`
- `dataset_description.md` — deskripsi siap tempel di halaman kompetisi

## Mengatur pengumpulan

```bash
python3 scripts/collect.py \
  --queries "karhutla 2026" "asap karhutla" "karhutla Kalimantan" \
  --per-query 20 --max-videos 100 --max-comments 500
```

- Collector menyimpan cache per video di `data/raw/`, jadi aman dihentikan dan dilanjutkan.
- Video dengan komentar kosong tetap dicatat agar tidak diambil berulang.
- `data/manifest.csv` merangkum status tiap video.
- Kalau butuh video tertentu: `python3 scripts/collect.py --video-ids <ID_ATAU_URL> ...`.
- `clean.py` membuang komentar off-topic (pujian channel, tugas sekolah, dll) yang tidak menyebut topik karhutla. Matikan dengan `--no-offtopic-filter`.
- Stemming lexicon di-cache di `data/lexicon/`; run pertama lambat, run berikutnya cepat.

## Menambah data hingga ~10rb baris

Saat ini 4.501 komentar mentah menghasilkan 3.151 baris bersih (sekitar 70%), dan 2.134 di antaranya masuk split biner. Untuk mencapai **~10rb baris bersih**, targetkan sekitar **15rb komentar mentah**:

```bash
python3 -u scripts/collect.py \
  --per-query 30 \
  --max-videos 400 \
  --max-comments 500 \
  --target-comments 15000 \
  --sleep 1.5
```

Collector akan mencari ulang, melewati video yang sudah ada di cache, dan berhenti sendiri saat total komentar mencapai target. Jalankan di `tmux`/`nohup` karena bisa berjam-jam. Kalau terhenti, jalankan perintah yang sama lagi—video yang sudah diambil akan di-skip.

Setelah koleksi selesai:

```bash
python3 scripts/clean.py
python3 scripts/label.py
python3 scripts/split.py --test-count 300 --min-train 500
```

Kalau ingin **10rb baris train biner** (bukan 10rb baris bersih), targetnya lebih tinggi: sekitar 22rb komentar mentah, karena baris netral dibuang dari split biner.

Lakukan labeling manual **setelah** ekspansi selesai, supaya sampel review diambil dari data yang sudah lengkap. Kalau sudah terlanjur melabeli, jangan pakai `--force-review`; label manual tetap diterapkan berdasarkan `comment_id`.

## Labeling

1. `label.py` memakai lexicon InSet (positif/negatif) + `resources/domain_lexicon.tsv`, dengan stemming Sastrawi dan penanganan negasi sederhana.
2. Istilah yang muncul di file positif **dan** negatif InSet dibuang karena ambigu, lalu sebagian diisi manual lewat lexicon domain.
3. Komentar tanpa sinyal kuat diberi label `neu`.
4. `data/review_sample.csv` berisi 300 baris, diseimbangkan 100 `pos`, 100 `neg`, dan 100 `neu`. Isi `manual_label` dengan `pos`, `neg`, atau `neu`.
5. Setelah koreksi diterapkan, semua baris yang punya label manual ditandai `label_source=manual`.

**Penting:** label otomatis adalah weak supervision dan masih noisy. Untuk kompetisi, label manual harus diprioritaskan. `split.py` otomatis memakai baris berlabel manual sebagai test set supaya leaderboard tidak mengukur noise lexicon. Kalau semua 300 baris dilabeli, test set biner yang terbentuk adalah 200 baris dengan komposisi 100 `pos` dan 100 `neg` (baris `neu` dikeluarkan).

## Baseline

Setelah `data/kaggle/` terbentuk:

```bash
python3 scripts/baseline.py
```

Baseline memakai TF-IDF word + char n-gram dan logistic regression, mencetak macro F1 cross-validation, lalu menulis `data/kaggle/submission_baseline.csv`. Gunakan ini untuk memastikan kompetisi dan submission berjalan sebelum di-publish.

## Membuat kompetisi di Kaggle

1. Buka `kaggle.com/competitions` → **Create** → **Community Competition**.
2. Unggah `train.csv`, `test.csv`, dan `sample_submission.csv`.
3. Unggah `solution.csv` sebagai **solution file** dan jangan dibagikan.
4. Set metrik **Macro F1**.
5. Tempel isi `dataset_description.md` ke halaman Overview.
6. Untuk kompetisi publik, pertimbangkan lisensi dan ToS YouTube. Dataset komentar publik sebaiknya dipakai untuk riset/edukasi; jangan publikasikan ulang identitas komentator.

## Timeline 2 hari

- **Hari 1 pagi:** jalankan collector (60-100 video), sambil menyiapkan halaman kompetisi.
- **Hari 1 siang:** `clean.py` dan `label.py`, cek distribusi label.
- **Hari 1 malam:** review manual 200-300 baris di `review_sample.csv`.
- **Hari 2 pagi:** terapkan review, `split.py`, cek `stats.json`, unggah ke Kaggle.
- **Hari 2 siang:** buat baseline notebook (TF-IDF + logistic regression) untuk memastikan kompetisi berjalan.
- **Hari 2 sore:** uji submission, atur leaderboard, publish.

## Catatan kualitas

- Lexicon tidak paham sarkasme, implikasi, atau konteks panjang. Karena itu review manual test set wajib.
- Model baseline yang disarankan: TF-IDF word + char n-gram, lalu linear SVM/logistic regression; atau IndoBERT kalau waktu memungkinkan.
- Distribusi kelas bisa tidak seimbang. Gunakan macro F1, bukan accuracy.
- Split dilakukan per komentar, bukan per video. Ini bisa membuat skor sedikit optimistis karena gaya komentar dalam satu video mirip. Untuk kompetisi yang lebih ketat, split per `video_id`.
- Pertimbangkan membuang komentar yang hanya berisi emoji/mention; cleaner sudah menyaring sebagian.

## Lisensi dan etika

Komentar diambil dari konten publik, tanpa username. Teks komentar tetap milik penulisnya dan tunduk pada YouTube ToS. Anotasi yang kamu buat dapat dilisensikan terpisah (misalnya CC BY 4.0). Jangan gunakan dataset untuk profiling individu atau doxing. Untuk penggunaan komersial, konsultasikan dengan pihak yang berwenang.

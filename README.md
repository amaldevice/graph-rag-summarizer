# Summarizer Project

Prototype pipeline untuk **long-document summarization** berbasis **Docling + selectable object storage + selectable Qdrant backend + Graph Analysis + LLM**. Project ini sekarang dipisah menjadi dua alur utama agar lebih jelas: satu script khusus untuk **upload/indexing dokumen ke Qdrant**, dan satu script khusus untuk **retrieval + summarization** dari data yang sudah ada di Qdrant.

## Gambaran alur

Project ini mendukung dua proses utama:
- **Upload / Indexing**: PDF diproses dengan Docling, dipecah menjadi chunk, diubah menjadi embedding, lalu disimpan ke Qdrant.
- **Retrieval / Summarization**: query di-embedding, chunk relevan diambil dari Qdrant, lalu diproses dengan graph pipeline, LLM summarization, evaluation, quality gate, dan feedback loop.

Arsitektur ini lebih aman untuk handoff karena pengguna project tidak perlu bingung kapan harus upload ulang dokumen dan kapan cukup melakukan query ke database vector.

Batas implementasi aktif saat ini:
- **Sebelum / sampai Vector DB**: flow ingest mengikuti arah `graph_rag-pipeline` (Docling -> object storage backend -> Qdrant backend).
- **Setelah Vector DB / semantic retrieval**: flow besar tetap memakai pipeline `summarizer_project` yang sudah ada, dengan penyesuaian pada format payload retrieval (`page` dinormalisasi ke `page_no`, `image_urls` ke `image_url`).

---

## Struktur folder

```text
summarizer_project/
├── .vscode/
├── config/
│   ├── __init__.py
│   └── settings.py
├── embedding/
│   ├── __init__.py
│   └── embedder.py
├── evaluation/
│   ├── __init__.py
│   ├── evaluator.py
│   └── quality_checker.py
├── graph/
│   ├── __init__.py
│   ├── community_detector.py
│   ├── entity_extractor.py
│   ├── graph_analyzer.py
│   └── graph_builder.py
├── output/
│   └── ... hasil pipeline ...
├── pipeline/
│   ├── __init__.py
│   └── feedback_loop.py
├── preprocessing/
│   ├── __init__.py
│   ├── docling_loader.py
│   └── image_exporter.py
├── storage/
│   ├── __init__.py
│   └── r2_handler.py
├── summarizer/
│   ├── __init__.py
│   ├── hierarchical_reducer.py
│   ├── llm_summarizer.py
│   ├── prompt_builder.py
│   └── pruner.py
├── test_database/
│   └── qdrant_r2_test.py
├── vectordb/
│   ├── __init__.py
│   └── qdrant_handler.py
├── .env
├── .gitignore
├── docker-compose.yml
├── env.example
├── main.py
├── README.md
├── requirements.txt
├── sample.pdf
└── upload_to_qdrant.py
```

---

## Penjelasan folder

### `config/`
Folder konfigurasi global project.

Isi utama:
- `settings.py` → menyimpan selector backend, konfigurasi Qdrant, R2, MinIO, embedding model, spaCy model, dan flag pipeline lain.

Tahap diagram yang diwakili:
- configuration layer / runtime setup.

### `preprocessing/`
Folder tahap awal pemrosesan dokumen.

Isi utama:
- `docling_loader.py` → load PDF, ekstraksi teks, chunking, dan integrasi image pipeline.
- `image_exporter.py` → export image langsung dari dokumen atau fallback render halaman saat diperlukan.

Catatan implementasi:
- chunking saat ini berbasis **Docling item iteration** (`iterate_items`) dengan fallback ke split markdown per paragraf.
- implementasi ini **belum** memecah dokumen secara eksplisit menjadi pipeline bertingkat `sentence -> paragraph -> section`.

Tahap diagram yang diwakili:
- input document,
- preprocessing,
- adaptive chunking,
- image extraction / page rendering.

### `embedding/`
Folder pembentukan embedding vector.

Isi utama:
- `embedder.py` → encode chunk dan query menjadi vector embedding.

Catatan implementasi:
- model default saat ini adalah `nomic-ai/nomic-embed-text-v1.5` dan bisa diganti lewat `EMBEDDING_MODEL`.

Tahap diagram yang diwakili:
- embedding layer.

### `vectordb/`
Folder integrasi ke vector database.

Isi utama:
- `qdrant_handler.py` → create collection, upsert payload + vector, semantic search, dan helper retrieval format chunk.

Tahap diagram yang diwakili:
- vector DB storage,
- semantic retrieval.

### `storage/`
Folder object storage.

Isi utama:
- `factory.py` → memilih backend storage aktif dari environment.
- `minio_handler.py` → koneksi ke MinIO lokal, upload file image, dan generate public URL object.
- `r2_handler.py` → koneksi ke Cloudflare R2, upload file image, dan generate public URL object.

Tahap diagram yang diwakili:
- image/object storage layer.

### `graph/`
Folder graph pipeline untuk analisis hasil retrieval.

Isi utama:
- `entity_extractor.py` → hybrid entity extraction dan relation extraction.
- `graph_builder.py` → membangun graph dari chunk, entity, relation, dan similarity.
- `community_detector.py` → community detection dengan Leiden.
- `graph_analyzer.py` → centrality, ranking node, dan export hasil graph analysis.

Catatan implementasi:
- graph saat ini membentuk **chunk nodes** dan **entity nodes**.
- edge yang aktif saat ini adalah:
  - **chunk-chunk** via KNN cosine similarity,
  - **entity-entity** via relation extraction.
- belum ada edge eksplisit **chunk-entity**.

Tahap diagram yang diwakili:
- hybrid entity extraction,
- hierarchical graph construction,
- community detection,
- graph analysis.

### `summarizer/`
Folder penyusunan konteks dan summarization.

Isi utama:
- `pruner.py` → memilih chunk paling penting dari hasil graph ranking.
- `prompt_builder.py` → menyusun prompt untuk summarization.
- `llm_summarizer.py` → summarization tahap map per community.
- `hierarchical_reducer.py` → reduce hasil map menjadi final summary.

Tahap diagram yang diwakili:
- pruning / reranking,
- structure-aware prompt,
- LLM summarizer,
- hierarchical reduce.

### `evaluation/`
Folder evaluasi hasil summary.

Isi utama:
- `evaluator.py` → evaluasi with-reference atau without-reference.
- `quality_checker.py` → quality gate dan rekomendasi aksi.

Catatan implementasi:
- evaluasi saat ini mendukung:
  - **with reference**: ROUGE + BERTScore (jika package tersedia),
  - **without reference**: lexical overlap terhadap source chunks.
- evaluasi ini **belum** mengimplementasikan FactCC, SummaC, G-Eval, atau QA-coverage seperti versi diagram konseptual.

Tahap diagram yang diwakili:
- evaluation layer,
- quality check.

### `pipeline/`
Folder pengendali alur lanjutan.

Isi utama:
- `feedback_loop.py` → memutuskan apakah pipeline berhenti atau perlu retry.

Catatan implementasi:
- `feedback_loop.py` saat ini bertindak sebagai **decision controller**:
  - accept,
  - review,
  - retry retrieval,
  - retry prompt,
  - retry reduce.
- modul ini **belum** otomatis menjalankan ulang stage yang dipilih; ia hanya mengembalikan keputusan `next_stage`.

Tahap diagram yang diwakili:
- adaptive feedback loop.

### `test_database/`
Folder pengujian koneksi database lokal.

Isi utama:
- `qdrant_r2_test.py` → smoke test ingest/retrieval backend-neutral untuk payload Qdrant + image URL contract.

Tahap diagram yang diwakili:
- local integration testing.

### `output/`
Folder hasil pipeline.

Contoh file output:
- `graph_ranked_nodes.csv`
- `graph_ranked_nodes.json`
- `graph_summary.json`
- `pruned_summary_context.csv`
- `pruned_summary_context.json`
- `community_map_summaries.json`
- `community_map_summaries.txt`
- `final_summary.json`
- `final_summary.txt`
- `evaluation_result.json`
- `quality_gate_report.json`
- `feedback_loop_decision.json`
- `images/`

Folder ini mewakili tahap **artifact/output layer** dari keseluruhan diagram.

---

## File root project

### `upload_to_qdrant.py`
Script khusus untuk **upload/indexing** dokumen ke Qdrant.

Fungsi:
- membaca PDF lokal,
- chunking dokumen via Docling,
- embedding chunk,
- upload asset gambar ke R2,
- menyimpan vector dan payload ke Qdrant.

Script ini dipakai hanya saat ada dokumen baru yang ingin dimasukkan ke database vector.

### `main.py`
Script utama untuk **retrieval + summarization**.

Fungsi:
- embed query,
- ambil chunk relevan dari Qdrant,
- jalankan graph pipeline,
- bangun summary,
- evaluasi hasil,
- quality gate,
- feedback loop.

Script ini dipakai setelah data dokumen sudah tersedia di Qdrant.

### `docker-compose.yml`
Bootstrap local mode untuk Qdrant + MinIO. Volume lokal tetap dipakai, dan `minio-init` otomatis membuat bucket `summarizer-images` sekaligus membuka akses download lokal.

### `requirements.txt`
Daftar dependency Python untuk menjalankan project.

### `.env`
Konfigurasi environment lokal.

### `env.example`
Template environment variable yang bisa dipakai sebagai acuan setup awal.

### `sample.pdf`
Contoh file dokumen lokal untuk pengujian upload/indexing.

### `README.md`
Dokumentasi project.

---

## Mapping diagram ke implementasi

Catatan:
- mapping di bawah ini adalah mapping **arsitektur**.
- beberapa box pada diagram masih bersifat **konseptual/high-level**, sedangkan code saat ini adalah implementasi minimum yang sudah jalan.
- khusus setelah **Vector DB Storage + Semantic Retrieval**, flow besar tetap mengikuti pipeline lama `main.py` milik `summarizer_project`.

- **Input Document**
  - `sample.pdf`
  - `preprocessing/docling_loader.py`

- **Preprocessing**
  - `preprocessing/docling_loader.py`
  - `preprocessing/image_exporter.py`

- **Adaptive Hierarchical Chunking**
  - `preprocessing/docling_loader.py`
  - status: **partial** — saat ini berbasis Docling item/paragraf, belum full hierarchical `sentence -> paragraph -> section`

- **Embedding**
  - `embedding/embedder.py`
  - default model: `nomic-ai/nomic-embed-text-v1.5`

- **Vector DB Storage**
  - `upload_to_qdrant.py`
  - `vectordb/qdrant_handler.py`

- **Semantic Retrieval**
  - `main.py`
  - `vectordb/qdrant_handler.py`

- **Hybrid Entity Extraction**
  - `graph/entity_extractor.py`

- **Hierarchical Graph Construction**
  - `graph/graph_builder.py`
  - status: **partial** — chunk nodes + entity nodes + KNN similarity + entity relations, belum ada edge eksplisit chunk-entity

- **Community Detection**
  - `graph/community_detector.py`

- **Graph Analysis**
  - `graph/graph_analyzer.py`

- **Pruning / Re-ranking**
  - `summarizer/pruner.py`

- **Structure-Aware Prompt**
  - `summarizer/prompt_builder.py`

- **LLM Summarizer**
  - `summarizer/llm_summarizer.py`

- **Hierarchical Reduce**
  - `summarizer/hierarchical_reducer.py`
  - status: **partial** — reduce LLM bertingkat map->final, belum RAPTOR-style re-embed per level

- **Evaluation Layer**
  - `evaluation/evaluator.py`
  - status: **partial** — ROUGE/BERTScore/lexical overlap, belum FactCC/SummaC/G-Eval/QA-coverage

- **Quality Check**
  - `evaluation/quality_checker.py`

- **Adaptive Feedback Loop**
  - `pipeline/feedback_loop.py`
  - status: **partial** — baru decision stage, belum auto re-run loop

---

## Konfigurasi database dan storage

Project ini memakai konfigurasi environment-driven. Ingest path sekarang satu flow yang bisa diarahkan ke **cloud mode** (`R2 + Qdrant Cloud`) atau **local mode** (`MinIO + local Qdrant`) dari `.env`.

File yang perlu diperhatikan:
- `.env`
- `config/settings.py`
- `vectordb/qdrant_handler.py`

Variabel yang biasanya perlu diganti:
- `STORAGE_BACKEND`
- `QDRANT_BACKEND`
- `QDRANT_COLLECTION`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `QDRANT_HOST`
- `QDRANT_PORT`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_PUBLIC_BASE_URL`
- `MINIO_ENDPOINT_URL`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`
- `MINIO_PUBLIC_BASE_URL`
- `GROQ_API_KEY`
- `PDF_PATH`
- `QUERY_TEXT`
- `RETRIEVAL_LIMIT`

Contoh **cloud mode** `.env`:

```env
STORAGE_BACKEND=r2
QDRANT_BACKEND=cloud
QDRANT_COLLECTION=summarizer_docs
QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=replace_me

R2_ACCOUNT_ID=replace_me
R2_ACCESS_KEY_ID=replace_me
R2_SECRET_ACCESS_KEY=replace_me
R2_BUCKET=replace_me
R2_PUBLIC_BASE_URL=https://pub-example.r2.dev

GROQ_API_KEY=your_api_key_here

PDF_PATH=sample.pdf
QUERY_TEXT=What is the main idea of the paper?
RETRIEVAL_LIMIT=10
```

Contoh **local mode** `.env`:

```env
STORAGE_BACKEND=minio
QDRANT_BACKEND=local
QDRANT_COLLECTION=summarizer_docs_local
QDRANT_HOST=localhost
QDRANT_PORT=6333

MINIO_ENDPOINT_URL=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=summarizer-images
MINIO_PUBLIC_BASE_URL=http://localhost:9000/summarizer-images

GROQ_API_KEY=your_api_key_here

PDF_PATH=sample.pdf
QUERY_TEXT=What is the main idea of the paper?
RETRIEVAL_LIMIT=10
```

Penerima project bisa mengganti konfigurasi tersebut sesuai server, bucket, collection, volume lokal, dan credential miliknya sendiri.

---

## Requirements yang disarankan

```txt
bert-score==0.3.13
bertopic==0.16.4
boto3==1.39.3
docling==2.31.0
groq==0.9.0
leidenalg==0.10.2
matplotlib==3.9.0
networkx==3.3
numpy==1.26.4
pandas==2.2.2
Pillow==10.4.0
python-dotenv==1.0.1
python-igraph==0.11.6
qdrant-client==1.9.1
rouge-score==0.1.2
scikit-learn==1.5.1
sentence-transformers==3.0.1
spacy==3.7.5
tqdm==4.66.4
```

Setelah install dependency, jalankan juga:

```bash
python -m spacy download en_core_web_sm
```

---

## Cara menjalankan

### 1. Buat environment

```bash
conda create -n summarizer_env python=3.10 -y
conda activate summarizer_env
```

### 2. Install dependency

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 3. Siapkan backend

```bash
cp env.example .env
```

Pastikan selector backend, credential storage, koneksi Qdrant, API key, dan path file sudah sesuai environment yang dipakai.

Untuk **local mode**, jalankan:

```bash
docker compose up -d
```

Lalu set `.env` ke `STORAGE_BACKEND=minio` dan `QDRANT_BACKEND=local`.

### 4. Upload dokumen ke Qdrant

```bash
python upload_to_qdrant.py
```

Tahap ini digunakan untuk memasukkan dokumen baru ke collection Qdrant.

### 5. Jalankan retrieval + summarization

```bash
python main.py
```

Tahap ini digunakan untuk mengambil chunk relevan dari Qdrant dan menghasilkan summary.

### 6. Cek hasil

Semua hasil pipeline akan muncul di folder `output/`.

---

## Catatan penting

- `upload_to_qdrant.py` hanya fokus pada indexing/upload dokumen ke Qdrant.
- `main.py` hanya fokus pada retrieval dan summarization dari data yang sudah ada di Qdrant.
- Active ingest path memakai satu flow dengan backend yang dipilih dari environment.
- Setelah retrieval dari Qdrant, pipeline besar tetap memakai modul lama `summarizer_project` (`graph/*`, `summarizer/*`, `evaluation/*`, `pipeline/feedback_loop.py`).
- Jika `PDF_PATH` tersedia saat retrieval mode, sistem dapat melakukan on-demand page render untuk halaman yang terambil.
- Jika `PDF_PATH` tidak tersedia, retrieval tetap berjalan karena teks utama diambil dari payload Qdrant.
- Final summary saat ini **dibentuk lebih dulu**, lalu **dievaluasi**; quality gate menentukan apakah hasil tersebut diterima, direview, atau perlu retry.
- Warning `pin_memory` dari PyTorch dapat diabaikan jika tidak menggunakan GPU.
- API key aktif sebaiknya tidak dibagikan ke repository publik. Ganti dengan placeholder sebelum project dikirim ke orang lain.

---

## Ringkasan teknis

Project ini sudah mencakup pipeline lokal berikut:
- preprocessing dokumen PDF,
- image export / on-demand page rendering,
- embedding,
- vector DB storage,
- semantic retrieval,
- entity extraction,
- graph construction,
- community detection,
- graph analysis,
- pruning,
- prompt building,
- LLM summarization,
- hierarchical reduce,
- evaluation,
- quality gate,
- feedback loop.

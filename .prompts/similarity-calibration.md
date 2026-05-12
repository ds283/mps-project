# Task: Standalone similarity distribution profiling script

## Background

The MPS-Project platform includes a similarity pipeline (`similarity_analysis.py`) that compares student submission
reports stored as `SubmissionRecord` instances. The pipeline:

1. Extracts and LLM-classifies document sections into chunk types (`abstract`, `introduction`, `literature_review`,
   `methodology`, `results`, `discussion`, `conclusions`)
2. Computes MinHash signatures for each chunk and stores them in MongoDB
3. Uses MinHash LSH (threshold 0.15, 128 permutations) as a cheap pre-filter
4. Re-ranks LSH candidates with cosine similarity via `sentence-transformers` (`all-MiniLM-L6-v2`)
5. Creates a `SimilarityConcern` when cosine exceeds a per-chunk-type threshold

The MongoDB collection storing scraped text and chunk data is accessed via `shared/scraped_text_store.py`. The relevant
subdocument structure is believed to be under `similarity_chunks`, but **you should verify the exact field paths by
fetching and inspecting a real document before writing any analysis code**.

## Goal

Produce a standalone Python script `similarity_distribution.py` that can be run outside the Flask application context,
connecting directly to the MongoDB instance (which exposes a port to the host network). The script profiles the full
pairwise similarity distribution across all available `SubmissionRecord` documents — approximately 260 reports, giving
260×259/2 = 33,670 pairs.

This is a calibration exercise to understand whether the production LSH threshold and per-chunk cosine thresholds are
well set. The LSH gate means the production pipeline never scores many pairs with cosine similarity; we need the full
distribution to know what it is missing.

## What the script should do

### 1. Schema inspection (do this first)

Fetch a single document from the MongoDB scraped text collection and print its full structure. Confirm field paths for:

- The chunk section texts and their presence sentinels
- The MinHash hashvalue arrays
- The `submission_record_id` field type (integer vs string)

Read `shared/scraped_text_store.py` to cross-check against the application code before proceeding.

### 2. Data loading

Pull all documents that have chunked similarity data, projecting only the fields needed:

- `submission_record_id`
- Section texts for each chunk type (and their presence flags)
- MinHash hashvalue arrays for each chunk type

Index everything by `submission_record_id`.

### 3. Pairwise MinHash Jaccard

For each chunk type, compute the full pairwise Jaccard similarity across all records that have that chunk present, using
the stored MinHash hashvalues (128 permutations, matching `MINHASH_NUM_PERM` in `similarity_analysis.py`). Use
`datasketch.MinHash`.

The naive O(N² · num_perm) loop is acceptable for N≈260. If a vectorised approach (stacking hashvalues into an (N, 128)
array and computing agreement fraction with NumPy) is cleaner, use that instead.

### 4. Pairwise cosine similarity — three models

For each chunk type, encode all present section texts with each of the following models and compute the full pairwise
cosine similarity matrix:

| Key        | Model string        |
|------------|---------------------|
| `minilm`   | `all-MiniLM-L6-v2`  |
| `mpnet`    | `all-mpnet-base-v2` |
| `specter2` | `allenai-specter2`  |

Use `model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)` so that `E @ E.T` gives cosine similarities
directly.

Note for SPECTER2: check the HuggingFace model card for the correct load pattern — it uses an adapter architecture and
may require `trust_remote_code=True`. For symmetric pairwise comparison (neither text is a query), the `proximity`
adapter is appropriate.

Extract the upper triangle (`np.triu_indices(n, k=1)`) to get the 33,670 unique pair values.

### 5. Output

Write results to an Excel workbook (one sheet per chunk type) with one row per unique pair:

| Column            | Content                                        |
|-------------------|------------------------------------------------|
| `record_a_id`     | lower of the two `submission_record_id` values |
| `record_b_id`     | higher                                         |
| `jaccard`         | MinHash Jaccard estimate                       |
| `cosine_minilm`   | cosine similarity under MiniLM                 |
| `cosine_mpnet`    | cosine similarity under mpnet                  |
| `cosine_specter2` | cosine similarity under SPECTER2               |

Also write a summary sheet with per-chunk-type statistics (median, p75, p90, p95, p99, and counts above the production
cosine thresholds from `CHUNK_SIMILARITY_THRESHOLD` in `similarity_analysis.py`) for each model and for Jaccard.

Additionally print to stdout, for each chunk type: the fraction of pairs above the LSH threshold (0.15 Jaccard), and the
fraction above each production cosine threshold under each model — to give a quick sense of how many pairs the LSH gate
is suppressing that would pass the cosine gate.

### 6. Diagnostic: LSH false-negative rate

For each chunk type and each cosine model, count the pairs in the top-left quadrant: Jaccard < 0.15 but cosine ≥
production threshold. Print these counts prominently — this is the key calibration diagnostic. A nonzero count here
means the LSH gate is suppressing pairs that would have triggered a `SimilarityConcern`.

## Configuration

Accept the following as command-line arguments with sensible defaults:

```
--mongo     MongoDB URI          (default: mongodb://localhost:27017)
--db        database name        (default: to be confirmed from scraped_text_store.py)
--out       output Excel path    (default: similarity_distribution.xlsx)
```

## Implementation notes

- Load models lazily, one at a time, to avoid holding all three in memory simultaneously if memory is tight
- Show a progress indicator during encoding (pass `show_progress_bar=True` to encode)
- Records missing a given chunk type should be excluded from that chunk type's analysis but included in others
- The script runs outside Flask context — do not import any application modules
- Use `openpyxl` for Excel output
- Prefer clarity over cleverness; this is a one-off analysis script

## Verification step

Before writing the full script, confirm with me:

1. The exact MongoDB collection name and field paths discovered from the live instance
2. Whether SPECTER2 loads correctly with the standard sentence-transformers interface
3. The database name from `scraped_text_store.py`
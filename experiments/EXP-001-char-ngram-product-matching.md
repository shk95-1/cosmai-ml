# EXP-001 — Character n-gram cross-source product matching

## Identity and status

- Experiment ID: `EXP-001`
- Type: `OTHER` (model construction against the integrated dataset)
- Status: `COMPLETED`
- Related: `MODELS-CATALOGUE.md` C2
- Owner: hyeonjunni
- Created at: 2026-08-22T03:00+09:00
- Last executed at: 2026-08-22T11:56+09:00

**Integrity note, recorded first because it changes how the rest reads.** This log was
written *after* the experiment ran. The hypothesis and falsification condition below were
not declared in advance, so this record cannot claim the protection that pre-declaration
gives — nothing stopped the criteria from being shaped to fit what was already seen.
`EXP-002` is declared before execution; this one is a faithful record of an unplanned
build, not a test.

## Question

Can cross-source product identity be recovered from product names alone, cheaply enough
to skip an embedding model?

## Hypothesis

`[가설]` Normalised Korean product names carry enough signal that character n-gram TF-IDF
with brand blocking produces same-product candidate pairs at a rate worth a person's
review time.

## Falsification condition

Fewer than 50 cross-source candidate pairs above 0.45, or manual inspection of the top
band showing mostly unrelated products.

## Exit condition

One run over the whole `product` table. No tuning loop beyond a single inspection pass.

## Scope

### Included

- `product` table of `cosmai_integrated`, 4,804 rows, 4 sources
- Name, brand, volume fields only

### Excluded

- Same-source duplicates (a different problem)
- Any use of price, rank or review signal
- Precision measurement — see Result

## Inputs and provenance

| Input | Source | Captured at | Basis | Version | Storage |
| --- | --- | --- | --- | --- | --- |
| `product` (4,804 rows) | shk integration DB via PostgREST | 2026-08-22T02:42Z freeze | internal team data | `cosmai_integrated` on spark-2ea6 | Postgres, DGX |

## Environment

- Code revision: `cosmai-ml/match_products.py`
- Runtime: Python 3.12, scikit-learn 1.9.0, numpy 2.5.2, pandas 3.0.5
- Host: spark-2ea6 (GB10, 20 cores), CPU only
- Resource caps: `OMP/OPENBLAS/MKL_NUM_THREADS=4`, `nice -n 15` — a Minecraft server shares
  this host and must not be disturbed
- Reproduction:
  `nice -n 15 .venv/bin/python match_products.py --dsn postgresql://trend_radar:***@localhost:5432/cosmai_integrated --out matches.csv`

## Procedure

1. Normalise names: strip bracketed promo segments, promo words, volume tokens, punctuation.
2. Block on normalised brand — 4,804 products pairwise is 11.5M comparisons; within-brand
   is a few thousand.
3. Score `char_wb` 2–4-gram TF-IDF cosine, plus 0.15 × volume agreement.
4. Keep cross-source pairs scoring ≥ 0.45.
5. Inspect three score bands by eye.
6. **Revision after step 5** — see Observations. A product-form feature was added and the
   run repeated. The original boundary was not changed; only the scorer was.

## Evidence collection

- Metrics: candidate pair count, score distribution, one-to-many conflict count
- Artifacts: `~/cosmai-data/matches.csv`, `~/cosmai-data/to-label.csv` on spark-2ea6
- Integrity: row counts printed by the script at run time

## Observations

```text
[측정] Run 1 — name + volume only
  products 4,804 (oliveyoung 2,873 / daisomall 1,628 / glowpick 273 / hwahae 30)
  candidate pairs 592
  score >= 0.90: 71   >= 0.70: 210   >= 0.45: 592
  one-to-many conflicts 113
```

```text
[측정] Run 1 inspection, three bands, 4 pairs each
  0.90+ : exact-name matches across glowpick/hwahae. correct on inspection.
  0.65-0.75 : mixed. Two wrong pairs shared a product line but differed in form —
      "다이브인 저분자 히알루론산 세럼" ↔ "... 토너"
      "레드 블레미쉬 수딩 업 선" ↔ "레드 블레미쉬 클리어 히알 시카 수딩 세럼"
  0.45-0.55 : mixed, includes a correct 랑방 퍼퓸 pair.
```

```text
[측정] Run 2 — product form added, disagreement penalised 0.30
  products with a recognised form 2,831 of 4,804
  candidate pairs 675
  score >= 0.90: 190   >= 0.70: 333   >= 0.45: 675
  one-to-many conflicts 155
  The two named failures moved: 세럼↔토너 0.75 → 0.46, 세럼↔세럼 1.15 → 1.45.
  Every form-disagreeing pair now scores ≤ 0.52.
```

```text
[측정] Host during run
  load average 0.17 → 0.33 of 20 cores
  Minecraft java process 25.5% CPU / 10.8 GB RSS, unchanged before and after
  GPU 0% throughout; free memory 101 GB unchanged
```

## Interpretation

```text
[추론] The dominant error mode was product form within a shared line, not brand or
name confusion. Character n-grams cannot separate 세럼 from 토너 because the strings
differ by one short token inside otherwise identical text, so the failure was structural
rather than a threshold problem.
```

```text
[추론] Extracting form as a categorical feature and penalising stated disagreement
addressed that specific failure: the two named wrong pairs fell below the band where
correct pairs sit, and the count above 0.90 rose from 71 to 190 because form agreement
lifts true pairs as well as demoting false ones. This is consistent with the feature
carrying identity signal rather than merely acting as a filter.
```

```text
[추론] The rise in one-to-many conflicts (113 → 155) is expected rather than a
regression: more pairs cleared the threshold overall. It is not evidence either way
about correctness and needs the labelled set to interpret.
```

## Result

- Outcome: `SUPPORTED`
- Falsification condition met: `NO` (675 pairs, top band correct on inspection)
- Exit condition met: `YES`
- Known limitations:
  - **Precision is not measured.** There are no ground-truth pairs. Every count is what
    the matcher proposed, not evidence it is right. The inspection covered 12 pairs.
  - Recall is not measured either, and cannot be without knowing how many true
    cross-source pairs exist.
  - `hwahae` contributes 30 products, so any conclusion about it rests on almost nothing.
  - The score is not bounded to 1: it is cosine plus two weighted agreements, so 1.45 is
    reachable. Do not read it as a probability.
  - The 0.15 and 0.30 weights were chosen by hand and never tuned against labels.

## Next

`to-label.csv` holds 300 pairs stratified across score bands, with an empty
`is_same_product` column. Precision, recall and a defensible threshold all wait on that
file coming back labelled. Sampling only the top band was deliberately avoided: it would
measure the matcher where it is most confident and say nothing about where to cut.

# cosmai-ml

Label construction and trend models for Cosmai beauty R&D signals.

This repo owns everything downstream of a collected record: labels, features, training,
evaluation. It collects nothing. Collection lives in
[`cosmai`](https://github.com/slopindustries/cosmai) (platform core),
[`trend-radar`](https://github.com/slopindustries/trend-radar) and
[`ingredient-radar`](https://github.com/slopindustries/ingredient-radar) (Korean retail
sites), [`yt-scrapper`](https://github.com/slopindustries/yt-scrapper) and
[`youtube-data-collector`](https://github.com/slopindustries/youtube-data-collector)
(YouTube), and [`Research_Paper`](https://github.com/slopindustries/Research_Paper)
(academic evidence).

## Data flow

```text
collector repos  ->  local working copy  ->  DGX (spark-2ea6)  ->  training
                     project-data/          ./sync.sh            this repo
                     ~/cosmai-data/
```

`./sync.sh <dir>` streams a directory to the DGX over the tailnet. It needs `DGX_USER`.
The DGX is a GB10, 119 GB unified memory, Ubuntu 24.04 **aarch64** — pick wheels
accordingly. A venv for this work lives at `~/cosmai-data/.venv`; the machine is shared,
so don't install into system Python.

## The prediction task

Given signals observed up to month `t`, predict the direction and size of beauty demand
at `t + horizon`. `horizon` defaults to 3 months.

What "demand" means is not settled — the Cosmai charter leaves final product semantics
open. This repo therefore builds the label from four independent axes and keeps them
separable, so the composite can be redefined without re-deriving the parts.

## Label axes

| Axis | Source | Entity grain | Time grain | Usable history |
|---|---|---|---|---|
| 판매량 | 관세청 면세점 품목별 매출 | **category** (`화장품`, `향수`) | monthly | **2019-01 → 2025-06, 78 months** |
| 학계동향 | `Research_Paper` (OpenAlex/S2/Europe PMC) | paper | **calendar year** | backfillable, not yet collected |
| 키워드 | `trend-radar`, `yt-scrapper` | product, review, video | hourly / per event | **none yet — `trend-radar` collecting since 2026-08-20** |
| 신제품 출시 | `trend-radar` `new_product` (daisomall, glowpick) | product | hourly | **none yet — collecting since 2026-08-20** |

Only `labels_sales.py` is implemented, because it is the only axis with past data.

### The history problem

The brief is to build labels from past data. Three axes cannot, today:

- `trend-radar` is **forward-only**. There is no backfill or historical import; it starts
  producing when someone starts the cron, and its first commits are 2026-08-18.
- `yt-scrapper` is a **rolling 30-day cache** that prunes by age and a 50 GiB backstop.
  Its own docs call it "not a historical archive". A training set assembled from it
  silently shrinks, and a run from a month ago cannot be reproduced.
- `new_product` **is** implemented in `trend-radar` — `daisomall` and `glowpick` both
  write `NewProductRecord`, and one run produced 198 rows. It is `ingredient-radar`, the
  stale copy, where the table has no writer. The axis has no past data like the others,
  but it does have a working collector.

So: sales has real history, academic evidence can be backfilled because publication dates
are historical by nature, and keyword and launch start from zero. Either find a
backfillable source for those two, or accept that they become usable only after months of
accumulation. Decide this before designing the composite label — it determines whether
there is a model to train this quarter or next year.

### The granularity problem

Nothing in any repo produces ingredient-level entities. Sales resolves to a product
category; the collectors resolve to product, document, or paper. There is no honest join
between them at ingredient level.

Three ways out, none free:

1. **Label at category level.** Sales stays the target; other axes aggregate up. Loses the
   resolution that makes the product useful.
2. **Label at ingredient level without sales.** Target becomes a composite of the
   ingredient-resolvable axes; sales is demoted to a category-level covariate that
   validates the composite rather than defining it.
3. **Allocate sales to ingredients** by product-composition share. Needs a product
   catalogue with parsed ingredient lists *and* per-product sales. `trend-radar` stores
   `ingredients` as one unparsed text blob for one of four sources, and the blocker below
   erases it. Treat as unavailable, not as future work.

Option 2 is the only one that reaches ingredient resolution with data that exists.

### Do not build the label from mention counts

`youtube-data-collector`'s own design notes (§8) say it: features from mention counts plus
labels from mention counts means the model predicts its own input. `opportunity_score` is
exactly that composite. It is a ranking heuristic, not a label. Any keyword-derived target
needs an external anchor — sales, or retail ranking movement.

### Confounders already known

- **`product.ingredients` NULLs were not missing-at-random.** `trend-radar`'s ranking
  upsert overwrote with nulls what the product-detail pass wrote, so the column recorded
  which dataset ran last. Fixed on `fix/product-upsert-coalesce`; any row written before
  that branch merges is still suspect.
- **A broken scraper and a quiet hour are the same signal.** Every `sources/*.py`
  `parse()` returns an empty result on shape mismatch. Training across a silent multi-day
  breakage reads a code outage as a market move.
- **Collection is not a sample.** `trend-radar` takes reviews for the top 10 ranked
  products only, Olive Young sorts by rating extremes, and Hwahae is robots-limited to
  ~10 of each 50-100-row board. `yt-scrapper`'s corpus is one operator's
  ~100-video watchlist.
- **2020–2022 duty-free volume collapsed for travel reasons, not beauty reasons.** Train
  on raw year-over-year and the model learns the pandemic. `labels_sales.py` emits
  `per_visitor` for this; use it or justify not using it.
- **Duty-free sales are dominated by non-resident buyers.** This is not domestic consumer
  demand and should not be described as such.
- **The customs category file carries no unit row.** The unit is inferred as 억원 by
  cross-checking monthly totals against the USD file. Growth rates are unit-free, so the
  label is unaffected; do not quote absolute figures from it.

## What runs today

```sh
uv run --with pandas --with openpyxl labels_sales.py --self-check
uv run --with pandas --with openpyxl labels_sales.py -o sales_labels.csv
```

On the DGX, the data is at `~/cosmai-data/datasets`:

```sh
.venv/bin/python labels_sales.py datasets --self-check
```

Output covers 2019-01 to 2025-06 (78 months): monthly cosmetics + perfume duty-free sales,
per-visitor normalization, year-over-year growth, and the forward-shifted target.

No model yet. A baseline on 78 monthly rows and one axis would be a curve fit, not a
finding. What is worth building, with which `X` and which `Y`, is in [MODELS.md](MODELS.md).

## Next

1. Decide the granularity option and the history question above. Both are prerequisites,
   not follow-ups.
2. Backfill the academic axis — it is the only other axis with reachable history. Needs
   day-level dates (`Research_Paper` requests only `publication_year`) and a paper→entity
   join, which no repo implements.
3. Then a baseline on at least two axes, evaluated on a last-N-months holdout — never a
   random split, the series is temporal.

Collector defects that would corrupt training input are in
`../reviews/REVIEW-collectors.md`.

## Environment

Python >= 3.13 locally, managed by `uv`. The DGX venv is on 3.12. The repo defines no
importable package; modules stay flat until a contract says otherwise.

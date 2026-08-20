# What can actually be modelled

Written against the data that exists on 2026-08-20, not against the data the brief
assumes. Each model below names its unit of observation, its `Y`, its `X`, and the date
it becomes trainable.

## The rule that shapes all of this

`Y` must not come from the same counting process as `X`. Counting mentions to build a
feature and counting mentions to build a label means the model predicts its own input —
the `youtube-data-collector` design notes say this in §8 and it is the single easiest way
to produce an impressive, meaningless score here.

Two external anchors exist, and only two:

- **판매량** — 관세청 duty-free, category grain, monthly, 2019-01 onward.
- **랭킹** — `trend-radar.rank_snapshot`, product grain, hourly, starting 2026-08-20.

Everything else — mentions, papers, reviews, prices, launches — is `X`. If a proposed
label is not derived from sales or ranking, check it against this rule before building it.

## Model A — category demand, 3 months out

**Trainable now.** Also the weakest.

| | |
|---|---|
| Unit | one calendar month |
| Y | `target_yoy_fwd` — year-over-year change in 화장품+향수 duty-free sales, 3 months ahead |
| X | month-of-year, `visitors_k`, lagged `yoy` (t-1, t-3, t-12), nationality mix (연도별), per-visitor sales level |
| Source | `labels_sales.py`, already implemented |

The honest sample count: 78 months, minus 12 for the year-over-year window, minus 3 for
the forward shift, leaves **63 usable rows** — and a last-12-months holdout leaves 51 to
train on. That is a statistics problem, not a machine-learning one.

Use ridge or a seasonal-naive baseline. A gradient-boosted tree on 51 rows will fit the
pandemic and report a good score. Whatever you build must beat seasonal-naive on the
holdout or it is not evidence of anything.

## Model B — product ranking movement

**Trainable in 2–4 weeks.** The first model here that is genuinely ML.

| | |
|---|---|
| Unit | (product, day) or (product, week) |
| Y | rank change over the next k days, or "enters top N within k days" — computed directly from `rank_snapshot` |
| X | current rank; rank momentum over 1/3/7 days; price level and discount change (`price_point`); days since first seen (`new_product.first_seen_at`); review count and rating change (`review_stats`); board and category; brand-level aggregates |
| Source | `trend-radar`, collecting hourly since 2026-08-20 |

Not self-referential: `Y` is ranking, and most of `X` is price, launches, and reviews —
different measurement processes. But rank momentum in `X` is strongly autocorrelated with
`Y`, so a **persistence baseline** ("tomorrow's rank equals today's") is mandatory as the
comparison. Beating it is the entire claim.

Needs roughly 7 days of momentum window + the forecast horizon + a holdout period, so
2–4 weeks of accumulated hourly data.

Caveat that must be carried into any result: hwahae is robots-limited to about 10 rows of
each 50–100-row board, so the observed rank distribution has an artificially short tail.

## Model C — new-product success

**Trainable in 2–3 months.** The most directly useful for R&D.

| | |
|---|---|
| Unit | one product, at the moment it first appears in `new_product` |
| Y | reaches top N ranking within D days of first sighting — or best rank achieved |
| X | brand's historical hit rate; price tier; category; launch month; early review velocity; ingredients (Olive Young only, once authorised) |
| Source | `new_product` (198 rows after one run), joined to `rank_snapshot` |

The wait is structural rather than technical: products must be seen at launch *and* then
observed long enough for the outcome to resolve. Nothing shortens it except starting the
clock, which is now running.

## Model D — ingredient trend

**Blocked, and not by a bug.** No repo produces ingredient-level entities.

The intended shape is: `Y` = future adoption of an ingredient (share of new products
containing it, from `new_product` × parsed ingredients), `X` = publication counts,
patents, search volume, SNS mentions. That is the model the project is named after.

What is missing:

1. **INCI tokenization.** `product.ingredients` is one unparsed text blob, populated for
   one of four sources, with the site's own `[세럼] … [마스크]` separators baked in.
2. **product → ingredient mapping.** Does not exist.
3. **paper → ingredient mapping.** `Research_Paper` is explicit that mapping papers to
   trend entities is out of scope.

This is a project, not a task. It is also the thing that turns every other model here from
category-level to R&D-actionable, so it deserves an owner rather than a backlog line.

## Model E — academic signal as a leading indicator

**Blocked on granularity, and possibly on physics.**

`Y` would be Model A's or Model B's label; `X` would be publication counts per year from
`Research_Paper`. Two problems:

- The pipeline requests only `publication_year`, so `X` is annual while `Y` is monthly.
  OpenAlex exposes `publication_date`; adding it is a small change to
  `papers/sources/openalex.py`.
- Lab-to-shelf lead time in cosmetics is typically 2–5 years. With 78 months of sales
  history, estimating a lag that long leaves almost no independent observations. This may
  simply not be answerable with this window, and finding that out is cheaper than assuming
  either way.

Worth running the backfill regardless — it is the only axis where history can be recovered
rather than waited for.

## Ordering

1. **Now** — Model A, as a baseline and a sanity check on the label plumbing. Expect it to
   be unimpressive; the value is the pipeline, not the score.
2. **Weeks 2–4** — Model B, once `rank_snapshot` has depth. This is where the first real
   result comes from.
3. **Month 2–3** — Model C.
4. **In parallel, whenever someone owns it** — the ingredient entity layer, which unlocks
   Model D and upgrades B and C from product-level to ingredient-level.

## Contamination to check before trusting any result

- **A broken scraper and a quiet market are the same signal.** Every `sources/*.py`
  `parse()` returns an empty result on shape mismatch. Before training on any window,
  check `run_source` and `fetch_log` for gaps and exclude them explicitly — otherwise a
  code outage enters the training set as a demand collapse.
- **Collection is not a sample.** Reviews are taken for top-ranked products only; Olive
  Young sorts by rating extremes. Anything trained on reviews describes popular products,
  not the market.
- **2020–2022 duty-free volume collapsed for travel reasons.** Use `per_visitor`, or say
  why not.
- **Duty-free buyers are mostly non-resident.** This is not domestic consumer demand.

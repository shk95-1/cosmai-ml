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

## Deadline reality (2026-08-26)

Only Model A can produce a number by then. Model B's pipeline is written and runs
against the live database today, but the data it needs does not exist yet and cannot be
made to exist faster — `trend-radar` has no backfill. `model_b.py` reports this itself
rather than being described here and forgotten:

```
panel: 1 day(s) of rank history, 529 products, 529 product-days
INSUFFICIENT DATA. This design needs 22 days ... Missing 21 more day(s).
```

Earliest date each becomes trainable, counting from when collection started:

| Model | Trainable | vs deadline |
|---|---|---|
| A | now | ✓ |
| B (daily) | 2026-09-10 | 15 days late |
| C | 2026-10 or later | late |
| D | needs the ingredient layer built first | — |
| E | tested — no signal at category level | ✓ (answered) |

There is an hourly variant of Model B — momentum and horizon in hours rather than days —
that would be fittable around 2026-08-24. It predicts hour-to-hour rank noise, which is
not the question anyone asked. It is available if a number is needed more than an answer
is; say so explicitly in whatever it goes into.

## Model A — category demand, 3 months out

**Trainable now, and trained.** Also the weakest.

| | |
|---|---|
| Unit | one calendar month |
| Y | `target_yoy_fwd` — year-over-year change in 화장품+향수 duty-free sales, 3 months ahead |
| X | month-of-year (sin/cos), `yoy` and its 1- and 3-month lags, visitor-count year-over-year, per-visitor sales level |
| Source | `labels_sales.py`, already implemented |

The honest sample count: 78 months, minus the year-over-year window, the forward shift
and the feature lags, leaves **60 usable rows** — and a last-12-months holdout leaves 48
to fit on. That is a statistics problem, not a machine-learning one.

`model_a.py` fits closed-form ridge (numpy; scikit-learn is not worth a dependency for
one linear solve) and scores it against two baselines. Measured on the
2024-04 → 2025-03 holdout:

| model | MAE | RMSE | direction |
|---|---|---|---|
| ridge | 0.1398 | 0.1763 | 0.83 |
| persistence | 0.2205 | 0.2667 | 0.67 |
| zero | 0.2063 | 0.2474 | n/a |

Ridge beats both. **Do not report this as a result.** 48 training rows, and the 12 test
months are one contiguous, autocorrelated year, so the effective sample is far smaller
than twelve independent observations. It is a hypothesis that survived one honest test,
which is worth exactly that much and no more.

## Model B — product ranking movement

**Written and running; refuses to fit until 2026-09-10.** The first model here that is
genuinely ML. `model_b.py` reads the live Postgres, builds the panel, and either fits or
prints exactly how many days are missing.

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

Needs 7 days of momentum window + 7 for the label to resolve + 7 of temporal holdout +
1 to stand on = **22 days**. Collection started 2026-08-20, so 2026-09-10.

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

**Tested. It does not add signal at this granularity.**

The backfill ran twice, against two independently-constructed free measures of the same
axis: monthly cosmetics publication counts, 2017-01 → 2026-08. Joined to Model A as
`papers_yoy`:

| | ridge MAE | vs baseline |
|---|---|---|
| sales only | 0.1398 | — |
| + Europe PMC counts | 0.1381 | −1.2%, noise |
| + PubMed counts | 0.1489 | **+6.5%, worse** |

One neutral and one actively harmful. That is a much stronger answer than either run alone
would have been: a real signal would have shown up in both, since both are measuring
cosmetics publication volume over the same months. `model_a.py` names the Europe PMC move
as noise itself rather than leaving the sign of the difference to be read as a finding.

That is a real answer, not a failure: **global cosmetics publication volume does not
predict Korean duty-free category sales three months out.** It was never especially likely
to. Two reasons the test was worth running anyway — it wires the second axis end to end,
and it rules out the cheapest version of the hypothesis before anyone builds the expensive
one.

What was *not* tested, and might still hold:

- **Per-ingredient**, rather than whole-category. "Retinol papers rise, then retinol
  products sell" is a much more specific claim than "cosmetics research rises, then
  cosmetics sell". It needs the ingredient entity layer (Model D).
- **Longer leads.** Lab-to-shelf in cosmetics is typically 2–5 years. With 78 months of
  sales history, a lag that long leaves almost no independent observations, so this window
  may not be able to answer it at all.

### Free sources for this axis

OpenAlex is metered as of 2026-08 — `costUsd: 0.001` per request against a `$0` daily
budget, so it returns 429 until an account is funded. `project-data`'s source inventory
still lists it as `F0 지속 무료`; that entry is stale.

Three free substitutes were verified live. They disagree by six times on the same month:

| Source | 2019-01 | What it is | Status |
|---|---|---|---|
| PubMed E-utilities | 1,205 | MeSH-expanded subject match, biomedical | implemented |
| Europe PMC | 843 | life-science index, includes preprints and patents | implemented |
| Crossref | 208 | all disciplines, bibliographic-field match only | verified, not implemented |

The gap is not a disagreement about how many papers exist — it is three different
questions. PubMed expands `cosmetic` through a curated vocabulary
(`"cosmetics"[MeSH Terms]`, `[Pharmacological Action]`, …) so it reaches papers that never
use the word. Crossref matches the term against bibliographic fields only, which is much
narrower here; it is the one to reach for if cross-discipline breadth is ever needed,
being the only one of the three that is not life-science-shaped.

**Never splice two of these into one series.** The join would put a step change in the data
that has nothing to do with publishing.

## Ordering

1. **Done** — Model A. The value is the pipeline and the baseline comparison, not the
   score.
2. **2026-09-10** — Model B, once `rank_snapshot` has depth. Nothing to build; run
   `model_b.py` and it will fit instead of refusing. This is where the first real result
   comes from.
3. **2026-10 onward** — Model C.
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

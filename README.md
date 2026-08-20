# cosmai-ml

Label construction and trend models for Cosmai beauty R&D signals.

Sibling of [`cosmai`](https://github.com/slopindustries/cosmai), which owns collection and
normalization. This repo owns everything downstream of a normalized record: labels,
features, training, evaluation. It deliberately does not collect anything.

## Data flow

```text
cosmai collectors  ->  local working copy  ->  DGX (spark-2ea6)  ->  training
(Threads, YouTube,     project-data/           ./sync.sh            this repo
 public datasets)      cosmai/experiments/
```

`./sync.sh <dir>` streams a directory to the DGX. It needs `DGX_USER` set; the host has
no Tailscale SSH, so a real account and an authorized key are required.

## The prediction task

Given signals observed up to month `t`, predict the direction and size of beauty demand
at `t + horizon`. `horizon` defaults to 3 months.

What "demand" means is not settled — the Cosmai charter leaves final product semantics
open. This repo therefore builds the label from four independent axes and keeps them
separable, so the composite can be redefined without re-deriving the parts.

## Label axes

| Axis | Source | Entity granularity | Cadence | Status |
|---|---|---|---|---|
| 판매량 (sales) | 관세청 면세점 품목별 매출, KOTRA 수출금액 | **category only** (`화장품`, `향수`) | monthly / annual | **implemented** — `labels_sales.py` |
| 학계동향 (academic) | PubMed E-utilities, OpenAlex | ingredient, efficacy concept | monthly | blocked — no collector |
| 키워드 (keyword) | Daum Search, NAVER DataLab, Threads, YouTube, GDELT | keyword, brand, product | daily / weekly | blocked — collectors are still probes |
| 신제품 출시 (launch) | Open Beauty Facts `last_modified_t`, MFDS, eBay Browse, USPTO | product, ingredient | monthly | blocked — no collector |

Source evaluations, quotas, and licence constraints are in
`project-data/0817/beauty-data-source-inventory.md`. Read it before adding an axis:
several candidates permit reading but not storage or derived commercial use.

### The granularity problem

Three axes resolve to an ingredient or keyword. Sales resolves only to a whole product
category. There is no honest join between them at ingredient level.

Three ways out, none free:

1. **Label at category level.** Sales stays the target; academic/keyword/launch signals
   are aggregated up to the category. Loses the resolution that makes the product useful.
2. **Label at ingredient level without sales.** Target becomes a composite of the three
   ingredient-resolvable axes, and sales is demoted to a category-level covariate that
   validates the composite rather than defining it.
3. **Allocate sales to ingredients** by product-composition share. Requires a product
   catalogue with ingredient lists (Open Beauty Facts) *and* per-product sales, which no
   source here provides. Treat as unavailable, not as future work.

Option 2 is the only one that reaches ingredient resolution with data that exists.
Pick before writing the second label builder, and write the decision down — this choice
determines what every downstream feature is allowed to be.

### Confounders already known

- 2020–2022 duty-free volume collapsed for travel reasons, not beauty reasons. Train on
  raw year-over-year growth and the model learns the pandemic. `labels_sales.py` emits
  `per_visitor` for this reason; use it or justify not using it.
- Duty-free sales are dominated by non-resident buyers (largely Chinese wholesale). This
  is not domestic consumer demand and should not be described as such.
- The customs category file carries no unit row. The unit is inferred as 억원 by
  cross-checking monthly totals against the USD file. Growth rates are unit-free, so the
  label is unaffected, but do not quote absolute figures from it.

## What runs today

```sh
uv run --with pandas --with openpyxl labels_sales.py --self-check
uv run --with pandas --with openpyxl labels_sales.py -o sales_labels.csv
```

Output covers 2019-01 to 2025-06 (78 months): monthly cosmetics + perfume duty-free
sales, per-visitor normalization, year-over-year growth, and the forward-shifted target.

No model yet. A baseline on 78 monthly rows and one axis would be a curve fit, not a
finding. The first model waits on a second axis.

## Next

1. Decide the granularity option above.
2. Land one ingredient-resolvable axis (PubMed is the cheapest: free, no auth, stable
   schema, and `project-data` already scopes it).
3. Then a baseline, on at least two axes, evaluated against a
   last-N-months holdout — never a random split, the series is temporal.

## Environment

Python >= 3.13, managed by `uv`, matching `cosmai`. The repo defines no importable
package; modules stay flat and disposable until a contract says otherwise.

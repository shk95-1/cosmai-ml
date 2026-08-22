# EXP-003 — Does stripping the brand from the name close the gap EXP-002 found?

## Identity and status

- Experiment ID: `EXP-003`
- Type: `OTHER` (feature change)
- Status: `COMPLETED`
- Related: `EXP-001`, `EXP-002`
- Owner: hyeonjunni
- Created at: 2026-08-22T12:20+09:00
- Last executed at: 2026-08-22T12:26+09:00

**Declared before execution.** Hypothesis, falsification condition and the pairs used as
the test are fixed below and are not edited afterwards.

## Question

`EXP-002` refuted the sentence transformer but found two pairs it got right and character
n-grams missed. Both have the same shape: one site prints the brand inside the product
name and the other does not.

```text
brand 려            glowpick  "루트젠 여성 맞춤 탈모증상전문케어 샴푸"
                    oliveyoung "려 루트젠 여성맞춤볼륨 탈모증상케어 샴푸"
brand 온그리디언츠  glowpick  "바쿠 글로우 캡슐 로션"
                    oliveyoung "온그리디언츠 바쿠글로우 캡슐 로션 150ml"
```

Candidate pairs are already blocked on brand, so the brand token inside the name carries
no identity information the blocking has not already used. It only makes one string
longer than the other, which character n-gram cosine reads as difference.

## Hypothesis

`[가설]` Removing a leading brand token from the normalised name lifts brand-asymmetric
pairs into the candidate set without merging products that are not the same.

## Falsification condition

Declared before running. The hypothesis is refuted if **any** holds:

1. Either named pair above still falls outside the n-gram top 675 after stripping.
2. Silver-positive recovery drops below 7 of 7 (the `EXP-002` set, unchanged).
3. One-to-many conflicts rise by more than 30% relative to the 155 measured in `EXP-001`
   run 2 — that would indicate the shorter names are merging distinct products.

## Exit condition

One run with the change and one without, on the same frozen table. No weight tuning.

## Scope

### Included

- Leading brand token only, and only when the name actually begins with it

### Excluded

- Brand mentions elsewhere in the name
- Whitespace normalisation. `바쿠 글로우` vs `바쿠글로우` is a second, separate difference
  visible in the same pair; changing two things at once would make the result
  unattributable. If EXP-003 fails, that is the next thing to test, not a second change here.
- Any change to volume or form handling

## Inputs and provenance

| Input | Source | Captured at | Basis | Version | Storage |
| --- | --- | --- | --- | --- | --- |
| `product` (4,804 rows) | shk integration DB | 2026-08-22T02:42Z freeze | internal team data | `cosmai_integrated` | Postgres, DGX |

## Environment

- Host: spark-2ea6, CPU only, 4 threads, `nice -n 15`
- Shared with a Minecraft server that must not be disturbed
- Code: `match_products.py --strip-brand`

## Procedure

1. Add an opt-in `--strip-brand` flag so both variants run from one script.
2. Strip leading tokens from the normalised name while they spell the blocked brand.
3. Run without the flag and with it, on the same table.
4. Report, for each variant: candidate count, score distribution, one-to-many conflicts,
   silver positives recovered, and the rank of the two named pairs.

## Evidence collection

- Metrics: rank of the two named pairs; candidate count; conflicts; silver recovery
- Artifacts: `matches.csv` (baseline), `matches-stripped.csv`
- Integrity: same frozen table for both runs, counts printed at run time

## Observations

```text
[측정] baseline vs brand-stripped, same frozen table
                          baseline    stripped
  candidate pairs              675         627
  score >= 0.90                190         225
  one-to-many conflicts        155         134   (-13.5%)
  silver positives (total)       7          63
  silver recovered               7          63
```

```text
[측정] rank of the two pairs EXP-002 named
  루트젠 여성 맞춤        baseline 446   stripped 417
  바쿠 글로우 캡슐 로션    baseline 199   stripped 149
  Both are inside the 675 budget in BOTH runs.
```

```text
[측정] declared falsification checks, as executed
  1. a named pair outside top 675 after stripping : not met
  2. silver recovery below its set                : not met
  3. conflicts up more than 30% (-13.5%)          : not met
```

## Interpretation

```text
[추론] Correction to this experiment's own design, condition 1. The two named pairs sit
at ranks 446 and 199 in the BASELINE run -- inside the 675 budget before the change. So
condition 1 could not have been met by either outcome, and it tested nothing.

The cause is a mismatch between EXP-002 and this experiment. EXP-002 compared raw name
cosine with no volume or form bonus, deliberately, to isolate the similarity function.
match_products.py scores with those bonuses included. Both named pairs agree on form, so
+0.30 already carried them into the candidate set. The "gap" EXP-002 reported was a gap
in raw cosine ranking, not a gap in the production matcher. That was not stated when this
experiment was declared, and it should have been.
```

```text
[추론] Correction, condition 2. The declaration says "the EXP-002 set, unchanged". The
script recomputed silver positives from the stripped names instead, so the target set
grew from 7 to 63 and the comparison is not the one declared. Both runs recovered 100%
of their own set, so nothing here is contradicted, but the number reported is not the
number promised.
```

```text
[추론] The unplanned measurement is the informative one. Silver positives are pairs whose
normalised names match exactly; stripping the brand took that set from 7 to 63. Those 56
additional pairs are near-certainly the same product and were previously invisible as
exact matches purely because one site printed the brand in the title and the other did
not. The asymmetry EXP-002 found in two pairs is present in roughly thirty times more.
```

```text
[추론] The over-merging risk this change carried did not appear. Shorter names could have
collapsed distinct products within a brand, which is what condition 3 watched for.
One-to-many conflicts fell 13.5% (155 -> 134) while pairs above 0.90 rose from 190 to 225,
which is the opposite pattern: the change is separating rather than merging. Total
candidates fell 675 -> 627, consistent with pairs that were marginal on length alone
resolving one way or the other rather than sitting near the threshold.
```

## Result

- Outcome: `SUPPORTED`, with two recorded defects in the experiment's own design
- Falsification condition met: `NO` — but conditions 1 and 2 did not measure what they
  were written to measure. See the corrections above. Only condition 3 tested what it said.
- Exit condition met: `YES`
- Known limitations:
  - **Condition 1 was vacuous.** The evidence for the hypothesis therefore rests on the
    silver-set growth, which was not the declared test.
  - **Condition 2 measured a recomputed set.** Declared as unchanged, executed as changed.
  - Precision is still unmeasured for every variant. `to-label.csv` remains the blocking
    item, and it is now stale: it was sampled from the baseline matcher's output.
  - Leading-position stripping only. A brand named mid-title is untouched, and no evidence
    here says whether that matters.

## Next

Keep `--strip-brand` on. The conflict and 0.90-band movement both favour it and nothing
measured argues against it.

Two things follow from the corrections rather than from the result:

1. **Re-sample the labelling file** from the stripped matcher. The existing 300 pairs came
   from the baseline and no longer represent what the matcher emits.
2. **The whitespace difference is still untested.** `바쿠 글로우` versus `바쿠글로우` was
   excluded from this experiment on purpose so the result stayed attributable. It is the
   obvious EXP-004.

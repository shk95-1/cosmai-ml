# EXP-002 — Does a Korean sentence transformer beat character n-grams at product matching?

## Identity and status

- Experiment ID: `EXP-002`
- Type: `OTHER` (model comparison)
- Status: `COMPLETED`
- Related: `EXP-001`, `MODELS-CATALOGUE.md` C2
- Owner: hyeonjunni
- Created at: 2026-08-22T12:05+09:00
- Last executed at: 2026-08-22T12:08+09:00

**This section is written before execution.** The hypothesis, falsification condition and
comparison metric below are fixed now, and the result is filled in afterwards without
editing them. `EXP-001` could not make that claim; this one can, and that is the only
reason its numbers mean more.

## Question

`EXP-001` used character n-grams and said a transformer was not worth a GPU at this scale.
The GPU turned out to be free. So: does a Korean sentence embedding find same-product
pairs that character n-grams miss, by enough to justify carrying the dependency?

## Hypothesis

`[가설]` A Korean sentence-transformer embedding recovers cross-source same-product pairs
that character n-gram TF-IDF ranks below threshold — specifically pairs where the two
sites describe one product in different words rather than different spellings.

## Falsification condition

Declared before running. The hypothesis is refuted if **either** holds:

1. At an equal candidate budget (top 675 cross-source pairs, matching `EXP-001`'s output
   size), the transformer recovers **no more silver positives** than character n-grams.
2. Inspection of 10 pairs the transformer ranks high and n-grams rank low shows **fewer
   than 3 correct** — i.e. its distinctive candidates are mostly noise.

## Comparison metric, and why it is weak

There are still no ground-truth labels, so precision cannot be compared. Instead:

**Silver positives** — cross-source pairs where the normalised name matches *exactly*, the
normalised brand matches, and volume either agrees or is unstated on both sides. These are
near-certainly the same product. They are a **recall proxy only**: a method that finds all
of them may still be wrong about everything else, and a method that misses some may be
right about harder pairs. The number is a floor, not a score.

Both methods see the same blocking and the same normalisation, so the comparison isolates
the similarity function and nothing else.

## Exit condition

One run of each method over the same 4,804 products. No hyperparameter search. If the
transformer needs tuning to compete, that is itself the answer for this deadline.

## Scope

### Included

- Same `product` table, same freeze (2026-08-22T02:42Z)
- One Korean sentence-transformer checkpoint, chosen for Korean coverage
- Comparison against `EXP-001` run 2 (with the form feature)

### Excluded

- Fine-tuning. There is no labelled set to fine-tune on.
- Multi-model comparison. One checkpoint answers the "worth the dependency" question.
- Any claim about precision.

## Inputs and provenance

| Input | Source | Captured at | Basis | Version | Storage |
| --- | --- | --- | --- | --- | --- |
| `product` (4,804 rows) | shk integration DB | 2026-08-22T02:42Z freeze | internal team data | `cosmai_integrated` | Postgres, DGX |
| sentence-transformer checkpoint | Hugging Face `jhgan/ko-sroberta-multitask` | 2026-08-22T12:07+09:00 | model card licence — not re-verified | 768-dim | DGX local cache |

## Environment

- Host: spark-2ea6, GB10, 20 cores, 119 GB
- **Shared with a Minecraft server that must not be disturbed.** Caps: 4 threads,
  `nice -n 15`. GPU was 0% and unclaimed before this experiment; that is what makes it
  available.
- Runtime: Python 3.12, torch 2.13.0+cu130, sentence-transformers, scikit-learn 1.9.0
- GPU: NVIDIA GB10, CUDA available

## Procedure

1. Load the same products with the same normalisation as `EXP-001`.
2. Build silver positives; record the count before scoring anything.
3. Score all cross-source within-brand pairs with n-gram cosine (already have).
4. Score the same pairs with embedding cosine.
5. Take the top 675 of each. Count silver positives recovered by each.
6. Take 10 pairs ranked high by the transformer and low by n-grams. Inspect by eye.
7. Record GPU memory and wall time, and confirm the Minecraft process is unchanged.

## Evidence collection

- Metrics: silver positives recovered by each method at equal budget; overlap; wall time;
  GPU memory
- Artifacts: `~/cosmai-data/matches-embed.csv`, `~/cosmai-data/exp002-disagreement.csv`
- Integrity: both methods read the same frozen table; counts printed at run time

## Observations

```text
[측정] Candidate set, printed before any scoring
  products 4,804   within-brand cross-source pairs 3,963
  silver positives 7 of 3,963
```

```text
[측정] Embedding run
  jhgan/ko-sroberta-multitask, 768-dim, on cuda (GB10)
  encode 4,804 names in 17.7 s, GPU peak 512.5 MB
```

```text
[측정] Recall proxy at a budget of 675 pairs
  char n-gram  7 / 7 silver positives
  embedding    7 / 7 silver positives
  top-675 sets overlap on 425 of 675 pairs
  pairs the embedding ranks top-675 that n-grams do not: 250
```

```text
[측정] Inspection of the 10 highest-ranked disagreement pairs, by eye
  correct 2, wrong 8.

  correct:
    루트젠 여성 맞춤 탈모증상전문케어 샴푸 <-> 려 루트젠 여성맞춤볼륨 탈모증상케어 샴푸
    바쿠 글로우 캡슐 로션 <-> 온그리디언츠 바쿠글로우 캡슐 로션 150ml

  wrong (6 of the 8 are the same failure, razors):
    도루코윈 3중날 면도기 1P <-> 도루코 PACE 3D모션 면도기+면도날 5입
    도루코윈4 시스템 면도기 SET <-> 도루코 PACE7 면도기 (핸들+7입날)
    도루코윈4 시스템 면도기 SET <-> 도루코 PACE7 면도기 (핸들+13입날)
    도루코윈 3중날 면도기 4P <-> 도루코 PACE 3D모션 면도기+면도날 5입
    도루코 6중날 남성 면도기 2P <-> 도루코 PACE 3D모션 면도기+면도날 5입
    도루코윈 3중날 면도기 1P <-> 도루코 PACE7 면도기 (핸들+13입날)
    아쿠아 스쿠알란 수분크림 <-> 에스네이처 아쿠아 오아시스 수분 젤크림  (glowpick, hwahae)
```

```text
[측정] Host during the run
  load average 0.33 -> 0.30 of 20 cores
  Minecraft java 25.5% -> 25.3% CPU, 10.8 GB RSS unchanged
  GPU returned to 0% after the run; peak 512 MB of an otherwise idle device
```

## Interpretation

```text
[추론] Falsification condition 1 was met, but it did not discriminate. Only 7 silver
positives exist, and both methods recovered all 7. A ceiling both methods reach says
nothing about which is better. The metric was designed before seeing that the exact-name
criterion would be this rare, and it was too strict to carry the comparison. That is a
flaw in this experiment's design, not a property of either method.
```

```text
[추론] Falsification condition 2 was met and did discriminate: 2 of 10 correct, against
a declared bar of 3. The failure has one shape. Six of the eight wrong pairs are razors
matched to different razors, and the other two are a 수분크림 matched to a different
brand's 젤크림. The embedding is scoring "these describe the same kind of thing", which
is what a model trained for semantic textual similarity is built to do, and which is the
wrong question. Product identity needs the parts of a string that STS training teaches a
model to discount -- model numbers, blade counts, pack sizes.
```

```text
[추론] The two correct disagreements share a shape too: one side carries a brand prefix
the other omits (려, 온그리디언츠). Character n-gram cosine penalises that as a length
mismatch. So the embedding does hold signal the n-gram lacks -- it is simply swamped, at
this budget, by category-level matches.
```

```text
[추론] EXP-001 justified skipping the transformer on cost. That justification was wrong:
17.7 s and 512 MB on an idle GPU is not a cost worth avoiding. The right reason is the
one measured here -- semantic similarity is the wrong objective for identity matching --
and it is a stronger reason, because it does not change when hardware does.
```

## Result

- Outcome: `REFUTED`
- Falsification condition met: `YES` — both criteria, though only the second one
  discriminated
- Exit condition met: `YES`
- Known limitations:
  - **Silver positives measure recall on the easy cases by construction**, and with only 7
    of them the measure saturated. Any future comparison needs the hand-labelled set.
  - The inspection was 10 pairs by one reader. It is enough to meet a declared bar of 3,
    not enough to estimate precision.
  - One checkpoint tested. A model trained for entity matching rather than sentence
    similarity might behave differently; this experiment says nothing about that.
  - Neither method's precision is established. `REFUTED` here means "does not beat
    n-grams at this task on this evidence", not "n-grams are good".

## Next

Character n-grams plus the volume and form features stay the production matcher.

The embedding is not discarded, because the two correct disagreements point at a real gap:
names where one side omits a brand prefix. A cheaper fix for that specific gap than
carrying a transformer is to strip a leading brand token from the name before scoring,
since brand is already blocked on. Worth trying, and testable against the same
disagreement file.

`to-label.csv` from EXP-001 remains the blocking item. Everything above is a comparison
between two unmeasured things.


"""EXP-002 — character n-gram cosine vs Korean sentence-embedding cosine.

Runs the comparison declared in experiments/EXP-002-transformer-vs-ngram-matching.md.
The declaration is fixed; this script only produces the numbers that fill it in.

Both methods get the same products, the same normalisation and the same blocking, and
are compared on the raw name-similarity signal alone -- no volume or form bonus on either
side. That is deliberate: EXP-001 already showed those features carry real signal, and
mixing them in here would compare two scorers rather than two similarity functions.

Silver positives are a recall floor, not a score. See the experiment log.
"""

from __future__ import annotations

import argparse
import sys
import time
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from match_products import load_products

BUDGET = 675  # EXP-001 run 2 output size, fixed in the declaration
MODEL = "jhgan/ko-sroberta-multitask"


def all_cross_source_pairs(frame: pd.DataFrame) -> list[tuple[int, int]]:
    """Every within-brand, cross-source pair. No threshold -- both methods rank these."""
    pairs = []
    for brand, group in frame.groupby("brand_norm"):
        if not brand or len(group) < 2:
            continue
        index = group.index.to_numpy()
        for i, j in combinations(index, 2):
            if frame.at[i, "source"] != frame.at[j, "source"]:
                pairs.append((int(i), int(j)))
    return pairs


def silver_positives(frame: pd.DataFrame, pairs: list[tuple[int, int]]) -> set[tuple[int, int]]:
    """Pairs that are near-certainly the same product.

    Exact normalised-name match, same brand, and volumes that either agree or are unstated
    on both sides. Built from the pair list itself so both methods are scored against the
    identical target set.
    """
    silver = set()
    for i, j in pairs:
        if frame.at[i, "norm"] != frame.at[j, "norm"]:
            continue
        vol_i, vol_j = frame.at[i, "vol"], frame.at[j, "vol"]
        if vol_i is not None and vol_j is not None and vol_i != vol_j:
            continue
        silver.add((i, j))
    return silver


def ngram_scores(frame: pd.DataFrame, pairs: list[tuple[int, int]]) -> np.ndarray:
    vectoriser = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectoriser.fit_transform(frame["norm"])
    left = matrix[[i for i, _ in pairs]]
    right = matrix[[j for _, j in pairs]]
    return np.asarray(left.multiply(right).sum(axis=1)).ravel()


def embed_scores(frame: pd.DataFrame, pairs: list[tuple[int, int]]) -> tuple[np.ndarray, dict]:
    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    started = time.perf_counter()
    model = SentenceTransformer(MODEL, device=device)
    vectors = model.encode(
        frame["norm"].tolist(),
        batch_size=64,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    elapsed = time.perf_counter() - started

    left = vectors[[i for i, _ in pairs]]
    right = vectors[[j for _, j in pairs]]
    meta = {
        "device": device,
        "model": MODEL,
        "dim": int(vectors.shape[1]),
        "encode_seconds": round(elapsed, 1),
        "gpu_peak_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1)
        if device == "cuda"
        else 0.0,
    }
    return (left * right).sum(axis=1), meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--budget", type=int, default=BUDGET)
    parser.add_argument("--out", default="matches-embed.csv")
    parser.add_argument("--disagreement", default="exp002-disagreement.csv")
    args = parser.parse_args()

    frame = load_products(args.dsn)
    pairs = all_cross_source_pairs(frame)
    silver = silver_positives(frame, pairs)

    # Printed before any scoring, so the target set cannot be read as chosen after the fact.
    print(f"[측정] products {len(frame)}  candidate pairs {len(pairs)}")
    print(f"[측정] silver positives {len(silver)} of {len(pairs)} pairs")

    ngram = ngram_scores(frame, pairs)
    embed, meta = embed_scores(frame, pairs)
    print(f"[측정] embedding {meta['model']} dim {meta['dim']} on {meta['device']}, "
          f"encode {meta['encode_seconds']}s, GPU peak {meta['gpu_peak_mb']} MB")

    budget = min(args.budget, len(pairs))
    top_ngram = set(map(tuple, np.array(pairs)[np.argsort(-ngram)[:budget]].tolist()))
    top_embed = set(map(tuple, np.array(pairs)[np.argsort(-embed)[:budget]].tolist()))

    hit_ngram = len(silver & top_ngram)
    hit_embed = len(silver & top_embed)
    print(f"\n[측정] at a budget of {budget} pairs:")
    print(f"  char n-gram recovers {hit_ngram} / {len(silver)} silver positives")
    print(f"  embedding  recovers {hit_embed} / {len(silver)} silver positives")
    print(f"  the two top-{budget} sets overlap on {len(top_ngram & top_embed)} pairs")

    # Pairs the transformer likes and n-grams do not: the declaration says inspect 10.
    rank_ngram = {p: r for r, p in enumerate(map(tuple, np.array(pairs)[np.argsort(-ngram)].tolist()))}
    rank_embed = {p: r for r, p in enumerate(map(tuple, np.array(pairs)[np.argsort(-embed)].tolist()))}
    only_embed = sorted(top_embed - top_ngram, key=lambda p: rank_embed[p])

    rows = []
    for i, j in only_embed:
        rows.append(
            {
                "embed_rank": rank_embed[(i, j)],
                "ngram_rank": rank_ngram[(i, j)],
                "embed_score": round(float(embed[pairs.index((i, j))]), 4),
                "ngram_score": round(float(ngram[pairs.index((i, j))]), 4),
                "is_same_product": "",
                "source_a": frame.at[i, "source"], "name_a": frame.at[i, "name"],
                "source_b": frame.at[j, "source"], "name_b": frame.at[j, "name"],
            }
        )
    disagreement = pd.DataFrame(rows)
    disagreement.to_csv(args.disagreement, index=False)
    print(f"\n[측정] pairs the embedding ranks in its top {budget} and n-grams do not: "
          f"{len(disagreement)}  -> {args.disagreement}")

    print("\n[측정] first 10 of those, for inspection:")
    for _, r in disagreement.head(10).iterrows():
        print(f"  e{r.embed_score:.2f}/n{r.ngram_score:.2f}  [{r.source_a}] {str(r.name_a)[:42]}")
        print(f"                     [{r.source_b}] {str(r.name_b)[:42]}")

    pd.DataFrame(
        {
            "embed_score": embed, "ngram_score": ngram,
            "source_a": [frame.at[i, "source"] for i, _ in pairs],
            "name_a": [frame.at[i, "name"] for i, _ in pairs],
            "source_b": [frame.at[j, "source"] for _, j in pairs],
            "name_b": [frame.at[j, "name"] for _, j in pairs],
        }
    ).sort_values("embed_score", ascending=False).to_csv(args.out, index=False)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

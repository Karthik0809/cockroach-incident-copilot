"""Measure whether the memory layer actually recalls the right thing.

Retrieval quality is the whole product here, so it gets a number rather than a
vibe. Ten alerts, each written to describe a *different* service and different
wording than the incident it should match, so lexical overlap cannot carry it.

Two of the ten are control cases with no correct answer. Those are the
interesting ones: a memory system that returns something confident for the
espresso machine is worse than one that says nothing, and precision-only
scoring would hide that.

    python -m scripts.eval
    python -m scripts.eval --json      # machine-readable, for CI

Reported metrics:
    recall@1     correct incident is the top hit
    recall@k     correct incident is anywhere in the returned set
    MRR          1/rank of the correct hit, averaged
    abstention   control cases correctly returning nothing
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import config, memory  # noqa: E402

CASES = pathlib.Path(__file__).resolve().parents[1] / "data" / "eval_alerts.json"


def _external_ids(hits: list[memory.Recollection]) -> list[str]:
    """Recollection carries the title, not external_id, so resolve them."""
    if not hits:
        return []
    with memory.connect() as conn:
        rows = conn.execute(
            "SELECT id, external_id FROM incidents WHERE id = ANY(%s)",
            ([h.incident_id for h in hits],),
        ).fetchall()
    by_id = {str(r["id"]): r["external_id"] for r in rows}
    return [by_id.get(h.incident_id) or "" for h in hits]


def run() -> dict:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    scored, controls = [], []

    for case in cases:
        hits = memory.recall_incidents(case["alert"])
        ids = _external_ids(hits)
        expected = case["expect"]

        if expected is None:
            controls.append(
                {
                    "alert": case["alert"],
                    "abstained": len(hits) == 0,
                    "returned": ids,
                    "why": case["why"],
                }
            )
            continue

        rank = ids.index(expected) + 1 if expected in ids else 0
        scored.append(
            {
                "alert": case["alert"],
                "expected": expected,
                "returned": ids,
                "rank": rank,
                "top1": rank == 1,
                "hit": rank > 0,
                "reciprocal_rank": (1.0 / rank) if rank else 0.0,
                "why": case["why"],
            }
        )

    n = len(scored) or 1
    return {
        "config": {
            "recall_k": config.RECALL_K,
            "max_distance": config.RECALL_MAX_DISTANCE,
            "embed_model": config.EMBED_MODEL_ID,
        },
        "recall_at_1": sum(c["top1"] for c in scored) / n,
        "recall_at_k": sum(c["hit"] for c in scored) / n,
        "mrr": sum(c["reciprocal_rank"] for c in scored) / n,
        "abstention_rate": (
            sum(c["abstained"] for c in controls) / len(controls) if controls else None
        ),
        "cases": scored,
        "controls": controls,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    args = parser.parse_args()

    results = run()

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print("=" * 74)
    print("RECALL QUALITY")
    print(
        f"  k={results['config']['recall_k']}  "
        f"max_distance={results['config']['max_distance']}"
    )
    print("=" * 74)

    for case in results["cases"]:
        mark = "PASS" if case["top1"] else ("partial" if case["hit"] else "MISS")
        print(f"\n[{mark}] expected {case['expected']}, got {case['returned'] or '--'}")
        print(f"  alert: {case['alert'][:90]}...")
        print(f"  why:   {case['why']}")

    print("\n" + "-" * 74)
    print("CONTROLS (correct answer is: nothing)")
    for ctrl in results["controls"]:
        mark = "PASS" if ctrl["abstained"] else "FALSE POSITIVE"
        print(f"\n[{mark}] returned {ctrl['returned'] or '--'}")
        print(f"  alert: {ctrl['alert'][:90]}...")

    print("\n" + "=" * 74)
    print(f"  recall@1     {results['recall_at_1']:.0%}")
    print(f"  recall@k     {results['recall_at_k']:.0%}")
    print(f"  MRR          {results['mrr']:.3f}")
    print(f"  abstention   {results['abstention_rate']:.0%}")
    print("=" * 74)
    print("\nTuning knobs: RECALL_MAX_DISTANCE (lower = more abstention, fewer")
    print("false positives) and RECALL_K, both in .env.")


if __name__ == "__main__":
    main()

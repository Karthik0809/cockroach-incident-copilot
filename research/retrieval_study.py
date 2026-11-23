"""How should incident memory be keyed so a reworded recurrence finds it?  (PMBench, local embeddings)

Query: the recurrence alert (alert2). Memory: one record per incident. Compares what the record
contains and dense vs. lexical vs. hybrid scoring. Writes research/results/retrieval_results.json.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_robustness as mr  # noqa: E402

from build_benchmark import load_bench  # noqa: E402
items = load_bench()
n = len(items)
Q = mr.embed([x["alert2"] for x in items], "search_query: ")
tok = lambda s: re.findall(r"[a-z]+", s.lower())  # noqa: E731
z = lambda S: (S - S.mean(1, keepdims=True)) / (S.std(1, keepdims=True) + 1e-9)  # noqa: E731


def score(S):
    gold = S[np.arange(n), np.arange(n)][:, None]
    rank = (S > gold).sum(1) + 1
    return {"top1": float((rank == 1).mean()), "top5": float((rank <= 5).mean()), "mrr": float((1 / rank).mean())}


keys = {
    "summary + lesson": lambda x: f"{x['summary']}\nLesson: {x['lesson']}",
    "first alert only": lambda x: x["alert"],
    "first alert + summary + lesson": lambda x: f"Alert: {x['alert']}\nWhat happened: {x['summary']}\nLesson: {x['lesson']}",
}
res = {}
for name, f in keys.items():
    res[f"dense: {name}"] = score(Q @ mr.embed([f(x) for x in items], "search_document: ").T)
bm = BM25Okapi([tok(f"{x['alert']} {x['summary']}") for x in items])
B = np.array([bm.get_scores(tok(x["alert2"])) for x in items])
res["BM25: first alert + summary"] = score(B)
E = Q @ mr.embed([keys["first alert + summary + lesson"](x) for x in items], "search_document: ").T
res["hybrid: dense + 0.5 x BM25 (z-scored)"] = score(z(E) + 0.5 * z(B))
for k, v in res.items():
    print(f"{k:42s} top1={v['top1']:.3f} top5={v['top5']:.3f} MRR={v['mrr']:.3f}")
(mr.OUT / "retrieval_results.json").write_text(json.dumps({"n_incidents": n, "results": res}, indent=1))

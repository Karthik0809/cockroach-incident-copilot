"""Render research/PAPER.md from PAPER.template.md + results JSON (no hand-typed numbers)."""
import json
from pathlib import Path

H = Path(__file__).resolve().parent
ret = json.loads((H / "results" / "retrieval_results.json").read_text())
mem = json.loads((H / "results" / "memory_results.json").read_text())
R, M = ret["results"], mem["main"]
pc = lambda x: f"{100 * x:.1f}%"  # noqa: E731
RANK = [("similarity", "Similarity"), ("trust", "Trust (production)"), ("trust+prov", "**Trust + provenance gate**")]

retrieval_table = "| Memory record / scoring | Top-1 | Top-5 | MRR |\n|---|---|---|---|\n" + "\n".join(
    f"| {k} | {pc(v['top1'])} | {pc(v['top5'])} | {v['mrr']:.3f} |" for k, v in R.items())

main_table = ("Always-answer agent (no abstention), mean ± std over 5 seeds:\n\n"
              "| Ranker | Correct lesson first | Poisoned fix served | Stale wrong lesson served |\n|---|---|---|---|\n" +
              "\n".join(f"| {lab} | {pc(M[k]['top1_no_abstention']['mean'])} ± {100*M[k]['top1_no_abstention']['std']:.1f} | "
                        f"{pc(M[k]['poison_asr_no_abstention']['mean'])} ± {100*M[k]['poison_asr_no_abstention']['std']:.1f} | "
                        f"{pc(M[k]['stale_twin_served_no_abstention']['mean'])} ± {100*M[k]['stale_twin_served_no_abstention']['std']:.1f} |"
                        for k, lab in RANK))
g = lambda d, k, m: pc(d[k][m]["mean"])  # noqa: E731
C = mem["clean_memory"]
abst_prose = (f"With calibrated abstention, the rankers abstain correctly on {g(M,'similarity','abstention_accuracy')} / "
              f"{g(M,'trust','abstention_accuracy')} / {g(M,'trust+prov','abstention_accuracy')} of novel incidents and serve poisoned "
              f"fixes on {g(M,'similarity','poison_attack_success')} / {g(M,'trust','poison_attack_success')} / {g(M,'trust+prov','poison_attack_success')} "
              f"of alerts — but they then answer few known incidents correctly (recall@1 {g(M,'similarity','recall_at_1')} / "
              f"{g(M,'trust','recall_at_1')} / {g(M,'trust+prov','recall_at_1')}), so abstention alone trades helpfulness for safety. "
              f"Clean memory (no twins, no poison): top-1 {g(C,'similarity','top1_no_abstention')} / {g(C,'trust','top1_no_abstention')} / "
              f"{g(C,'trust+prov','top1_no_abstention')}.")


def sweep_table(sw, label, fmt):
    rows = "\n".join(f"| {fmt(x)} | " + " | ".join(pc(sw[x][k]["poison_asr_no_abstention"]["mean"]) for k, _ in RANK) + " |"
                     for x in sorted(sw, key=float))
    return f"| {label} | Similarity | Trust | Trust + provenance |\n|---|---|---|---|\n{rows}"


SP, SN = mem["sweep_poison"], mem["sweep_noise"]
twins = [M[k]["stale_twin_served_no_abstention"]["mean"] for k, _ in RANK]
vals = dict(
    n=mem["n_postmortems"],
    r_sum_t1=pc(R["dense: summary + lesson"]["top1"]), r_full_t1=pc(R["dense: first alert + summary + lesson"]["top1"]),
    r_hyb_t1=pc(R["hybrid: dense + 0.5 x BM25 (z-scored)"]["top1"]), r_hyb_t5=pc(R["hybrid: dense + 0.5 x BM25 (z-scored)"]["top5"]),
    key_gain=f"{100 * (R['dense: first alert + summary + lesson']['top1'] - R['dense: summary + lesson']['top1']):+.1f}",
    p3_sim=pc(SP["3"]["similarity"]["poison_asr_no_abstention"]["mean"]),
    main_trust_asr=pc(M["trust"]["poison_asr_no_abstention"]["mean"]),
    main_prov_asr=pc(M["trust+prov"]["poison_asr_no_abstention"]["mean"]),
    n30_trust=pc(SN["0.3"]["trust"]["poison_asr_no_abstention"]["mean"]),
    twin_lo=pc(min(twins)), twin_hi=pc(max(twins)),
    prov_cost=f"{100 * (M['similarity']['top1_no_abstention']['mean'] - M['trust+prov']['top1_no_abstention']['mean']):.1f}",
    retrieval_table=retrieval_table, main_table=main_table, abst_prose=abst_prose,
    poison_table=sweep_table(SP, "Poisoned memories", lambda x: x),
    noise_table=sweep_table(SN, "Feedback noise", lambda x: f"{100*float(x):.0f}%"),
)
(H / "PAPER.md").write_text((H / "PAPER.template.md").read_text(encoding="utf-8").format(**vals), encoding="utf-8")
print("wrote", H / "PAPER.md")

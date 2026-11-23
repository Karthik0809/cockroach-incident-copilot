"""Build PMBench: an incident-memory benchmark from real public postmortems.

Source: Dan Luu's curated list of public post-mortems (github.com/danluu/post-mortems), ~250
real outages (Amazon, Cloudflare, CircleCI, GitHub, ...), each with a short root-cause summary.

For every postmortem an LLM (Gemini, temperature 0) writes three things:
  alert        what an on-call engineer would be paged with at minute 5: SYMPTOMS ONLY, no
               company name, no root cause, no fix, different service names and vocabulary
               (low lexical overlap is deliberate: the agent must match on the failure pattern)
  lesson       the generalizable lesson a team would record after resolving it (correct)
  wrong_lesson a plausible but WRONG lesson for the same symptoms (a stale/mistaken memory)

Run:  python research/build_benchmark.py   -> research/data/pmbench.json
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

def _ollama_json(prompt: str, num_ctx: int = 8192) -> tuple[dict | None, dict]:
    """Local backend: qwen3:8b on Ollama, temperature 0, JSON mode, thinking off."""
    import urllib.request
    t0 = time.time()
    body = {"model": os.environ.get("OLLAMA_MODEL", "qwen3:8b"), "think": False, "stream": False,
            "format": "json", "options": {"temperature": 0, "num_ctx": num_ctx, "seed": 0},
            "messages": [{"role": "user", "content": prompt}]}
    try:
        req = urllib.request.Request("http://localhost:11434/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=900).read())
        raw = d["message"]["content"]
        meta = {"latency_s": round(time.time() - t0, 2), "in_tokens": d.get("prompt_eval_count", 0),
                "out_tokens": d.get("eval_count", 0)}
        s, e = raw.find("{"), raw.rfind("}")
        return (json.loads(raw[s:e + 1]) if s != -1 else None), meta
    except Exception as ex:  # noqa: BLE001
        return None, {"latency_s": round(time.time() - t0, 2), "error": str(ex)[:200]}


HERE = Path(__file__).resolve().parent
SRC = HERE / "data" / "postmortems_README.md"
OUT = HERE / "data" / "pmbench.json"
BACKEND = os.environ.get("LLM_BACKEND", "ollama")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b") if BACKEND == "ollama" else os.environ.get("BENCH_MODEL", "gemini-flash-lite-latest")
BATCH = 4


SRC_URL = "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md"


def parse() -> list[dict]:
    if not SRC.exists():                       # not redistributed: fetched on demand
        import urllib.request
        SRC.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SRC_URL, SRC)
    rows, section = [], None
    for line in SRC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        m = re.match(r"^\[([^\]]+)\]\(([^)]+)\)\.?\s*(.+)$", line.strip())
        if m and section and "Other lists" not in section and "Analysis" not in section:
            company, url, summary = m.groups()
            if len(summary.split()) >= 18:          # need enough detail for symptoms + cause
                rows.append({"company": company.strip(), "url": url.strip(),
                             "category": section, "summary": summary.strip()})
    for i, r in enumerate(rows):
        r["id"] = f"PM-{i:03d}"
    return rows


PROMPT = """You are building an on-call incident benchmark from real public postmortems.
For EACH postmortem below return an object with:
  "id": the given id,
  "alert": 1-3 sentences an on-call engineer is paged with in the first minutes. SYMPTOMS ONLY
           (what users/dashboards show). Do NOT name the company, the root cause, the fix, or any
           distinctive term from the summary. Invent different service names. Vary wording.
  "alert2": a SECOND, independently worded page for a later recurrence of the same failure
           (different service names, different observer, different metrics) -- same rules as alert.
  "lesson": 1-2 sentences: the generalizable root cause + what to check/do, as a team would record it.
  "wrong_lesson": 1-2 sentences: a PLAUSIBLE but WRONG root cause + fix for the same symptoms
           (the kind of stale or mistaken memory that misleads responders).
Return JSON: {"items": [ ... ]}.

POSTMORTEMS:
"""


def generate(rows: list[dict]) -> dict:
    if BACKEND == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        m = genai.GenerativeModel(MODEL, generation_config={"temperature": 0.0,
                                                            "response_mime_type": "application/json"})
    out = {}
    if OUT.exists():
        out = {x["id"]: x for x in json.loads(OUT.read_text())["items"]}
    todo = [r for r in rows if r["id"] not in out]
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        body = "\n".join(f'- id={r["id"]} | {r["summary"]}' for r in chunk)
        if BACKEND == "gemini":
            time.sleep(4.5)
        for attempt in range(5):
            try:
                if BACKEND == "ollama":
                    data, meta = _ollama_json(PROMPT + body)
                    if not data:
                        raise RuntimeError(meta.get("error", "no JSON"))
                    items = data["items"]
                else:
                    items = json.loads(m.generate_content(PROMPT + body).text)["items"]
                break
            except Exception as e:  # noqa: BLE001
                print("retry", attempt, str(e)[:120]); time.sleep(10 * (attempt + 1)); items = []
        by = {r["id"]: r for r in chunk}
        for it in items:
            if it.get("id") in by and it.get("alert") and it.get("alert2") and it.get("lesson") and it.get("wrong_lesson"):
                out[it["id"]] = {**by[it["id"]], "alert": it["alert"].strip(), "alert2": it["alert2"].strip(),
                                 "lesson": it["lesson"].strip(), "wrong_lesson": it["wrong_lesson"].strip()}
        print(f"{len(out)}/{len(rows)}", flush=True)
        OUT.write_text(json.dumps({"source": "github.com/danluu/post-mortems", "generator": MODEL,
                                   "items": list(out.values())}, indent=1))
    return out


PUBLIC = HERE / "data" / "pmbench_public.json"


def write_public():
    """Committed copy without the source summaries (those are re-fetched from the original list)."""
    items = json.loads(OUT.read_text())["items"]
    keep = ["id", "company", "url", "category", "alert", "alert2", "lesson", "wrong_lesson"]
    PUBLIC.write_text(json.dumps({"source": "github.com/danluu/post-mortems (summaries not included)",
                                  "generator": MODEL, "items": [{k: x[k] for k in keep} for x in items]}, indent=1))


def load_bench() -> list[dict]:
    """Full benchmark: local file if present, else public file + summaries re-joined from the source list."""
    if OUT.exists():
        return json.loads(OUT.read_text())["items"]
    src = {r["id"]: r for r in parse()}
    return [{**x, "summary": src[x["id"]]["summary"]} for x in json.loads(PUBLIC.read_text())["items"]]


if __name__ == "__main__":
    rows = parse()
    print("parsed", len(rows), "postmortems")
    generate(rows)
    write_public()
    print("wrote", OUT, "and", PUBLIC)

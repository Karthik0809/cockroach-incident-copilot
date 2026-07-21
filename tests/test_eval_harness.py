"""The eval set is a claim about rigor, so it gets checked like one."""

import json
import pathlib

CASES = json.loads(
    (
        pathlib.Path(__file__).resolve().parents[1] / "data" / "eval_alerts.json"
    ).read_text(encoding="utf-8")
)
SEEDS = json.loads(
    (pathlib.Path(__file__).resolve().parents[1] / "data" / "incidents.json").read_text(
        encoding="utf-8"
    )
)
SEED_IDS = {s["external_id"] for s in SEEDS}


def test_every_expected_id_actually_exists_in_the_seed_data():
    """A typo here would silently show up as a recall failure."""
    for case in CASES:
        if case["expect"] is not None:
            assert case["expect"] in SEED_IDS, case["expect"]


def test_the_eval_set_has_control_cases():
    """Without these, precision-only scoring hides a system that matches
    everything confidently."""
    controls = [c for c in CASES if c["expect"] is None]
    assert len(controls) >= 2


def test_every_case_explains_itself():
    for case in CASES:
        assert case["why"].strip()
        assert len(case["alert"]) > 40


def test_eval_alerts_do_not_reuse_the_seed_service_names():
    """If an eval alert names the same service as its target incident, we are
    measuring string matching, not semantic recall."""
    by_id = {s["external_id"]: s["service"] for s in SEEDS}
    for case in CASES:
        if case["expect"] is None:
            continue
        assert by_id[case["expect"]] not in case["alert"], case["expect"]


def test_seed_incidents_are_complete():
    for seed in SEEDS:
        for field in ("external_id", "title", "service", "symptoms", "root_cause"):
            assert seed.get(field), f"{seed.get('external_id')}: missing {field}"
        assert seed["lesson"].strip()

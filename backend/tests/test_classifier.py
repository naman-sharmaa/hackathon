"""Tests for tactic_classifier.py — rules layer, offline LLM stand-in, and the
ensemble combiner. Runs offline (no key needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.tactic_classifier import classify, classify_rules
from config import TACTICS


def test_rules_catch_walk_away_threat():
    label, conf, _ = classify_rules("If you won't budge I'll just walk away and find another place.")
    assert label == "walk_away_threat"
    assert conf > 0


def test_rules_catch_comparables():
    label, _, _ = classify_rules("Similar units down the street are going for less.")
    assert label == "comparables"


def test_rules_catch_split_difference():
    label, _, _ = classify_rules("Let's just split the difference and be done.")
    assert label == "splitting_difference"


def test_rules_catch_deadline():
    label, _, _ = classify_rules("I need an answer by Friday, the offer expires then.")
    assert label == "deadline_pressure"


def test_rules_return_none_on_plain_number():
    label, conf, _ = classify_rules("I offer 17400.")
    assert label is None and conf == 0.0


def test_ensemble_always_returns_a_valid_label():
    for msg in ["I'll walk away.", "hmm let me think", "17400", "you seem fair"]:
        res = classify(msg)
        assert res.ensemble_label in TACTICS
        assert 0.0 <= res.ensemble_confidence <= 1.0


def test_ensemble_logs_both_labels_for_ablation():
    res = classify("Comparable places nearby are cheaper, and I might just walk.")
    # Both sub-classifier outputs are recorded separately (the ablation needs this).
    assert res.rule_label is not None
    assert res.llm_label in TACTICS
    assert res.source in ("rules", "llm")


def test_high_confidence_rule_wins_ensemble():
    res = classify("Take it or leave it, that's my final price.")
    assert res.ensemble_label == "anchoring"
    assert res.source == "rules"

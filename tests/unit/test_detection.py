import pytest

from odos.backend.detection import Baseline, DetectionSettings, evaluate, update

S = DetectionSettings(min_runs=5, ratio_threshold=3.0, deviation_k=4.0, min_waste_usd=1.0, alpha=0.2)


def build(costs):
    b = Baseline()
    for c in costs:
        v = evaluate(c, b, S)
        b = update(b, c, S, flagged=v.is_anomaly)
    return b


def test_no_flags_during_warm_up():
    b = build([1.0, 1.0])
    assert not evaluate(50.0, b, S).is_anomaly


def test_warm_up_baseline_is_plain_average():
    b = build([1.0, 2.0, 3.0])
    assert b.mean == pytest.approx(2.0)
    assert b.count == 3


def test_spike_is_flagged_with_waste_and_severity():
    b = build([1.0] * 10)
    v = evaluate(10.0, b, S)
    assert v.is_anomaly
    assert v.waste_usd == pytest.approx(9.0)
    assert v.severity == "CRITICAL"


def test_small_absolute_spikes_are_ignored():
    b = build([0.01] * 10)
    assert not evaluate(0.2, b, S).is_anomaly  # 20x, but only $0.19 extra


def test_noisy_queries_need_a_bigger_jump():
    noisy = build([2, 10, 3, 12, 2, 11, 3, 10, 2, 12])
    v = evaluate(3.2 * noisy.mean, noisy, S)
    assert not v.is_anomaly  # above 3x, but within normal swings


def test_spike_does_not_inflate_baseline():
    b = build([1.0] * 10)
    after = update(b, 100.0, S, flagged=True)
    assert after.mean < 1.5
    assert evaluate(10.0, after, S).is_anomaly  # the next spike is still caught


def test_settings_from_config_casts_types():
    s = DetectionSettings.from_config({"min_runs": "3", "ratio_threshold": 2, "unknown": 1})
    assert s.min_runs == 3 and s.ratio_threshold == 2.0

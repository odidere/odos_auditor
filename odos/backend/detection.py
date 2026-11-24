"""Cost anomaly detection (pure functions, no I/O).

Each query fingerprint keeps a smoothed baseline cost and a smoothed absolute
deviation. A run is flagged when its cost is above **both** ``ratio_threshold``
times the baseline **and** the baseline plus ``deviation_k`` typical deviations,
and the excess is at least ``min_waste_usd``. Requiring both keeps noisy queries
from alerting constantly while still catching big jumps in stable ones.

During warm-up (fewer than ``min_runs`` runs) nothing is flagged and the
baseline is a plain average. Flagged runs are capped before they update the
baseline, so one spike does not hide the next.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DetectionSettings:
    min_runs: int = 5
    ratio_threshold: float = 3.0
    deviation_k: float = 4.0
    min_waste_usd: float = 1.0
    alpha: float = 0.2

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any] | None) -> "DetectionSettings":
        cfg = cfg or {}
        fields = cls.__dataclass_fields__  # type: ignore[attr-defined]
        return cls(**{k: type(getattr(cls, k))(v) for k, v in cfg.items() if k in fields})


@dataclass(frozen=True)
class Baseline:
    mean: float = 0.0
    deviation: float = 0.0
    count: int = 0


@dataclass(frozen=True)
class Verdict:
    is_anomaly: bool
    threshold: float | None
    waste_usd: float
    ratio: float | None
    severity: str | None


def severity_for(ratio: float) -> str:
    if ratio >= 10:
        return "CRITICAL"
    if ratio >= 5:
        return "HIGH"
    return "MEDIUM"


def threshold_for(baseline: Baseline, settings: DetectionSettings) -> float:
    return max(baseline.mean * settings.ratio_threshold,
               baseline.mean + settings.deviation_k * baseline.deviation)


def evaluate(cost: float, baseline: Baseline, settings: DetectionSettings = DetectionSettings()) -> Verdict:
    if baseline.count < settings.min_runs or baseline.mean <= 0:
        return Verdict(False, None, 0.0, None, None)
    threshold = threshold_for(baseline, settings)
    waste = cost - baseline.mean
    ratio = cost / baseline.mean
    flagged = cost > threshold and waste >= settings.min_waste_usd
    return Verdict(flagged, threshold, waste if flagged else 0.0, ratio, severity_for(ratio) if flagged else None)


def update(baseline: Baseline, cost: float, settings: DetectionSettings = DetectionSettings(),
           flagged: bool = False) -> Baseline:
    if baseline.count == 0:
        return Baseline(mean=cost, deviation=0.0, count=1)
    observed = min(cost, threshold_for(baseline, settings)) if flagged else cost
    if baseline.count < settings.min_runs:
        n = baseline.count + 1
        mean = baseline.mean + (observed - baseline.mean) / n
        deviation = baseline.deviation + (abs(observed - baseline.mean) - baseline.deviation) / n
        return Baseline(mean, deviation, n)
    a = settings.alpha
    mean = a * observed + (1 - a) * baseline.mean
    deviation = a * abs(observed - baseline.mean) + (1 - a) * baseline.deviation
    return Baseline(mean, deviation, baseline.count + 1)

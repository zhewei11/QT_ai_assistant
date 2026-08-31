"""Interpretable 60-second RR-based arrhythmia screening.

The output is intended for screening and conversation context. It does not
replace ECG interpretation by a clinician and does not emit calibrated disease
probabilities.
"""

import math
import os

import numpy as np


BRADYCARDIA_BPM = float(os.getenv("ECG_BRADYCARDIA_BPM", "50"))
TACHYCARDIA_BPM = float(os.getenv("ECG_TACHYCARDIA_BPM", "100"))
IRREGULAR_SCORE_THRESHOLD = float(os.getenv("ECG_IRREGULAR_SCORE_THRESHOLD", "0.50"))
AF_PATTERN_SCORE_THRESHOLD = float(os.getenv("ECG_AF_PATTERN_SCORE_THRESHOLD", "0.68"))
PREMATURE_SCORE_THRESHOLD = float(os.getenv("ECG_PREMATURE_SCORE_THRESHOLD", "0.50"))
MIN_SIGNAL_QUALITY = float(os.getenv("ECG_MIN_SIGNAL_QUALITY", "0.50"))


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, float(value)))


def _scale(value, low, high):
    if high <= low:
        return 0.0
    return _clamp((float(value) - low) / (high - low))


def _sample_entropy(values, dimension=2, tolerance_ratio=0.2):
    series = np.asarray(values, dtype=np.float64)
    if series.size < dimension + 3:
        return 0.0
    tolerance = tolerance_ratio * float(np.std(series))
    if tolerance <= 0:
        return 0.0

    def count_matches(length):
        count = 0
        vectors = [series[index:index + length] for index in range(series.size - length + 1)]
        for left in range(len(vectors) - 1):
            for right in range(left + 1, len(vectors)):
                if np.max(np.abs(vectors[left] - vectors[right])) <= tolerance:
                    count += 1
        return count

    matches_m = count_matches(dimension)
    matches_m1 = count_matches(dimension + 1)
    if matches_m == 0 or matches_m1 == 0:
        return 2.5
    return float(-math.log(matches_m1 / matches_m))


def _normalized_shannon_entropy(values, bins=None):
    series = np.asarray(values, dtype=np.float64)
    if series.size < 3:
        return 0.0
    if bins is None:
        bins = max(4, min(12, int(round(math.sqrt(series.size)))))
    counts, _ = np.histogram(series, bins=bins)
    probabilities = counts[counts > 0].astype(np.float64)
    probabilities /= probabilities.sum()
    entropy = -float(np.sum(probabilities * np.log2(probabilities)))
    maximum = math.log2(bins)
    return entropy / maximum if maximum > 0 else 0.0


def _turning_point_ratio(values):
    series = np.asarray(values, dtype=np.float64)
    if series.size < 3:
        return 0.0
    center = series[1:-1]
    turning = ((center - series[:-2]) * (center - series[2:])) > 0
    return float(np.mean(turning))


def _premature_pattern_metrics(rr_ms):
    rr = np.asarray(rr_ms, dtype=np.float64)
    if rr.size < 5:
        return {
            "premature_pattern_count": 0,
            "premature_pattern_percent": 0.0,
            "isolated_rr_outlier_percent": 0.0,
        }

    premature = 0
    outliers = 0
    reference = float(np.median(rr))
    if reference <= 0:
        return {
            "premature_pattern_count": 0,
            "premature_pattern_percent": 0.0,
            "isolated_rr_outlier_percent": 0.0,
        }

    for index, interval in enumerate(rr):
        relative = interval / reference
        if relative < 0.8 or relative > 1.2:
            outliers += 1
        if index + 1 < rr.size:
            next_interval = rr[index + 1]
            pair_is_compensated = abs((interval + next_interval) - (2.0 * reference)) <= 0.25 * reference
            if relative < 0.8 and next_interval > 1.15 * reference and pair_is_compensated:
                premature += 1

    denominator = max(1, rr.size)
    return {
        "premature_pattern_count": int(premature),
        "premature_pattern_percent": round(premature / denominator * 100.0, 1),
        "isolated_rr_outlier_percent": round(outliers / denominator * 100.0, 1),
    }


def assess_signal_quality(samples, peak_indices, sample_rate):
    values = np.asarray(samples, dtype=np.float64)
    peaks = np.asarray(peak_indices, dtype=np.float64)
    duration = values.size / sample_rate if sample_rate > 0 else 0.0
    total_rr = max(0, peaks.size - 1)
    rr_ms = np.diff(peaks) / sample_rate * 1000.0 if total_rr else np.array([])
    physiological_rr = rr_ms[(rr_ms >= 300.0) & (rr_ms <= 2000.0)]
    rr_valid_ratio = physiological_rr.size / total_rr if total_rr else 0.0

    if values.size:
        robust_range = float(np.percentile(values, 95) - np.percentile(values, 5))
        finite_ratio = float(np.mean(np.isfinite(values)))
        centered = values - np.median(values)
        first_difference = np.diff(centered)
        noise_ratio = (
            float(np.median(np.abs(first_difference))) / max(float(np.median(np.abs(centered))), 1e-9)
            if first_difference.size else 0.0
        )
    else:
        robust_range = 0.0
        finite_ratio = 0.0
        noise_ratio = 0.0

    duration_score = _scale(duration, 20.0, 55.0)
    beat_score = _scale(peaks.size, 15.0, 35.0)
    rr_score = _scale(rr_valid_ratio, 0.65, 0.95)
    amplitude_score = 1.0 if robust_range > 1e-9 else 0.0
    noise_score = 1.0 - _scale(noise_ratio, 2.5, 8.0)
    quality_score = (
        0.25 * duration_score
        + 0.25 * beat_score
        + 0.30 * rr_score
        + 0.10 * amplitude_score
        + 0.10 * noise_score
    ) * finite_ratio

    if quality_score >= 0.75:
        quality_label = "good"
    elif quality_score >= 0.5:
        quality_label = "fair"
    else:
        quality_label = "poor"

    return {
        "score": round(_clamp(quality_score), 3),
        "label": quality_label,
        "measurement_seconds": round(duration, 1),
        "rr_valid_percent": round(rr_valid_ratio * 100.0, 1),
        "robust_amplitude_range": round(robust_range, 6),
        "noise_ratio": round(noise_ratio, 3),
    }


def analyze_arrhythmia(samples, peak_indices, sample_rate):
    peaks = np.asarray(peak_indices, dtype=np.float64)
    signal_quality = assess_signal_quality(samples, peaks, sample_rate)
    if peaks.size < 3 or sample_rate <= 0:
        return {
            "status": "insufficient_signal",
            "signal_quality": signal_quality,
            "features": {},
            "screening_scores": {},
            "rhythm_labels": ["insufficient_signal"],
        }

    all_rr = np.diff(peaks) / sample_rate * 1000.0
    valid_rr = all_rr[(all_rr >= 300.0) & (all_rr <= 2000.0)]
    if valid_rr.size < 8:
        return {
            "status": "insufficient_signal",
            "signal_quality": signal_quality,
            "features": {"valid_rr_count": int(valid_rr.size)},
            "screening_scores": {},
            "rhythm_labels": ["insufficient_signal"],
        }

    rr_diffs = np.diff(valid_rr)
    mean_rr = float(np.mean(valid_rr))
    median_rr = float(np.median(valid_rr))
    bpm = 60000.0 / median_rr
    sdnn = float(np.std(valid_rr))
    rmssd = float(np.sqrt(np.mean(rr_diffs ** 2))) if rr_diffs.size else 0.0
    pnn50 = float(np.mean(np.abs(rr_diffs) >= 50.0) * 100.0) if rr_diffs.size else 0.0
    prr30 = float(np.mean(np.abs(rr_diffs) >= 30.0) * 100.0) if rr_diffs.size else 0.0
    prr325 = (
        float(np.mean(np.abs(rr_diffs) >= (0.0325 * valid_rr[:-1])) * 100.0)
        if rr_diffs.size else 0.0
    )
    coefficient_variation = sdnn / mean_rr if mean_rr > 0 else 0.0
    turning_point_ratio = _turning_point_ratio(valid_rr)
    shannon_entropy = _normalized_shannon_entropy(valid_rr)
    sample_entropy = _sample_entropy(valid_rr)
    premature = _premature_pattern_metrics(valid_rr)

    irregularity_score = (
        0.25 * _scale(coefficient_variation, 0.05, 0.20)
        + 0.20 * _scale(prr30, 20.0, 70.0)
        + 0.20 * _scale(prr325, 20.0, 70.0)
        + 0.15 * _scale(turning_point_ratio, 0.45, 0.67)
        + 0.10 * _scale(shannon_entropy, 0.45, 0.90)
        + 0.10 * _scale(sample_entropy, 0.5, 1.8)
    )
    premature_score = _scale(premature["premature_pattern_percent"], 10.0, 35.0)
    af_pattern_score = irregularity_score * (1.0 - 0.45 * premature_score)
    rate_confidence = signal_quality["score"]

    labels = []
    if bpm < BRADYCARDIA_BPM:
        labels.append("bradycardia_pattern")
    elif bpm > TACHYCARDIA_BPM:
        labels.append("tachycardia_pattern")

    if premature_score >= PREMATURE_SCORE_THRESHOLD:
        labels.append("frequent_premature_pattern")
    if af_pattern_score >= AF_PATTERN_SCORE_THRESHOLD and signal_quality["score"] >= MIN_SIGNAL_QUALITY:
        labels.append("possible_af_pattern")
    elif irregularity_score >= IRREGULAR_SCORE_THRESHOLD:
        labels.append("irregular_rhythm_pattern")
    if not labels:
        labels.append("regular_rhythm_pattern")

    features = {
        "bpm": round(bpm, 1),
        "mean_rr_ms": round(mean_rr, 1),
        "median_rr_ms": round(median_rr, 1),
        "sdnn_ms": round(sdnn, 1),
        "rmssd_ms": round(rmssd, 1),
        "pnn50_percent": round(pnn50, 1),
        "prr30_percent": round(prr30, 1),
        "prr3_25_percent": round(prr325, 1),
        "rr_coefficient_of_variation": round(coefficient_variation, 4),
        "turning_point_ratio": round(turning_point_ratio, 4),
        "normalized_shannon_entropy": round(shannon_entropy, 4),
        "sample_entropy": round(sample_entropy, 4),
        "r_peak_count": int(peaks.size),
        "valid_rr_count": int(valid_rr.size),
    }
    features.update(premature)

    return {
        "status": "complete" if signal_quality["label"] != "poor" else "low_quality",
        "signal_quality": signal_quality,
        "features": features,
        "screening_scores": {
            "irregular_rhythm": round(_clamp(irregularity_score) * rate_confidence, 3),
            "possible_af_pattern": round(_clamp(af_pattern_score) * rate_confidence, 3),
            "premature_beat_pattern": round(_clamp(premature_score) * rate_confidence, 3),
        },
        "rhythm_labels": labels,
        "interpretation_notice": (
            "Scores are heuristic screening indicators derived from RR intervals. "
            "They are not calibrated disease probabilities and cannot confirm AF, PAC, or PVC without clinical ECG review."
        ),
    }

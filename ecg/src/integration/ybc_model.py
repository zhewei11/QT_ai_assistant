"""Optional YBC beat-classification arrhythmia screening.

The YBC model classifies individual beats from a two-channel input:
one 360-sample ECG window centered on an R peak, plus one RR-context channel.
Its output is a screening signal only; it is not a calibrated disease
probability and must not be presented as a diagnosis.
"""

from __future__ import annotations

import importlib.util
import math
import os
import time
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import signal


TARGET_SAMPLE_RATE = 360.0
WINDOW_SIZE = 360
HALF_WINDOW = WINDOW_SIZE // 2
LABELS = {
    0: "N",
    1: "S",
    2: "V",
    3: "F",
    4: "Q",
}
LABEL_DESCRIPTIONS = {
    "N": "normal_beat",
    "S": "supraventricular_ectopic_beat",
    "V": "ventricular_ectopic_beat",
    "F": "fusion_beat",
    "Q": "unknown_or_unclassifiable_beat",
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _round_dict(values: dict[str, float], digits: int = 1) -> dict[str, float]:
    return {key: round(float(value), digits) for key, value in values.items()}


def _load_ybc_inference_module():
    module_path = Path(__file__).resolve().parents[1] / "ybc" / "utils" / "inference.py"
    if not module_path.exists():
        raise FileNotFoundError(f"YBC inference module not found: {module_path}")

    spec = importlib.util.spec_from_file_location("qt_ai_ybc_inference", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load YBC inference module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resample_signal(samples, peak_indices, sample_rate):
    values = np.asarray(samples, dtype=np.float64)
    peaks = np.asarray(peak_indices, dtype=np.float64)
    if values.size == 0 or sample_rate <= 0:
        return values, np.asarray([], dtype=int)

    if abs(float(sample_rate) - TARGET_SAMPLE_RATE) < 0.001:
        return values, np.rint(peaks).astype(int)

    target_count = max(1, int(round(values.size * TARGET_SAMPLE_RATE / float(sample_rate))))
    resampled = signal.resample(values, target_count)
    peak_scale = TARGET_SAMPLE_RATE / float(sample_rate)
    resampled_peaks = np.rint(peaks * peak_scale).astype(int)
    resampled_peaks = resampled_peaks[(resampled_peaks >= 0) & (resampled_peaks < target_count)]
    return resampled, np.unique(resampled_peaks)


def _bandpass_filter(values):
    if values.size <= 771:
        return values
    taps = signal.firwin(257, [1.0, 40.0], pass_zero=False, fs=TARGET_SAMPLE_RATE)
    return signal.filtfilt(taps, 1.0, values)


def _zscore(values):
    mean = float(np.mean(values))
    standard_deviation = float(np.std(values))
    if not math.isfinite(standard_deviation) or standard_deviation < 1e-8:
        return np.zeros_like(values, dtype=np.float64)
    return (values - mean) / standard_deviation


def _relative_rr_channel(peaks, beat_index):
    if beat_index <= 0:
        return None

    rr_intervals = np.diff(peaks)
    if rr_intervals.size == 0 or beat_index - 1 >= rr_intervals.size:
        return None

    current_rr = float(rr_intervals[beat_index - 1])
    start = max(0, beat_index - 31)
    end = min(rr_intervals.size, beat_index + 30)
    local_rr = np.asarray(rr_intervals[start:end], dtype=np.float64)
    if local_rr.size == 0:
        return None

    if local_rr.size > 5:
        local_rr = np.sort(local_rr)[:-5]
    reference_rr = float(np.mean(local_rr)) if local_rr.size else 0.0
    if reference_rr <= 0:
        return 0.0
    return ((reference_rr - current_rr) / reference_rr) * 10.0


def _base_result(status, **extra):
    result = {
        "enabled": _env_bool("ECG_YBC_MODEL_ENABLED", False),
        "status": status,
        "model_name": "ybc_smallcnn_beat_classifier",
        "sample_rate_hz": TARGET_SAMPLE_RATE,
        "clinical_notice": (
            "YBC output is beat-level model screening. It is not a diagnosis "
            "and is not a calibrated disease probability."
        ),
    }
    result.update(extra)
    return result


def analyze_ybc_arrhythmia(samples, peak_indices, sample_rate):
    started_at = time.monotonic()
    if not _env_bool("ECG_YBC_MODEL_ENABLED", False):
        return _base_result("disabled")

    values = np.asarray(samples, dtype=np.float64)
    peaks = np.asarray(peak_indices, dtype=int)
    if values.size < int(sample_rate * 3) or peaks.size < 3:
        return _base_result(
            "insufficient_beats",
            beat_count=int(peaks.size),
            analyzed_beat_count=0,
        )

    try:
        inference_module = _load_ybc_inference_module()
    except (ImportError, ModuleNotFoundError, FileNotFoundError) as exc:
        return _base_result("dependency_missing", error=str(exc))
    except Exception as exc:
        return _base_result("model_load_error", error=str(exc))

    try:
        model_signal, model_peaks = _resample_signal(values, peaks, sample_rate)
        model_signal = _bandpass_filter(model_signal)
    except Exception as exc:
        return _base_result("preprocess_error", error=str(exc))

    counts: Counter[str] = Counter()
    confidence_sums: Counter[str] = Counter()
    analyzed = 0
    skipped = 0
    limited_out = 0

    try:
        batch_predict = getattr(inference_module, "batch_inference_with_probabilities", None)
        predict_with_probabilities = getattr(inference_module, "inference_with_probabilities", None)
        predict = getattr(inference_module, "inference")
        model_inputs = []
        for index, peak in enumerate(model_peaks):
            if peak < HALF_WINDOW or peak + HALF_WINDOW > model_signal.size:
                skipped += 1
                continue

            relative_rr = _relative_rr_channel(model_peaks, index)
            if relative_rr is None:
                skipped += 1
                continue

            segment = model_signal[peak - HALF_WINDOW: peak + HALF_WINDOW]
            signal_channel = _zscore(segment * 1000.0)
            rr_channel = np.full((WINDOW_SIZE,), relative_rr, dtype=np.float64)
            combined_input = np.stack([signal_channel, rr_channel], axis=0)
            model_inputs.append(combined_input)

        max_beats = max(0, _env_int("ECG_YBC_MAX_BEATS", 80))
        if max_beats and len(model_inputs) > max_beats:
            selected_indices = np.linspace(0, len(model_inputs) - 1, num=max_beats, dtype=int)
            selected_set = set(int(index) for index in selected_indices)
            limited_out = len(model_inputs) - len(selected_set)
            model_inputs = [model_inputs[index] for index in sorted(selected_set)]

        timeout_seconds = max(0.0, _env_float("ECG_YBC_TIMEOUT_SECONDS", 5.0))
        batch_size = max(1, _env_int("ECG_YBC_BATCH_SIZE", 32))

        def add_prediction(class_id, probability):
            nonlocal analyzed
            label = LABELS.get(int(class_id), f"class_{int(class_id)}")
            counts[label] += 1
            if probability is not None and math.isfinite(float(probability)):
                confidence_sums[label] += float(probability)
            analyzed += 1

        if batch_predict and model_inputs:
            for start in range(0, len(model_inputs), batch_size):
                if timeout_seconds and time.monotonic() - started_at > timeout_seconds:
                    break
                batch = np.asarray(model_inputs[start:start + batch_size], dtype=np.float32)
                predictions, probabilities_batch = batch_predict(batch)
                for class_id, probabilities in zip(predictions, probabilities_batch):
                    probability = probabilities[class_id] if class_id < len(probabilities) else None
                    add_prediction(class_id, probability)
        else:
            for combined_input in model_inputs:
                if timeout_seconds and time.monotonic() - started_at > timeout_seconds:
                    break

                if predict_with_probabilities:
                    class_id, probabilities = predict_with_probabilities(combined_input)
                    probability = probabilities[class_id] if class_id < len(probabilities) else None
                else:
                    class_id = predict(combined_input)
                    probability = None
                add_prediction(class_id, probability)
    except Exception as exc:
        return _base_result(
            "model_inference_error",
            beat_count=int(model_peaks.size),
            analyzed_beat_count=int(analyzed),
            skipped_beat_count=int(skipped),
            limited_out_beat_count=int(limited_out),
            inference_seconds=round(time.monotonic() - started_at, 3),
            error=str(exc),
        )

    if analyzed == 0:
        return _base_result(
            "insufficient_beats",
            beat_count=int(model_peaks.size),
            analyzed_beat_count=0,
            skipped_beat_count=int(skipped),
            limited_out_beat_count=int(limited_out),
            inference_seconds=round(time.monotonic() - started_at, 3),
        )

    class_counts = {label: int(counts.get(label, 0)) for label in LABELS.values()}
    for label in counts:
        class_counts.setdefault(label, int(counts[label]))
    class_percentages = _round_dict({label: count / analyzed * 100.0 for label, count in class_counts.items()})
    mean_confidence = _round_dict(
        {
            label: confidence_sums[label] / counts[label]
            for label in confidence_sums
            if counts[label] > 0
        },
        digits=3,
    )

    abnormal_labels = [label for label in class_counts if label != "N" and class_counts[label] > 0]
    abnormal_beat_count = sum(class_counts[label] for label in abnormal_labels)
    abnormal_percent = abnormal_beat_count / analyzed * 100.0
    percent_threshold = float(os.getenv("ECG_YBC_ABNORMAL_PERCENT_THRESHOLD", "10.0"))
    minimum_abnormal_beats = int(os.getenv("ECG_YBC_MIN_ABNORMAL_BEATS", "2"))
    arrhythmia_detected = (
        abnormal_beat_count >= minimum_abnormal_beats
        and abnormal_percent >= percent_threshold
    )

    return _base_result(
        "complete",
        beat_count=int(model_peaks.size),
        analyzed_beat_count=int(analyzed),
        skipped_beat_count=int(skipped),
        limited_out_beat_count=int(limited_out),
        inference_seconds=round(time.monotonic() - started_at, 3),
        batch_size=_env_int("ECG_YBC_BATCH_SIZE", 32),
        max_beats=_env_int("ECG_YBC_MAX_BEATS", 80),
        class_counts=class_counts,
        class_percentages=class_percentages,
        mean_confidence=mean_confidence,
        label_descriptions=LABEL_DESCRIPTIONS,
        abnormal_labels=abnormal_labels,
        abnormal_beat_count=int(abnormal_beat_count),
        abnormal_beat_percent=round(float(abnormal_percent), 1),
        arrhythmia_detected=bool(arrhythmia_detected),
        thresholds={
            "abnormal_beat_percent": percent_threshold,
            "minimum_abnormal_beats": minimum_abnormal_beats,
        },
    )

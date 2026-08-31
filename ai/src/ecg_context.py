import json
import os
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_RESULT_PATH = Path(__file__).resolve().parents[2] / "runtime" / "ecg_latest.json"
DEFAULT_FACE_MEMORY_PATH = Path(__file__).resolve().parents[2] / "runtime" / "face_memory.json"


def _result_path():
    return Path(os.getenv("ECG_RESULT_FILE", str(DEFAULT_RESULT_PATH))).expanduser()


def _face_memory_path():
    path = Path(os.getenv("FACE_MEMORY_FILE", str(DEFAULT_FACE_MEMORY_PATH))).expanduser()
    if not path.is_absolute():
        path = DEFAULT_FACE_MEMORY_PATH.parents[1] / path
    return path


def _measurement_age_seconds(measured_at):
    if not measured_at:
        return None
    try:
        measured = datetime.fromisoformat(str(measured_at).replace("Z", "+00:00"))
        if measured.tzinfo is None:
            measured = measured.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - measured).total_seconds())
    except (TypeError, ValueError):
        return None


def _load_json(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _with_measurement_age(payload):
    payload["age_seconds"] = _measurement_age_seconds(payload.get("measured_at"))
    max_age_seconds = float(os.getenv("ECG_MAX_AGE_SECONDS", "21600"))
    payload["is_stale"] = (
        payload["age_seconds"] is None
        or payload["age_seconds"] > max_age_seconds
    )
    return payload


def _current_person(face_memory):
    if not isinstance(face_memory, dict):
        return None
    person_id = face_memory.get("current_person_id")
    if not person_id:
        return None

    max_age_seconds = float(os.getenv("FACE_CURRENT_TTL_SECONDS", "30"))
    people = face_memory.get("people", [])
    for person in people:
        if person.get("person_id") != person_id:
            continue
        age_seconds = _measurement_age_seconds(person.get("last_seen"))
        if age_seconds is not None and age_seconds <= max_age_seconds:
            person = dict(person)
            person["age_seconds"] = age_seconds
            return person
    return None


def _person_memory_summary(face_memory, current_person=None):
    people = face_memory.get("people", []) if isinstance(face_memory, dict) else []
    return {
        "current_person_id": current_person.get("person_id") if current_person else None,
        "known_people_count": len(people),
        "max_people": int(os.getenv("FACE_MEMORY_MAX_PEOPLE", "4")),
        "face_memory_file": str(_face_memory_path()),
    }


def _informational_measurement(status, face_memory, current_person=None):
    payload = {
        "status": status,
        "measured_at": None,
        "metrics": {},
        "is_stale": False,
        "source": "face_memory",
        "person_memory": _person_memory_summary(face_memory, current_person),
    }
    if current_person:
        payload["person_id"] = current_person.get("person_id")
        payload["person_identity"] = {
            "person_id": current_person.get("person_id"),
            "face_tracking_id": current_person.get("face_tracking_id"),
            "last_seen": current_person.get("last_seen"),
        }
    return payload


def _measurement_for_person(face_memory, current_person):
    measurement = current_person.get("latest_ecg_measurement")
    if not isinstance(measurement, dict):
        return _informational_measurement("no_person_measurement", face_memory, current_person)

    measurement = _with_measurement_age(dict(measurement))
    measurement["result_file"] = str(_result_path())
    measurement["person_memory"] = _person_memory_summary(face_memory, current_person)
    measurement.setdefault("person_id", current_person.get("person_id"))
    if measurement.get("is_stale"):
        return {
            "status": "person_measurement_stale",
            "measured_at": measurement.get("measured_at"),
            "age_seconds": measurement.get("age_seconds"),
            "is_stale": False,
            "metrics": {},
            "person_id": current_person.get("person_id"),
            "person_memory": _person_memory_summary(face_memory, current_person),
        }
    return measurement


def load_ecg_measurement():
    face_memory_enabled = os.getenv("FACE_MEMORY_ENABLED", "true").lower() == "true"
    face_memory = _load_json(_face_memory_path()) if face_memory_enabled else {}
    if face_memory_enabled:
        current_person = _current_person(face_memory)
        if current_person:
            return _measurement_for_person(face_memory, current_person)
        return _informational_measurement("no_current_face", face_memory)

    path = _result_path()
    payload = _load_json(path)
    if not payload:
        return {}
    _with_measurement_age(payload)
    payload["result_file"] = str(path)
    return payload


def format_ecg_context(measurement):
    if not isinstance(measurement, dict) or not measurement:
        return "No ECG measurement is available for this session."

    if measurement.get("status") == "no_current_face":
        return "Face memory is enabled, but no current face slot is visible. Do not reuse another person's ECG."
    if measurement.get("status") == "no_person_measurement":
        person_id = measurement.get("person_id", "unknown")
        return f"The current face slot {person_id} does not have an ECG measurement yet."
    if measurement.get("status") == "person_measurement_stale":
        age_seconds = measurement.get("age_seconds")
        return f"The current face slot has an ECG measurement, but it is stale. age_seconds={round(age_seconds, 1) if age_seconds is not None else 'unknown'}."

    metrics = measurement.get("metrics") or {}
    analysis = measurement.get("arrhythmia_analysis") or {}
    model_arrhythmia = measurement.get("model_arrhythmia") or {}
    quality = analysis.get("signal_quality") or {}
    features = analysis.get("features") or {}
    scores = analysis.get("screening_scores") or {}
    parts = [
        f"status={measurement.get('status', 'unknown')}",
        f"measured_at={measurement.get('measured_at', 'unknown')}",
        f"measurement_duration_seconds={measurement.get('measurement_duration_seconds', 0)}",
    ]
    for key in ("bpm", "rmssd_ms", "pnn50_percent", "arrhythmia_indicator_percent", "r_peak_count"):
        if key in metrics:
            parts.append(f"{key}={metrics[key]}")
    if measurement.get("person_id"):
        parts.append(f"person_id={measurement.get('person_id')}")
    if analysis:
        parts.append(f"signal_quality={quality.get('label', 'unknown')}:{quality.get('score', 0)}")
        parts.append(f"rhythm_labels={json.dumps(analysis.get('rhythm_labels', []), ensure_ascii=False)}")
        parts.append(f"arrhythmia_screening_scores={json.dumps(scores, ensure_ascii=False)}")
        for key in (
            "sdnn_ms",
            "prr30_percent",
            "prr3_25_percent",
            "turning_point_ratio",
            "normalized_shannon_entropy",
            "sample_entropy",
            "premature_pattern_percent",
        ):
            if key in features:
                parts.append(f"{key}={features[key]}")
    if model_arrhythmia:
        parts.append(f"ybc_model_status={model_arrhythmia.get('status', 'unknown')}")
        if model_arrhythmia.get("status") == "complete":
            parts.append(f"ybc_model_arrhythmia_detected={bool(model_arrhythmia.get('arrhythmia_detected'))}")
            parts.append(f"ybc_model_abnormal_beat_percent={model_arrhythmia.get('abnormal_beat_percent', 0)}")
            parts.append(f"ybc_model_class_counts={json.dumps(model_arrhythmia.get('class_counts', {}), ensure_ascii=False)}")
            parts.append(f"ybc_model_abnormal_labels={json.dumps(model_arrhythmia.get('abnormal_labels', []), ensure_ascii=False)}")
    age_seconds = measurement.get("age_seconds")
    if age_seconds is not None:
        parts.append(f"measurement_age_seconds={round(age_seconds, 1)}")
    parts.append(f"is_stale={bool(measurement.get('is_stale', True))}")
    parts.append(
        "safety=screening_only; arrhythmia_indicator_percent is RR variability, not disease probability; "
        "screening scores are heuristic and not calibrated probabilities; "
        "ybc model output is beat-level screening and not a disease probability; "
        "do not diagnose from this measurement"
    )
    return "; ".join(parts)

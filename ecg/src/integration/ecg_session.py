#!/usr/bin/env python3
"""Run one Firebase-backed ECG measurement session and persist an AI-safe snapshot."""

import argparse
import json
import math
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import signal

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arrhythmia import analyze_arrhythmia
from ybc_model import analyze_ybc_arrhythmia


DEFAULT_DATABASE_URL = "https://ecg-monitor-bf64d-default-rtdb.firebaseio.com"
DEFAULT_DEVICE_PATH = "devices/yuguard_01"
DEFAULT_SAMPLE_RATE = 375.0
DEFAULT_SIGNAL_WAIT_TIMEOUT = 120.0
DEFAULT_STREAM_GAP_TIMEOUT = 5.0
DEFAULT_FACE_MEMORY_PATH = Path(__file__).resolve().parents[3] / "runtime" / "face_memory.json"
ECG_GATE_MIN_SECONDS = float(os.getenv("ECG_GATE_MIN_SECONDS", "8.0"))
ECG_GATE_MIN_PEAKS = int(os.getenv("ECG_GATE_MIN_PEAKS", "6"))
ECG_GATE_MIN_VALID_RR = int(os.getenv("ECG_GATE_MIN_VALID_RR", "5"))
ECG_GATE_MIN_RR_VALID_PERCENT = float(os.getenv("ECG_GATE_MIN_RR_VALID_PERCENT", "80.0"))
ECG_GATE_MIN_BPM = float(os.getenv("ECG_GATE_MIN_BPM", "40.0"))
ECG_GATE_MAX_BPM = float(os.getenv("ECG_GATE_MAX_BPM", "180.0"))
ECG_GATE_MIN_ROBUST_RANGE = float(os.getenv("ECG_GATE_MIN_ROBUST_RANGE", "0.01"))
ECG_GATE_MAX_NOISE_RATIO = float(os.getenv("ECG_GATE_MAX_NOISE_RATIO", "2.5"))


def firebase_url(database_url, path):
    return f"{database_url.rstrip('/')}/{path.strip('/')}.json"


def firebase_write(database_url, path, value, timeout=10):
    request = urllib.request.Request(
        firebase_url(database_url, path),
        data=json.dumps(value).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def firebase_read(database_url, path, timeout=10):
    try:
        with urllib.request.urlopen(firebase_url(database_url, path), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _extract_stream_packet(payload):
    if not isinstance(payload, dict):
        return [], None
    data = payload.get("data")
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        batch = data.get("batch") or data.get("stream")
        if isinstance(batch, list):
            session_id = data.get("session_id")
            sequence = data.get("sequence")
            packet_id = None
            if session_id is not None and sequence is not None:
                packet_id = f"{session_id}:{sequence}"
            return batch, packet_id
    return [], None


def _extract_batch(payload):
    return _extract_stream_packet(payload)[0]


class FirebaseECGCollector:
    def __init__(self, database_url, stream_path):
        self.database_url = database_url
        self.stream_path = stream_path
        self.samples = []
        self.ready = threading.Event()
        self.data_received = threading.Event()
        self.collecting = threading.Event()
        self.stop_requested = threading.Event()
        self.error = None
        self.last_data_monotonic = 0.0
        self._recent_packet_ids = deque(maxlen=2048)
        self._recent_packet_id_set = set()
        self._lock = threading.Lock()

    def start(self):
        thread = threading.Thread(target=self._run, name="firebase_ecg_stream", daemon=True)
        thread.start()
        return thread

    def _run(self):
        url = firebase_url(self.database_url, self.stream_path)
        while not self.stop_requested.is_set():
            try:
                request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
                with urllib.request.urlopen(request, timeout=8) as response:
                    self.ready.set()
                    event_data = None
                    while not self.stop_requested.is_set():
                        line = response.readline().decode("utf-8").strip()
                        if line.startswith("data:"):
                            event_data = line[5:].strip()
                        elif not line and event_data:
                            payload = json.loads(event_data)
                            event_data = None
                            if not self.collecting.is_set():
                                continue
                            batch, packet_id = _extract_stream_packet(payload)
                            if packet_id and packet_id in self._recent_packet_id_set:
                                continue
                            clean_batch = []
                            for value in batch:
                                try:
                                    sample = float(value)
                                    if math.isfinite(sample):
                                        clean_batch.append(sample)
                                except (TypeError, ValueError):
                                    continue
                            if clean_batch:
                                if packet_id:
                                    if len(self._recent_packet_ids) == self._recent_packet_ids.maxlen:
                                        expired = self._recent_packet_ids.popleft()
                                        self._recent_packet_id_set.discard(expired)
                                    self._recent_packet_ids.append(packet_id)
                                    self._recent_packet_id_set.add(packet_id)
                                with self._lock:
                                    self.samples.extend(clean_batch)
                                self.last_data_monotonic = time.monotonic()
                                self.data_received.set()
            except (OSError, ValueError, socket.timeout, urllib.error.URLError) as exc:
                self.error = str(exc)
                self.ready.set()
                if not self.stop_requested.wait(0.5):
                    continue

    def snapshot(self):
        with self._lock:
            return list(self.samples)

    def clear(self):
        with self._lock:
            self.samples.clear()
        self.data_received.clear()
        self.last_data_monotonic = time.monotonic()


def heartbeat_gate_details(samples, sample_rate):
    """Require stable human-like ECG before timing a session."""
    details = {
        "valid": False,
        "sample_count": len(samples),
        "seconds": round(len(samples) / sample_rate, 1) if sample_rate > 0 else 0.0,
        "r_peak_count": 0,
        "valid_rr_count": 0,
        "rr_valid_percent": 0.0,
        "bpm": None,
        "robust_amplitude_range": 0.0,
        "noise_ratio": 0.0,
        "reason": "",
    }
    if sample_rate <= 0 or len(samples) < int(sample_rate * ECG_GATE_MIN_SECONDS):
        details["reason"] = f"need_at_least_{ECG_GATE_MIN_SECONDS:g}s_samples"
        return details

    recent_window = samples[-int(sample_rate * max(ECG_GATE_MIN_SECONDS, 10.0)):]
    values = np.asarray(recent_window, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size < int(sample_rate * ECG_GATE_MIN_SECONDS):
        details["reason"] = "insufficient_finite_samples"
        return details
    robust_range = float(np.percentile(finite, 95) - np.percentile(finite, 5))
    centered = finite - np.median(finite)
    first_difference = np.diff(centered)
    noise_ratio = (
        float(np.median(np.abs(first_difference))) / max(float(np.median(np.abs(centered))), 1e-9)
        if first_difference.size else 0.0
    )
    details["robust_amplitude_range"] = round(robust_range, 6)
    details["noise_ratio"] = round(noise_ratio, 3)
    if robust_range < ECG_GATE_MIN_ROBUST_RANGE:
        details["reason"] = "amplitude_too_low"
        return details
    if noise_ratio > ECG_GATE_MAX_NOISE_RATIO:
        details["reason"] = "signal_too_noisy"
        return details

    peaks = detect_r_peaks(recent_window, sample_rate)
    details["r_peak_count"] = int(peaks.size)
    if peaks.size < ECG_GATE_MIN_PEAKS:
        details["reason"] = "not_enough_r_peaks"
        return details

    metrics = calculate_metrics(peaks, sample_rate)
    if not metrics:
        details["reason"] = "no_plausible_rr_intervals"
        return details
    details["valid_rr_count"] = int(metrics.get("valid_rr_count", 0))
    details["bpm"] = metrics.get("bpm")
    total_rr = max(1, peaks.size - 1)
    details["rr_valid_percent"] = round(details["valid_rr_count"] / total_rr * 100.0, 1)
    if details["valid_rr_count"] < ECG_GATE_MIN_VALID_RR:
        details["reason"] = "not_enough_valid_rr"
        return details
    if details["rr_valid_percent"] < ECG_GATE_MIN_RR_VALID_PERCENT:
        details["reason"] = "rr_valid_percent_too_low"
        return details
    details["valid"] = ECG_GATE_MIN_BPM <= metrics["bpm"] <= ECG_GATE_MAX_BPM
    details["reason"] = "ok" if details["valid"] else "bpm_out_of_range"
    return details


def has_valid_heartbeat(samples, sample_rate):
    return heartbeat_gate_details(samples, sample_rate)["valid"]


def detect_r_peaks(samples, sample_rate):
    values = np.asarray(samples, dtype=np.float64)
    if values.size < int(sample_rate * 3):
        return np.array([], dtype=int)

    values = signal.detrend(values)
    differentiated = np.diff(values, prepend=values[0])
    squared = differentiated ** 2
    window_size = max(1, int(sample_rate * 0.08))
    integrated = np.convolve(squared, np.ones(window_size) / window_size, mode="same")
    finite = integrated[np.isfinite(integrated)]
    if finite.size == 0:
        return np.array([], dtype=int)

    reference = float(np.percentile(finite, 99))
    if reference <= 0:
        return np.array([], dtype=int)

    candidates, _ = signal.find_peaks(
        integrated,
        height=reference * 0.35,
        distance=max(1, int(sample_rate * 0.3)),
    )
    search_radius = max(1, int(sample_rate * 0.06))
    refined = []
    for candidate in candidates:
        start = max(0, candidate - search_radius)
        end = min(values.size, candidate + search_radius + 1)
        if start < end:
            refined.append(start + int(np.argmax(values[start:end])))
    return np.unique(np.asarray(refined, dtype=int))


def calculate_metrics(peak_indices, sample_rate):
    peaks = np.asarray(peak_indices, dtype=np.float64)
    if peaks.size < 3:
        return None

    rr_ms = np.diff(peaks) / sample_rate * 1000.0
    valid_rr = rr_ms[(rr_ms >= 300.0) & (rr_ms <= 2000.0)]
    if valid_rr.size < 2:
        return None

    recent_rr = valid_rr[-5:]
    bpm = 60000.0 / float(np.median(recent_rr))
    rr_diffs = np.diff(valid_rr)
    rmssd = float(np.sqrt(np.mean(rr_diffs ** 2))) if rr_diffs.size else 0.0
    pnn50 = float(np.mean(np.abs(rr_diffs) > 50.0) * 100.0) if rr_diffs.size else 0.0
    irregularity = float(np.std(valid_rr) / np.mean(valid_rr) * 100.0)
    return {
        "bpm": round(bpm, 1),
        "rmssd_ms": round(rmssd, 1),
        "pnn50_percent": round(pnn50, 1),
        "arrhythmia_indicator_percent": round(irregularity, 1),
        "r_peak_count": int(peaks.size),
        "valid_rr_count": int(valid_rr.size),
    }


def write_snapshot(path, payload):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(output_path)


def _workspace_path(path):
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parents[3] / resolved
    return resolved


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _read_json_file(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json_file(path, payload):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(output_path)


def current_person_identity(face_memory_file, current_ttl_seconds):
    memory = _read_json_file(_workspace_path(face_memory_file))
    person_id = memory.get("current_person_id")
    if not person_id:
        return None
    for person in memory.get("people", []):
        if person.get("person_id") != person_id:
            continue
        last_seen = _parse_iso_datetime(person.get("last_seen"))
        if not last_seen:
            return None
        age_seconds = max(0.0, (datetime.now(timezone.utc) - last_seen).total_seconds())
        if age_seconds > current_ttl_seconds:
            return None
        return {
            "person_id": person.get("person_id"),
            "face_tracking_id": person.get("face_tracking_id"),
            "last_seen": person.get("last_seen"),
            "age_seconds": round(age_seconds, 1),
        }
    return None


def attach_person_identity(snapshot, person_identity):
    if person_identity:
        snapshot["person_id"] = person_identity.get("person_id")
        snapshot["person_identity"] = dict(person_identity)
    return snapshot


def update_person_ecg_measurement(face_memory_file, snapshot):
    person_id = snapshot.get("person_id")
    if not person_id:
        return False
    memory_path = _workspace_path(face_memory_file)
    memory = _read_json_file(memory_path)
    people = memory.get("people", [])
    if not isinstance(people, list):
        return False
    for person in people:
        if person.get("person_id") != person_id:
            continue
        person["latest_ecg_measurement_id"] = snapshot.get("measurement_id")
        person["latest_ecg_measured_at"] = snapshot.get("measured_at")
        person["latest_ecg_measurement"] = snapshot
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json_file(memory_path, memory)
        return True
    return False


def format_person_identity(person_identity):
    if not person_identity:
        return "none"
    return (
        f"person_id={person_identity.get('person_id')} "
        f"tracking_id={person_identity.get('face_tracking_id')} "
        f"last_seen={person_identity.get('last_seen')} "
        f"age={person_identity.get('age_seconds')}s"
    )


def run_session(args):
    stream_path = f"{args.device_path}/stream"
    command_path = f"{args.device_path}/command"
    analysis_path = f"{args.device_path}/analysis"
    measurement_id = str(uuid.uuid4())
    person_identity = current_person_identity(args.face_memory_file, args.face_current_ttl)
    print("=" * 48, flush=True)
    print("[ECG] measurement session requested", flush=True)
    print(f"[ECG] measurement_id={measurement_id}", flush=True)
    print(f"[ECG] device_path={args.device_path}", flush=True)
    print(f"[ECG] stream_path={stream_path}", flush=True)
    print(f"[ECG] analysis_path={analysis_path}", flush=True)
    print(f"[ECG] result_file={args.output}", flush=True)
    print(f"[ECG] face_memory_file={args.face_memory_file}", flush=True)
    print(f"[ECG] current_face={format_person_identity(person_identity)}", flush=True)
    if not person_identity:
        print("[ECG] 注意：目前沒有可用臉孔槽，完成後只會寫入全域結果，不會綁定到 person slot。", flush=True)
    print("=" * 48, flush=True)
    waiting_snapshot = {
        "schema_version": 2,
        "measurement_id": measurement_id,
        "status": "waiting_device",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {},
        "source": "firebase_bluetooth_bridge",
    }
    attach_person_identity(waiting_snapshot, person_identity)
    write_snapshot(args.output, waiting_snapshot)
    collector = FirebaseECGCollector(args.database_url, stream_path)
    thread = collector.start()
    collector.ready.wait(timeout=10)

    print("[ECG] 等待藍牙裝置與穩定 ECG 訊號...", flush=True)
    waiting_snapshot["measured_at"] = datetime.now(timezone.utc).isoformat()
    write_snapshot(args.output, waiting_snapshot)
    try:
        firebase_write(args.database_url, analysis_path, waiting_snapshot)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"[ECG] 無法同步量測狀態到 Firebase: {exc}", flush=True)
    firebase_write(args.database_url, command_path, "reset")
    time.sleep(0.5)
    firebase_write(args.database_url, stream_path, None)
    collector.clear()
    collector.collecting.set()
    firebase_write(args.database_url, command_path, "start")

    signal_wait_started = time.monotonic()
    waiting_signal_published = False
    last_wait_debug = 0.0
    while time.monotonic() - signal_wait_started < args.signal_wait_timeout:
        samples = collector.snapshot()
        if collector.data_received.is_set() and not waiting_signal_published:
            waiting_snapshot["status"] = "waiting_signal"
            waiting_snapshot["measured_at"] = datetime.now(timezone.utc).isoformat()
            write_snapshot(args.output, waiting_snapshot)
            try:
                firebase_write(args.database_url, analysis_path, waiting_snapshot)
            except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
                print(f"[ECG] 無法同步心跳偵測狀態: {exc}", flush=True)
            print("[ECG] 已連上資料流，正在確認 ECG 品質、R 波與 RR 間期...", flush=True)
            waiting_signal_published = True

        gate_details = heartbeat_gate_details(samples, args.sample_rate)
        if gate_details["valid"]:
            break
        if args.wait_debug_interval > 0 and time.monotonic() - last_wait_debug >= args.wait_debug_interval:
            print(
                "[ECG] 等待穩定 ECG: "
                f"samples={gate_details['sample_count']} "
                f"seconds={gate_details['seconds']} "
                f"peaks={gate_details['r_peak_count']} "
                f"valid_rr={gate_details['valid_rr_count']} "
                f"rr_valid={gate_details['rr_valid_percent']}% "
                f"bpm={gate_details['bpm']} "
                f"range={gate_details['robust_amplitude_range']} "
                f"noise={gate_details['noise_ratio']} "
                f"reason={gate_details['reason']} "
                f"collector_error={collector.error or 'none'}",
                flush=True,
            )
            last_wait_debug = time.monotonic()
        time.sleep(0.25)
    else:
        firebase_write(args.database_url, command_path, "stop")
        collector.collecting.clear()
        collector.stop_requested.set()
        thread.join(timeout=2)
        failed_snapshot = {
            **waiting_snapshot,
            "status": "signal_timeout",
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "sample_count": len(collector.snapshot()),
            "collector_error": collector.error,
        }
        write_snapshot(args.output, failed_snapshot)
        updated_person = update_person_ecg_measurement(args.face_memory_file, failed_snapshot)
        print(f"[ECG] face_memory_update={updated_person} status=signal_timeout", flush=True)
        try:
            firebase_write(args.database_url, analysis_path, failed_snapshot)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError):
            pass
        print("[ECG] 等待逾時：未偵測到可用的人體心跳訊號。", flush=True)
        return 2

    collector.clear()
    measuring_snapshot = {
        **waiting_snapshot,
        "status": "measuring",
        "measured_at": datetime.now(timezone.utc).isoformat(),
    }
    write_snapshot(args.output, measuring_snapshot)
    try:
        firebase_write(args.database_url, analysis_path, measuring_snapshot)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"[ECG] 無法同步正式量測狀態: {exc}", flush=True)

    print(f"[ECG] 已確認穩定 ECG 訊號，開始 {args.duration:.0f} 秒量測。", flush=True)
    started_at = time.monotonic()

    stream_lost = False
    while True:
        elapsed = time.monotonic() - started_at
        if elapsed >= args.duration:
            break
        if time.monotonic() - collector.last_data_monotonic > args.stream_gap_timeout:
            stream_lost = True
            break
        remaining = max(0, math.ceil(args.duration - elapsed))
        print(f"\r[ECG] 量測中，剩餘 {remaining:02d} 秒", end="", flush=True)
        time.sleep(min(1.0, args.duration - elapsed))

    print("", flush=True)
    firebase_write(args.database_url, command_path, "stop")
    collector.collecting.clear()
    collector.stop_requested.set()
    thread.join(timeout=2)

    samples = collector.snapshot()
    if stream_lost:
        failed_snapshot = {
            **measuring_snapshot,
            "status": "stream_lost",
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "measurement_duration_seconds": round(len(samples) / args.sample_rate, 1),
            "sample_count": len(samples),
            "collector_error": collector.error,
        }
        write_snapshot(args.output, failed_snapshot)
        updated_person = update_person_ecg_measurement(args.face_memory_file, failed_snapshot)
        print(f"[ECG] face_memory_update={updated_person} status=stream_lost", flush=True)
        try:
            firebase_write(args.database_url, analysis_path, failed_snapshot)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError):
            pass
        print("[ECG] 量測中斷：ECG 資料流已停止。", flush=True)
        return 2

    peaks = detect_r_peaks(samples, args.sample_rate)
    metrics = calculate_metrics(peaks, args.sample_rate)
    arrhythmia_analysis = analyze_arrhythmia(samples, peaks, args.sample_rate)
    model_arrhythmia = analyze_ybc_arrhythmia(samples, peaks, args.sample_rate)
    measured_seconds = len(samples) / args.sample_rate if args.sample_rate > 0 else 0.0

    snapshot = {
        "schema_version": 2,
        "measurement_id": measurement_id,
        "status": arrhythmia_analysis.get("status", "insufficient_signal"),
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "measurement_duration_seconds": round(measured_seconds, 1),
        "requested_duration_seconds": args.duration,
        "sample_rate_hz": args.sample_rate,
        "sample_count": len(samples),
        "metrics": metrics or {},
        "arrhythmia_analysis": arrhythmia_analysis,
        "model_arrhythmia": model_arrhythmia,
        "waveform_summary": {
            "minimum": round(float(np.min(samples)), 6) if samples else None,
            "maximum": round(float(np.max(samples)), 6) if samples else None,
            "mean": round(float(np.mean(samples)), 6) if samples else None,
            "standard_deviation": round(float(np.std(samples)), 6) if samples else None,
        },
        "clinical_notice": (
            "This is a screening measurement, not a diagnosis. "
            "The arrhythmia indicator is RR-interval variability and is not a disease probability. "
            "The YBC model output is beat-level screening and is not a diagnosis."
        ),
        "source": "firebase_bluetooth_bridge",
        "collector_error": collector.error,
    }
    attach_person_identity(snapshot, person_identity)
    write_snapshot(args.output, snapshot)
    updated_person = update_person_ecg_measurement(args.face_memory_file, snapshot)
    print(
        f"[ECG] face_memory_update={updated_person} "
        f"person_id={snapshot.get('person_id', '(none)')} "
        f"measurement_id={measurement_id}",
        flush=True,
    )
    try:
        firebase_write(args.database_url, analysis_path, snapshot)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"[ECG] 無法回寫分析結果到 Firebase: {exc}", flush=True)

    if metrics and arrhythmia_analysis.get("status") in ("complete", "low_quality"):
        rhythm_labels = ", ".join(arrhythmia_analysis.get("rhythm_labels", []))
        scores = arrhythmia_analysis.get("screening_scores", {})
        print(
            "[ECG] 完成: "
            f"BPM={metrics['bpm']} | RMSSD={metrics['rmssd_ms']}ms | "
            f"pNN50={metrics['pnn50_percent']}% | "
            f"節律={rhythm_labels} | "
            f"不規則篩檢分數={scores.get('irregular_rhythm', 0)}",
            flush=True,
        )
        if model_arrhythmia.get("status") == "complete":
            print(
                "[ECG] YBC模型篩檢: "
                f"arrhythmia_detected={model_arrhythmia.get('arrhythmia_detected')} | "
                f"異常搏動={model_arrhythmia.get('abnormal_beat_percent')}% | "
                f"analyzed={model_arrhythmia.get('analyzed_beat_count')} | "
                f"time={model_arrhythmia.get('inference_seconds')}s | "
                f"counts={model_arrhythmia.get('class_counts')}",
                flush=True,
            )
        elif model_arrhythmia.get("status") not in ("disabled", None):
            print(
                "[ECG] YBC模型篩檢未完成: "
                f"status={model_arrhythmia.get('status')} "
                f"error={model_arrhythmia.get('error', 'none')}",
                flush=True,
            )
        return 0

    print(f"[ECG] 訊號不足，僅收到 {len(samples)} 個樣本。", flush=True)
    return 2


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=float(os.getenv("ECG_MEASUREMENT_SECONDS", "60")))
    parser.add_argument("--sample-rate", type=float, default=float(os.getenv("ECG_SAMPLE_RATE_HZ", str(DEFAULT_SAMPLE_RATE))))
    parser.add_argument(
        "--signal-wait-timeout",
        type=float,
        default=float(os.getenv("ECG_SIGNAL_WAIT_TIMEOUT_SECONDS", str(DEFAULT_SIGNAL_WAIT_TIMEOUT))),
    )
    parser.add_argument(
        "--stream-gap-timeout",
        type=float,
        default=float(os.getenv("ECG_STREAM_GAP_TIMEOUT_SECONDS", str(DEFAULT_STREAM_GAP_TIMEOUT))),
    )
    parser.add_argument("--database-url", default=os.getenv("ECG_FIREBASE_DATABASE_URL", DEFAULT_DATABASE_URL))
    parser.add_argument("--device-path", default=os.getenv("ECG_FIREBASE_DEVICE_PATH", DEFAULT_DEVICE_PATH))
    parser.add_argument("--output", default=os.getenv("ECG_RESULT_FILE", "runtime/ecg_latest.json"))
    parser.add_argument("--face-memory-file", default=os.getenv("FACE_MEMORY_FILE", str(DEFAULT_FACE_MEMORY_PATH)))
    parser.add_argument(
        "--wait-debug-interval",
        type=float,
        default=float(os.getenv("ECG_WAIT_DEBUG_INTERVAL", "3")),
    )
    parser.add_argument(
        "--face-current-ttl",
        type=float,
        default=float(os.getenv("FACE_CURRENT_TTL_SECONDS", "30")),
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run_session(parse_args()))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"[ECG] 量測失敗: {exc}", flush=True)
        raise SystemExit(1)

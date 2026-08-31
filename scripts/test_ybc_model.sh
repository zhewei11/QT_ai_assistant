#!/bin/bash
set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="$WORKSPACE_DIR/config/ecg_integration.env"
CONFIG_EXAMPLE="$WORKSPACE_DIR/config/ecg_integration.env.example"

if [ -f "$CONFIG_FILE" ]; then
    set -a
    source "$CONFIG_FILE"
    set +a
elif [ -f "$CONFIG_EXAMPLE" ]; then
    set -a
    source "$CONFIG_EXAMPLE"
    set +a
fi

ECG_PYTHON="${ECG_PYTHON:-$WORKSPACE_DIR/ecg/.venv/bin/python}"
if [ ! -x "$ECG_PYTHON" ]; then
    ECG_PYTHON="python3"
fi

export ECG_YBC_MODEL_ENABLED=true
export ECG_YBC_MAX_BEATS="${ECG_YBC_MAX_BEATS:-16}"
export ECG_YBC_BATCH_SIZE="${ECG_YBC_BATCH_SIZE:-8}"
export ECG_YBC_TIMEOUT_SECONDS="${ECG_YBC_TIMEOUT_SECONDS:-20}"

echo "========================================="
echo " YBC ECG model smoke test"
echo "========================================="
echo "python=$ECG_PYTHON"
echo "enabled=$ECG_YBC_MODEL_ENABLED"
echo "max_beats=$ECG_YBC_MAX_BEATS"
echo "batch_size=$ECG_YBC_BATCH_SIZE"
echo "timeout=$ECG_YBC_TIMEOUT_SECONDS"
echo "========================================="

"$ECG_PYTHON" - "$WORKSPACE_DIR" <<'PY'
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
module_path = workspace / "ecg" / "src" / "integration" / "ecg_session.py"
weight_path = workspace / "ecg" / "src" / "ybc" / "weight" / "icentia_mitbih_ds1_finetuned_73_93.pt"

print(f"module={module_path}")
print(f"weight={weight_path} exists={weight_path.exists()} size={weight_path.stat().st_size if weight_path.exists() else 0}")

try:
    import numpy as np
    print(f"numpy={np.__version__}")
except Exception as exc:
    print(f"numpy_error={exc!r}")
    raise

try:
    import scipy
    print(f"scipy={scipy.__version__}")
except Exception as exc:
    print(f"scipy_error={exc!r}")
    raise

try:
    import torch
    print(f"torch={torch.__version__}")
except Exception as exc:
    print(f"torch_error={exc!r}")

spec = importlib.util.spec_from_file_location("ecg_session", module_path)
ecg_session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecg_session)

sample_rate = 375.0
duration = 20.0
time_axis = np.arange(int(duration * sample_rate)) / sample_rate
samples = 0.01 * np.sin(2 * np.pi * 1.2 * time_axis)
peaks = []

for second in range(1, 19):
    center = int(round(second * sample_rate))
    peaks.append(center)
    for offset in range(-5, 6):
        index = center + offset
        if 0 <= index < samples.size:
            samples[index] += math.exp(-((offset / 2.2) ** 2))

result = ecg_session.analyze_ybc_arrhythmia(samples, np.asarray(peaks), sample_rate)
print("result=" + json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

if result.get("status") == "complete":
    print("[YBC] OK: model loaded and inference completed.")
    raise SystemExit(0)

print(f"[YBC] NOT_READY: status={result.get('status')} error={result.get('error', 'none')}")
raise SystemExit(2)
PY

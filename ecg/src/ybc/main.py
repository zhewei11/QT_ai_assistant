import os

# Fix for the Keras/LSTM loading error in ecg2rr
os.environ["TF_USE_LEGACY_KERAS"] = "1"

import sys
import time
import asyncio
import numpy as np
import re
import shutil
from pathlib import Path
from scipy import stats, signal

# Import custom objects for Keras legacy loading before importing detector
import tensorflow as tf
try:
    from tensorflow.keras.layers import LSTM, Bidirectional
    # This helps ecg2rr locate the LSTM class when loading its .h5 model
    tf.keras.utils.get_custom_objects().update({'LSTM': LSTM, 'Bidirectional': Bidirectional})
except ImportError:
    pass

from utils.load_file import load_file
from utils.inference import inference
from utils.save_beat import save_beat
from ecg2rr import detector

# ---------------------------- Filter Design -----------------------------
def apply_fir_filter(sig, fs=360.0, lowcut=1.0, highcut=40.0, numtaps=257):
    """
    Apply a 256-tap (numtaps=257 for odd symmetry) FIR bandpass filter.
    """
    # Design FIR filter using window method
    taps = signal.firwin(numtaps, [lowcut, highcut], pass_zero=False, fs=fs)
    # Using filtfilt for zero-phase shift
    filtered_sig = signal.filtfilt(taps, 1.0, sig)
    return filtered_sig

# ---------------------------- Parameter Setting -----------------------------
window_size = 360
Fs = 360

if len(sys.argv) < 2:
    print("Usage: python main.py <directory_path>")
    sys.exit(1)

mypath = sys.argv[1]
print("=========")
print("sys.argv[0]: main.py", sys.argv[0])
print("sys.argv[1]: directory", sys.argv[1])
print("=========")

def find_csv_files_os(directory_path):
    csv_files = []
    if not os.path.exists(directory_path):
        return csv_files
    all_entries = os.listdir(directory_path)
    for entry in all_entries:
        if entry.lower().endswith('.csv'):
            full_path = os.path.join(directory_path, entry)
            csv_files.append(full_path)
    return csv_files

csv_files = find_csv_files_os(mypath)
print("csv files = ", csv_files)

for csv_file in csv_files:
    match = re.search(r"(\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})", csv_file)
    dt_str = match.group(1) if match else "unknown_datetime"
    date_match = re.search(r"(\d{4}_\d{2}_\d{2})", csv_file)
    dt_ymd_str = date_match.group(1) if date_match else "unknown_datetime"
    
    output_dir = os.path.join(mypath, dt_ymd_str)
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, f"mark_{dt_str}.csv")
    output_txt = os.path.join(output_dir, f"summary_{dt_str}.txt")
    
    # Load signal
    print("Load_file: ", csv_file)
    sig_raw = load_file(csv_file)
    if sig_raw is None or len(sig_raw) == 0:
        print(f"Failed to load {csv_file}")
        continue
    
    # --- FIX: Check signal length for filtfilt padlen requirement ---
    # filtfilt requires len(sig) > 3 * (numtaps - 1). For 257 taps, this is 768-771.
    if len(sig_raw) <= 771:
        print(f"Signal too short ({len(sig_raw)} samples) for FIR filtering. Skipping...")
        continue

    # Apply FIR Filter (1.0 - 40.0 Hz)
    print("Applying 256-tap FIR Filter...")
    sig = apply_fir_filter(sig_raw, fs=Fs, lowcut=1.0, highcut=40.0)
    
    # ---------------------------- R Peak Detection Prep -----------------------------
    # Goal: Use raw data for detection, but perform thresholding on filtered signal
    sig_det_input = sig_raw.copy()
    
    # Mask regions to zero if filtered signal amplitude is outlier (<1mV or >3mV)
    threshold_low = 0.1
    threshold_high = 3.0
    check_window = 360 # 1 second chunks
    
    for start_idx in range(0, len(sig), check_window):
        end_idx = min(start_idx + check_window, len(sig))
        # Use 'sig' (filtered) for thresholding logic
        chunk_filtered = sig[start_idx:end_idx]
        if len(chunk_filtered) > 0:
            amplitude = np.max(chunk_filtered) - np.min(chunk_filtered)
            if amplitude < threshold_low or amplitude > threshold_high:
                # Zero out 'sig_det_input' (raw) for detection
                sig_det_input[start_idx:end_idx] = 0

    # R peak detection using the thresholded signal
    try:
        dt = detector.ECG_detector(sampling_rate=360, stride=250, threshold=0.05)
        peak, probs = dt.find_peaks(sig_det_input)
    except Exception as e:
        print(f"Error in R-peak detection: {e}")
        continue

    print("Initial peak number = ", len(peak))
    if len(peak) == 0:
        print("No peaks detected in this file.")
        continue
        
    peak = dt.remove_close(peaks=peak, peak_probs=probs, threshold_ms=200)
    
    # Basic metrics
    len_sec = len(sig) / 360.0
    bpm = (len(peak) / len_sec) * 60.0 if len_sec > 0 else 0
    print("bpm = ", bpm)
    
    if bpm > 140:
        print(f"BPM {bpm:.2f} too high, skipping...")
        continue
    
    # Move original processed file
    if len(sig) > 1080000:
        try:
            shutil.move(csv_file, output_dir)
        except Exception as e:
            print(f"Could not move file: {e}")

    # --------------------------------- Inference --------------------------------
    start = time.time()
    counts = {0:0, 1:0, 2:0, 3:0, 4:0} # N, S, V, F, Q
    pred = np.zeros((len(peak), 1))
    
    rr_intervals = np.diff(peak)
    
    print(f"Starting inference for {len(peak)} beats...")
    for i in range(len(peak)):
        if peak[i] < 180 or peak[i] + 180 > len(sig):
            continue

        # Prepare Signal Channel (Z-score normalized)
        segment = sig[peak[i]-180 : peak[i]+180]
        sig_zscore = stats.zscore(segment * 1000)

        # Calculate Relative RR (IR)
        if i == 0:
            continue
        
        IA = rr_intervals[i-1]
        start_win = max(0, i - 31) 
        end_win = min(len(rr_intervals), i + 30)
        local_rr_window = rr_intervals[start_win:end_win]
        
        # Remove 20 largest intervals before calculating mean
        if len(local_rr_window) > 5:
            sorted_window = np.sort(local_rr_window)
            filtered_window = sorted_window[:-5]
#            filtered_window = sorted_window
            IN = np.mean(filtered_window)
        else:
            IN = np.mean(local_rr_window)
        
        # IR = (IN - IA) / IN * s (where s=10)
        IR = ((IN - IA) / IN) * 10 if IN != 0 else 0
        
        # Create 2-channel input (2, 360)
        rr_channel = np.full((360,), IR)
        combined_input = np.stack([sig_zscore, rr_channel], axis=0)

        # PyTorch Inference
        res = inference(combined_input)
        pred[i] = res
        counts[res] = counts.get(res, 0) + 1
        
        if i % 500 == 0 and i > 0:
            print(f"Progress: {i}/{len(peak)} beats processed...")

    end = time.time()
    print(f"Execution time: {end - start:.2f} s")
    
    print('======================= Statistic =======================')
    for k in sorted(counts.keys()):
        label = {0:'N', 1:'S', 2:'V', 3:'F', 4:'Q'}.get(k, f"Class {k}")
        print(f"{label} : {counts[k]}")
    print("total samples :", len(sig))
    print('======================= End of Statistic =======================')
    
    # Save results
    save_beat(peak, pred, output_file)
    
    with open(output_txt, 'w') as f:
        f.write('======================= Statistic =======================\n')
        for k in sorted(counts.keys()):
            label = {0:'N', 1:'S', 2:'V', 3:'F', 4:'Q'}.get(k, f"Class {k}")
            f.write(f"{label} : {counts[k]}\n")
        f.write(f"total samples : {len(sig)}\n")
        f.write('======================= End of Statistic =======================\n')
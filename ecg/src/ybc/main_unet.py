import os
import sys
import time
import asyncio
import numpy as np
import re
import shutil
from pathlib import Path
from scipy import stats, signal

import torch
import torch.nn as nn
import torch.nn.functional as F

from utils.load_file import load_file
from utils.inference import inference
from utils.save_beat import save_beat

# ============================================================================
# PyTorch U-Net R-Peak Detector Architecture
# ============================================================================
class ConvBlock(nn.Module):
    """
    Standard 1D Conv-BN-ReLU block.
    Uses padding='same' to ensure the sequence length doesn't change 
    regardless of even or odd kernel sizes (like 6, 9).
    """
    def __init__(self, in_channels, out_channels, kernel_size):
        super().__init__()
        self.conv = nn.Conv1d(
            in_channels, 
            out_channels, 
            kernel_size, 
            stride=1, 
            padding='same', 
            bias=False
        )
        self.bn = nn.BatchNorm1d(out_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.relu(self.bn(self.conv(x)))

class ECG_UNet_Figure(nn.Module):
    """
    A 1D CNN model based on the paper's architecture diagram, but with
    ALL SKIP CONNECTIONS REMOVED.
    - Parameter count is kept under 50,000.
    - Encoder Kernel Sizes: 9, 9, 6, 6, 3, 3.
    - Channels: 16 -> 16 -> 32 -> 32 -> 64 -> 64.
    - Decoder uses pointwise (k=1) convolutions.
    """
    def __init__(self, in_channels=1, out_channels=1):
        super().__init__()

        # --- Encoder (Downsampling Path) ---
        self.enc1 = ConvBlock(in_channels, 16, kernel_size=9)
        self.pool1 = nn.MaxPool1d(kernel_size=2, stride=2)
        
        self.enc2 = ConvBlock(16, 16, kernel_size=9)
        self.pool2 = nn.MaxPool1d(kernel_size=2, stride=2)
        
        self.enc3 = ConvBlock(16, 32, kernel_size=6)
        self.pool3 = nn.MaxPool1d(kernel_size=2, stride=2)
        
        self.enc4 = ConvBlock(32, 32, kernel_size=6)
        self.pool4 = nn.MaxPool1d(kernel_size=2, stride=2)
        
        self.enc5 = ConvBlock(32, 64, kernel_size=3)
        self.pool5 = nn.MaxPool1d(kernel_size=2, stride=2)
        
        # --- Bottleneck ---
        self.bottle = ConvBlock(64, 64, kernel_size=3)
        
        # --- Decoder (Upsampling Path) ---
        self.dec1 = ConvBlock(64, 32, kernel_size=1)
        self.dec2 = ConvBlock(32, 32, kernel_size=1)
        self.dec3 = ConvBlock(32, 16, kernel_size=1)
        self.dec4 = ConvBlock(16, 16, kernel_size=1)
        self.dec5 = ConvBlock(16, 16, kernel_size=1)
        
        self.out_conv = nn.Conv1d(16, out_channels, kernel_size=1)

    def forward(self, x):
        # --- Encoder ---
        e1 = self.enc1(x)                   
        p1 = self.pool1(e1)                 
        e2 = self.enc2(p1)                  
        p2 = self.pool2(e2)                 
        e3 = self.enc3(p2)                  
        p3 = self.pool3(e3)                 
        e4 = self.enc4(p3)                  
        p4 = self.pool4(e4)                 
        e5 = self.enc5(p4)                  
        p5 = self.pool5(e5)                 
        
        # --- Bottleneck ---
        b = self.bottle(p5)                 
        
        # --- Decoder ---
        u1 = F.interpolate(b, size=e5.shape[-1], mode='nearest')
        d1 = self.dec1(u1) 
        u2 = F.interpolate(d1, size=e4.shape[-1], mode='nearest')
        d2 = self.dec2(u2)
        u3 = F.interpolate(d2, size=e3.shape[-1], mode='nearest')
        d3 = self.dec3(u3)
        u4 = F.interpolate(d3, size=e2.shape[-1], mode='nearest')
        d4 = self.dec4(u4)
        u5 = F.interpolate(d4, size=e1.shape[-1], mode='nearest')
        d5 = self.dec5(u5)
        
        logits = self.out_conv(d5)
        return logits

# ============================================================================
# Initialize Environment & Models
# ============================================================================
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Load U-Net Model
rpeak_model_path = Path(__file__).parent / "weight" / "icentia_unet_rpeak_wo_skip.pt"
rpeak_model = ECG_UNet_Figure(in_channels=1, out_channels=1)

if rpeak_model_path.exists():
    rpeak_model.load_state_dict(torch.load(rpeak_model_path, map_location=device))
    print(f"Loaded U-Net R-peak model from {rpeak_model_path}")
else:
    print(f"WARNING: U-Net R-peak model weights not found at {rpeak_model_path}")

rpeak_model.to(device)
rpeak_model.eval()

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
    
    # Check signal length for filtfilt padlen requirement
    if len(sig_raw) <= 771:
        print(f"Signal too short ({len(sig_raw)} samples) for FIR filtering. Skipping...")
        continue

    # Apply FIR Filter (1.0 - 40.0 Hz)
    print("Applying 256-tap FIR Filter...")
    sig = apply_fir_filter(sig_raw, fs=Fs, lowcut=1.0, highcut=40.0)
    
    # ---------------------------- R Peak Detection Prep -----------------------------
    sig_det_input = sig_raw.copy()
    
    # Mask regions to zero if filtered signal amplitude is outlier (<0.1mV or >3mV)
    threshold_low = 0.1
    threshold_high = 3.0
    check_window = 360 # 1 second chunks
    
    for start_idx in range(0, len(sig), check_window):
        end_idx = min(start_idx + check_window, len(sig))
        chunk_filtered = sig[start_idx:end_idx]
        if len(chunk_filtered) > 0:
            amplitude = np.max(chunk_filtered) - np.min(chunk_filtered)
            if amplitude < threshold_low or amplitude > threshold_high:
                sig_det_input[start_idx:end_idx] = 0

    # ---------------------------- U-Net R-Peak Detection ----------------------------
    if np.std(sig_det_input) == 0:
        print("Signal is completely flat after masking. Skipping...")
        continue
        
    chunk_size = 1800 # 5s exactly
    overlap = 1080     # 1s overlap
    stride = chunk_size - overlap # 1440 samples stride
    batch_size = 128
    
    orig_len = len(sig_det_input)
    
    # Pad signal so that the sliding window covers the entire length
    if orig_len <= chunk_size:
        pad_len = chunk_size - orig_len
    else:
        remainder = (orig_len - chunk_size) % stride
        pad_len = (stride - remainder) % stride
        
    sig_det_padded = np.pad(sig_det_input, (0, pad_len), mode='constant', constant_values=0)
    padded_len = len(sig_det_padded)
    
    num_chunks = (padded_len - chunk_size) // stride + 1
    
    # Extract overlapping chunks
    chunks = np.zeros((num_chunks, chunk_size), dtype=np.float32)
    for i in range(num_chunks):
        start_idx = i * stride
        chunks[i] = sig_det_padded[start_idx : start_idx + chunk_size]
    
    # Min-Max Normalization PER CHUNK (between 0 and 1)
    chunk_min = np.min(chunks, axis=1, keepdims=True)
    chunk_max = np.max(chunks, axis=1, keepdims=True)
    diff = chunk_max - chunk_min
    diff[diff == 0] = 1.0 # Prevent division by zero
    
    chunks_norm = (chunks - chunk_min) / diff
    chunks_norm = chunks_norm.reshape(num_chunks, 1, chunk_size) # (N, 1, 1800)
    
    all_probs = []
    
    try:
        with torch.no_grad():
            for b_idx in range(0, num_chunks, batch_size):
                batch = chunks_norm[b_idx : b_idx + batch_size]
                batch_tensor = torch.from_numpy(batch).float().to(device)
                logits = rpeak_model(batch_tensor)
                p = torch.sigmoid(logits).squeeze(1).cpu().numpy() # shape: (B, 1800)
                
                # Safeguard shape for single-batch concatenations
                if p.ndim == 1:
                    p = np.expand_dims(p, axis=0)
                    
                all_probs.append(p)
                
        chunk_probs = np.concatenate(all_probs, axis=0) # shape: (num_chunks, 1800)
        
        # Reconstruct full probabilities using average blending for overlapped regions
        full_probs = np.zeros(padded_len, dtype=np.float32)
        overlap_counts = np.zeros(padded_len, dtype=np.float32)
        
        for i in range(num_chunks):
            start_idx = i * stride
            full_probs[start_idx : start_idx + chunk_size] += chunk_probs[i]
            overlap_counts[start_idx : start_idx + chunk_size] += 1.0
            
        full_probs /= overlap_counts
        probs = full_probs[:orig_len] # Unpad back to original length
        
        # Find continuous active regions
        active_indices = np.where(probs > 0.5)[0]
        raw_peaks = []
        
        if len(active_indices) > 0:
            # Split indices into contiguous clusters
            split_points = np.where(np.diff(active_indices) > 1)[0] + 1
            clusters = np.split(active_indices, split_points)
            
            for cluster in clusters:
                # Expand search window to +/- 18 samples (~50ms) to cover wide VPCs
                center = cluster[len(cluster) // 2]
                c_start = max(0, center - 18)
                c_end = min(orig_len - 1, center + 18)
                
                # Use the filtered signal (sig) to find the true extremum
                local_seg = sig[c_start : c_end + 1]
                if len(local_seg) == 0:
                    raw_peaks.append(center)
                    continue
                
                # Find points where derivative is 0 (local extrema)
                dy = np.diff(local_seg)
                extrema = []
                for j in range(1, len(dy)):
                    # A sign change or a flat spot indicates derivative = 0
                    if dy[j-1] * dy[j] <= 0:
                        extrema.append(j)
                        
                if len(extrema) > 0:
                    extrema_values = local_seg[extrema]
                    # If multiple derivative = 0 points are found, use the one with highest value
                    best_ext_idx = np.argmax(extrema_values)
                    refined_peak = c_start + extrema[best_ext_idx]
                else:
                    # Fallback to the highest value in the window
                    refined_peak = c_start + np.argmax(local_seg)
                    
                raw_peaks.append(refined_peak)
                
        # Enforce minimum distance between peaks (~200ms -> 72 samples)
        peak = []
        for p in raw_peaks:
            if not peak or (p - peak[-1]) >= 72:
                peak.append(p)
                
        peak = np.array(peak)
        
    except Exception as e:
        print(f"Error in U-Net R-peak detection: {e}")
        continue

    print("Initial peak number = ", len(peak))
    if len(peak) == 0:
        print("No peaks detected in this file.")
        continue
        
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

        # Prepare Signal Channel (Z-score normalized for classification)
        segment = sig[peak[i]-180 : peak[i]+180]
        sig_zscore = stats.zscore(segment * 1000)

        # Calculate Relative RR (IR)
        if i == 0:
            continue
        
        IA = rr_intervals[i-1]
        start_win = max(0, i - 31) 
        end_win = min(len(rr_intervals), i + 30)
        local_rr_window = rr_intervals[start_win:end_win]
        
        # Remove 5 largest intervals before calculating mean
        if len(local_rr_window) > 5:
            sorted_window = np.sort(local_rr_window)
            filtered_window = sorted_window[:-5]
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
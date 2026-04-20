import asyncio
import websockets
import json
import csv
import os
import threading
import http.server
import socketserver
import sys
import platform

# Include the SDM_DEMO_GUI directory for calculation logic
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
SDM_PATH = os.path.realpath(os.path.join(DIRECTORY, '../SDM_DEMO_GUI'))
sys.path.insert(0, SDM_PATH)

import numpy as np
from scipy import signal

# --- Clinical Implementation Fallbacks (Self-Contained) ---

def find_r_peaks_robust(raw_view, fs):
    """
    Exact implementation of Peal Detection from SDM_DEMO_GUI/ecg_gui_arrhythmia.py.
    Adopted here to ensure clinical parity and fix UI dots.
    """
    if len(raw_view) < fs * 1.0: # Need enough data for MWA
        return np.array([])

    # --- Standard Pan-Tompkins Chain from Demo ---
    diff_ecg = np.diff(raw_view)
    squared_ecg = diff_ecg ** 2
    
    # 80ms window as in ecg_gui_arrhythmia.py
    window_size = int(fs * 0.08) 
    mwa_ecg = np.convolve(squared_ecg, np.ones(window_size)/window_size, mode='same')
    
    # Normalization
    mwa_max = np.max(mwa_ecg)
    if mwa_max > 0:
        mwa_ecg = mwa_ecg / mwa_max
    
    # Peak detection (height 0.35, distance 300ms)
    feature_indices, _ = signal.find_peaks(mwa_ecg, height=0.35, distance=int(fs * 0.3))
    
    # Local Refinement (50ms search as in demo)
    refined_peaks = []
    search_offset = int(fs * 0.05) 
    
    for p in feature_indices:
        start = max(0, p - search_offset)
        end = min(len(raw_view), p + search_offset)
        if start < end:
            # Use argmax on raw signal (as in demo)
            real_peak = start + np.argmax(raw_view[start:end])
            refined_peaks.append(real_peak)
    
    return np.unique(np.array(refined_peaks))

def calculate_metrics_local(peak_indices, fs):
    """ Local implementation of Clinical metrics (BPM, HRV). """
    if len(peak_indices) < 2:
        return {"bpm": 0, "rmssd": 0, "pnn50": 0, "arrhythmia_ratio": 0}
    
    # Refractory period check on indices before interval calculation
    cleaned_peaks = []
    for p in peak_indices:
        if not cleaned_peaks or (p - cleaned_peaks[-1]) > int(fs * 0.25):
            cleaned_peaks.append(p)
    
    if len(cleaned_peaks) < 2:
        return {"bpm": 0, "rmssd": 0, "pnn50": 0, "arrhythmia_ratio": 0}

    rr_intervals = np.diff(cleaned_peaks) / fs * 1000.0 # ms
    bpm = 60000.0 / np.mean(rr_intervals)
    rr_diffs = np.diff(rr_intervals)
    rmssd = np.sqrt(np.mean(rr_diffs**2))
    nn50 = np.sum(np.abs(rr_diffs) > 50.0)
    pnn50 = (nn50 / len(rr_diffs)) * 100.0
    arr_ratio = (np.std(rr_intervals) / np.mean(rr_intervals)) * 100.0
    
    return {
        "bpm": int(bpm),
        "rmssd": round(rmssd, 1),
        "pnn50": round(pnn50, 1),
        "arrhythmia_ratio": round(arr_ratio, 1)
    }

# Dynamic Imports with local Fallbacks
try:
    import quant
    quant_func = quant.quant
except (ImportError, AttributeError):
    def quant_func(val, b, f):
        i_bits = b - f - 1
        pos = 2**i_bits - 2**(-f)
        neg = -2**i_bits
        v = np.clip(np.floor(val * (2**f)) * (2**-f), neg, pos)
        return v, val - v

try:
    import filter
    filter_func = filter.filter
except (ImportError, AttributeError):
    def filter_func(a, comp, fir):
        # Basic CIC/FIR chain fallback
        y1 = np.cumsum(a)
        y2 = y1[::64]
        y3 = np.diff(y2, prepend=0)
        y4 = signal.lfilter(comp, [1.0], y3)
        y5 = signal.lfilter(fir, [1.0], y4)
        q, _ = quant_func(y5, 16, 14)
        return q, 375

# Hardware Connection Logic
HARDWARE_READY = False
try:
    import spi_receive
    # [MONKEY-PATCH] Support Mac hardware without changing SDM files
    if platform.system() == 'Darwin':
        print(f"[BOOT] Mac identified. Overriding COM11 with /dev/tty.usbserial")
        spi_receive.COM_PORT = '/dev/tty.usbserial'
    HARDWARE_READY = True
except ImportError:
    print(f"[BOOT] Notice: Hardware modules not found. Using local simulation.")
    pass

PORT_HTTP = 8080
PORT_WS = 8000
DATA_FILE = os.path.normpath(os.path.join(DIRECTORY, "../../data/10sec_ecg_output.csv"))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

def start_http_server():
    with ReuseTCPServer(("", PORT_HTTP), Handler) as httpd:
        httpd.serve_forever()

async def hardware_stream(websocket):
    """ Hardware pipeline hooked directly into the Web UI. """
    print("[SERVER] Attempting to connect to true ESP32 hardware...")
    
    try:
        stream = spi_receive.SerialStreaming()
        if not stream.connect():
            return False
    except:
        return False
        
    print("[SUCCESS] ESP32 SPI Pipeline activated!")
    
    # Coefficients from SDM directory
    try:
        comp_coef = np.genfromtxt(os.path.join(SDM_PATH, 'filter_coefficient/coef2.dat')).flatten()
        fir_coef = np.genfromtxt(os.path.join(SDM_PATH, 'filter_coefficient/coef_fir_v2.dat')).flatten()
    except:
        comp_coef = np.ones(10)
        fir_coef = np.ones(10)

    fs_mid = 375
    sos_band = signal.butter(3, [1.0, 35], fs=fs_mid, btype='band', output='sos')
    zi_band = signal.sosfilt_zi(sos_band)
        
    try:
        fs_web = 187.5
        
        while True:
            raw_bits = stream.get_chunk()
            if raw_bits is not None:
                input_bits = raw_bits.astype(np.float64).flatten()
                fir_out, _ = filter_func(input_bits, comp_coef, fir_coef)
                final_ecg, zi_band = signal.sosfilt(sos_band, fir_out, zi=zi_band)
                
                # Decimate to 187.5Hz for web display
                q_value, _ = quant_func(final_ecg[::2], 16, 14)
                
                # Only send raw waveform; frontend handles peak detection
                await websocket.send(json.dumps({"batch": q_value.tolist()}))
            await asyncio.sleep(0.001)
    except websockets.exceptions.ConnectionClosed:
        print("[SERVER] UI disconnected.")
    finally:
        stream.close()
    return True

async def csv_simulation_stream(websocket):
    """ Standalone CSV simulation. Sends raw waveform only; frontend handles peaks. """
    print("[WARNING] Hardware not found. Engaging SDM CSV Mode...")
    
    raw_amplitudes = []
    dfactor = 128
    try:
        with open(DATA_FILE, 'r') as f:
            reader = csv.reader(f)
            next(reader)
            for i, row in enumerate(reader):
                if i % dfactor == 0:
                    raw_amplitudes.append(float(row[1]))
    except Exception as e:
        print(f"[ERROR] CSV load failed ({e}), using sine wave fallback.")
        raw_amplitudes = np.sin(np.linspace(0, 50, 1500)).tolist()

    q_value, _ = quant_func(np.array(raw_amplitudes), 16, 14)
    q_list = q_value.tolist()
    points_per_frame = 4
    idx = 0
    total = len(q_list)

    try:
        while True:
            end_idx = min(idx + points_per_frame, total)
            batch = q_list[idx:end_idx]
            if batch:
                # Only send raw waveform; frontend handles peak detection
                await websocket.send(json.dumps({"batch": batch}))
            idx += points_per_frame
            if idx >= total:
                idx = 0
            await asyncio.sleep(0.016)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[ERROR] Simulation error: {e}")

async def ecg_stream(websocket):
    print("==================================================")
    print(">>> Web UI Connected! Negotiating Pipeline... <<<")
    
    is_hardware = False
    if HARDWARE_READY:
        is_hardware = await hardware_stream(websocket)
        
    if not is_hardware:
        await csv_simulation_stream(websocket)

async def main():
    print(f"==================================================")
    print(f" Starting QTrobot DUAL-MODE ECG Server ")
    print(f"==================================================")
    
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    
    async with websockets.serve(ecg_stream, "0.0.0.0", PORT_WS):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down streaming servers.")

import asyncio
import websockets
import json
import csv
import os
import threading
import http.server
import socketserver
import sys
# Include the upper directories so Python can find the user's modules
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(DIRECTORY, '..'))

import numpy as np
from scipy import signal
import quant

HARDWARE_READY = False
try:
    import spi_receive
    import filter
    from superfilter import super_filter
    HARDWARE_READY = True
except ImportError as e:
    print(f"[BOOT] Notice: Hardware modules not found or missing dependencies ({e}).")
    pass

PORT_HTTP = 8080
PORT_WS = 8000

DATA_FILE = os.path.normpath(os.path.join(DIRECTORY, "../../data/10sec_ecg_output.csv"))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

def start_http_server():
    with socketserver.TCPServer(("", PORT_HTTP), Handler) as httpd:
        httpd.serve_forever()

async def hardware_stream(websocket):
    """ Hardware pipeline hooked directly into the Web UI. """
    print("[SERVER] Attempting to connect to true ESP32 hardware...")
    
    stream = spi_receive.SerialStreaming()
    if not stream.connect():
        # Auto-fallback to CSV if no hardware is found
        return False
        
    print("[SUCCESS] ESP32 SPI Pipeline activated!")
    config_dir = os.path.join(DIRECTORY, '..', 'config')
    try:
        comp_coef = np.genfromtxt(os.path.join(config_dir, 'coef2.dat')).flatten()
        fir_coef = np.genfromtxt(os.path.join(config_dir, 'coef_fir_v2.dat')).flatten()
    except Exception as e:
        print(f"[ERROR] Could not load filter coefficients: {e}")
        return False
        
    try:
        fs_web = 240
        buffer_size = fs_web * 3 # 3 second sliding window
        bpm = 72
        
        # Buffer of the last N decimation outputs to count peaks easily
        history = []
        
        while True:
            # 1. Blocking stream get
            raw_bits = stream.get_chunk()
            if raw_bits is not None:
                # 2. Stage 1 Filtering
                input_bits = raw_bits.astype(np.float64).flatten()
                fir_out, fs_mid = filter.filter(input_bits, comp_coef, fir_coef)
                
                # 3. Stage 2 Super Filtration (Medical curve extraction)
                final_ecg = super_filter(fir_out, fs_mid, 0.5, 55)
                
                # 4. Decimate to 240Hz for pure web canvas rendering
                dfactor = 100
                display_ecg = final_ecg[::dfactor]
                
                # 5. Apply user requested quant.py fixed-point quantization
                q_value, _ = quant.quant(display_ecg, 16, 14)
                
                # 6. Apply user requested bpm.py peak finding algorithm over sliding window
                history.extend(q_value.tolist())
                if len(history) > buffer_size:
                    history = history[-buffer_size:]
                    peaks, _ = signal.find_peaks(history, height=np.max(history)*0.6, distance=int(fs_web*0.6))
                    if len(peaks) > 1:
                        rr_intervals = np.diff(peaks) / fs_web
                        bpm = int(round(60 / np.mean(rr_intervals)))
                
                batch = q_value.tolist()
                await websocket.send(json.dumps({"batch": batch, "bpm": bpm}))
            await asyncio.sleep(0.001)
    except websockets.exceptions.ConnectionClosed:
        print("[SERVER] UI disconnected from hardware stream.")
    except Exception as e:
        print(f"[ERROR] Hardware looping error: {e}")
    finally:
        stream.close()
    return True

async def csv_simulation_stream(websocket):
    """ Standalone test pipeline for independent cross-platform Dev/Testing. """
    print("[WARNING] Hardware not found. Gracefully engaging Standalone CSV Mode...")
    
    # Preload the entire file, downsample, and quantize it
    raw_amplitudes = []
    with open(DATA_FILE, 'r') as f:
        reader = csv.reader(f)
        next(reader) 
        for i, row in enumerate(reader):
            if i % 100 == 0:
                raw_amplitudes.append(float(row[1]))
                
    arr = np.array(raw_amplitudes)
    # Apply Quantization
    q_value, _ = quant.quant(arr, 16, 14)
    
    fs_web = 240
    buffer_size = fs_web * 3
    bpm = 72
    points_per_frame = 4
    
    try:
        idx = 0
        total = len(q_value)
        while True:
            end_idx = min(idx + points_per_frame, total)
            batch = q_value[idx:end_idx].tolist()
            
            # Apply real python find_peaks over the local 3 second sliding window
            start_val = max(0, idx - buffer_size)
            window = q_value[start_val:idx]
            if len(window) > fs_web:
                peaks, _ = signal.find_peaks(window, height=np.max(window)*0.6, distance=int(fs_web*0.6))
                if len(peaks) > 1:
                    rr_intervals = np.diff(peaks) / fs_web
                    bpm = int(round(60 / np.mean(rr_intervals)))
                    
            if len(batch) > 0:
                await websocket.send(json.dumps({"batch": batch, "bpm": bpm}))
            
            idx += points_per_frame
            if idx >= total:
                idx = 0
            
            await asyncio.sleep(0.016)
    except websockets.exceptions.ConnectionClosed:
        print("[SERVER] UI disconnected from CSV stream.")
    except Exception as e:
        print(f"[ERROR] CSV Stream Logic Error: {e}")

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

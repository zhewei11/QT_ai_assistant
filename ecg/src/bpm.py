import numpy as np
import pandas as pd
from scipy import signal
import plotly.graph_objects as go
import spi_receive
import filter

# --- 參數設定 ---
RECORD_SECONDS = 10
FS_RAW = 500000 
Filter_Low = 0.5
Filter_High = 55

def main():
    stream = spi_receive.SerialStreaming()
    if not stream.connect(): return

    all_data_bits = []
    print(f">>> 正在讀取理想訊號 ({RECORD_SECONDS}s)...")
    
    total_bits_needed = FS_RAW * RECORD_SECONDS
    bits_collected = 0
    while bits_collected < total_bits_needed:
        chunk = stream.get_chunk()
        if chunk is not None:
            all_data_bits.extend(chunk)
            bits_collected += len(chunk)
    stream.close()

    # --- 訊號處理 ---
    input_bits = np.array(all_data_bits).astype(np.float64)
    comp = np.genfromtxt('coef2.dat').flatten()
    fir = np.genfromtxt('coef_fir_v2.dat').flatten()
    fir_out, fs_mid = filter.filter(input_bits, comp, fir)
    
    sos = signal.butter(3, [Filter_Low, Filter_High], fs=fs_mid, btype='band', output='sos')
    final_ecg = signal.sosfiltfilt(sos, fir_out)
    t = np.arange(len(final_ecg)) / fs_mid

    # --- 新增：R 波偵測與 BPM 計算 ---
    # 設定高度門檻為最大值的 60%，距離至少間隔 0.6 秒 (對應 100 BPM)
    peaks, _ = signal.find_peaks(final_ecg, height=np.max(final_ecg)*0.6, distance=int(fs_mid*0.6))
    
    # 計算 RR 間隔與 BPM
    if len(peaks) > 1:
        rr_intervals = np.diff(peaks) / fs_mid
        avg_bpm = 60 / np.mean(rr_intervals)
        print(f">>> 平均心率 (BPM): {avg_bpm:.2f}")
    else:
        avg_bpm = 0

    # --- Plotly 繪圖 ---
    fig = go.Figure()
    # 原始 ECG 線
    fig.add_trace(go.Scatter(x=t, y=final_ecg, name='ECG Signal', line=dict(width=1)))
    # 標註 R 波點
    fig.add_trace(go.Scatter(x=t[peaks], y=final_ecg[peaks], mode='markers', 
                             marker=dict(size=10, color='red', symbol='cross'), name='R-peaks'))

    fig.update_layout(
        title=f'ECG Analysis - Estimated BPM: {avg_bpm:.1f}',
        xaxis_title='Time (s)', yaxis_title='Amplitude',
        template='plotly_dark', xaxis_rangeslider_visible=True
    )
    fig.show()

if __name__ == "__main__":
    main()
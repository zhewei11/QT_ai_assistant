import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt
import matplotlib.pyplot as plt

# --- 1. 定義您的「強大濾波器」 ---
def super_filter(data, fs, save_frequency_start, save_frequency_end):
    b, a = butter(3, [save_frequency_start, save_frequency_end], fs=fs, btype='band')
    y = filtfilt(b, a, data)
    return y

# --- 2. 處理位元流並解調 ---
def load_and_process_bits(filename):
    print(f"正在讀取 {filename} ...")
    bits = pd.read_csv(filename, header=None).values.flatten()
    
    fs_raw = 1536000 
    q = 1536
    n = len(bits) // q
    bits_truncated = bits[:n*q].reshape(-1, q)
    raw_analog = np.mean(bits_truncated, axis=1)
    
    actual_fs = fs_raw / q 
    return raw_analog, actual_fs

# --- 3. 主程式執行 ---
if __name__ == "__main__":
    try:
        # A. 處理資料
        data_raw, fs = load_and_process_bits('spi_receive.csv')
        
        # B. 套用強大濾波器 (0.5Hz ~ 55Hz)
        data_filtered = super_filter(data_raw, fs, 0.5, 200)
        
        # --- 【新增步驟：存成 CSV 檔】 ---
        output_filename = 'filtered_ecg_output.csv'
        print(f"正在將過濾後的資料存至 {output_filename} ...")
        
        # 建立時間軸
        t = np.arange(len(data_filtered)) / fs
        
        # 使用 Pandas 建立表格並儲存
        # 欄位包含：Time (秒), Amplitude (振幅)
        df_output = pd.DataFrame({
            'Time_sec': t,
            'Amplitude': data_filtered
        })
        df_output.to_csv(output_filename, index=False)
        print("儲存成功！")
        # --------------------------------

        # C. 模擬 MATLAB 畫圖
        print("正在繪製圖形...")
        plt.figure(figsize=(12, 6), facecolor='white')
        plt.plot(t, data_filtered, color='#0072BD', linewidth=1.5) 
        
        plt.title('Strong Filtered ECG Signal (0.5 - 55 Hz)', fontsize=14, fontweight='bold')
        plt.xlabel('Time (seconds)', fontsize=12)
        plt.ylabel('Amplitude', fontsize=12)
        plt.grid(True, which='both', linestyle='--', alpha=0.7)
        plt.gca().set_facecolor('#F8F8F8')
        
        if t[-1] > 5:
            plt.xlim([0, 5])
            
        plt.tight_layout()
        plt.show()
        
    except FileNotFoundError:
        print("錯誤：找不到 spi_receive.csv")
    except Exception as e:
        print(f"發生錯誤：{e}")
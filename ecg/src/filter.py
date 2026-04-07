import numpy as np
from scipy import signal
import matplotlib.pyplot as plt

# 假設您的 quant.py 檔案在同一目錄下，且其中定義了 quant(input_value, bit_num, fraction_num) 函數。
# 如果您的 quant 函數是直接定義在主檔案中，請確保將其定義複製到這個腳本的開頭。
import quant 

def filter(a, comp, fir):
    """
    執行訊號的降採樣、量化和濾波處理。

    :param a: 輸入訊號陣列 (來自 shen02_veryGood.csv)。
    :param comp: 補償濾波器係數陣列 (來自 coef2.dat)。
    :param fir: 最終 FIR 濾波器係數陣列 (來自 coef_fir_v2.dat)。
    :return: None. 函數將繪製結果圖形。
    """
    
    N = len(a) - 1
    print(f"Initial signal length: {N + 1}")

    # --- 1. 降採樣/CIC 積分器級聯 (Decimation/CIC Integrator Cascade) ---
    
    # Stage B: 4 Integrators, Decimation by 2
    i = np.arange(N)
    b1 = (a[i] + a[i+1])
    N = N - 1
    i = np.arange(N)
    b2 = (b1[i] + b1[i+1])
    N = N - 1
    i = np.arange(N)
    b3 = (b2[i] + b2[i+1])
    N = N - 1
    i = np.arange(N)
    b4 = (b3[i] + b3[i+1])
    
    if N % 2 == 0: N = N - 1
    j1 = np.arange(1, N + 1, 2)
    b5 = b4[j1 - 1] 
    N = ((N + 1) // 2) - 1

    # Stage C: 4 Integrators, Decimation by 2
    i = np.arange(N)
    c1 = (b5[i] + b5[i+1])
    N = N - 1
    i = np.arange(N)
    c2 = (c1[i] + c1[i+1])
    N = N - 1
    i = np.arange(N)
    c3 = (c2[i] + c2[i+1])
    N = N - 1
    i = np.arange(N)
    c4 = (c3[i] + c3[i+1])
    
    if N % 2 == 0: N = N - 1
    j2 = np.arange(1, N + 1, 2)
    c5 = c4[j2 - 1]
    N = ((N + 1) // 2) - 1

    # Stage D: 4 Integrators, Decimation by 2
    i = np.arange(N)
    d1 = (c5[i] + c5[i+1])
    N = N - 1
    i = np.arange(N)
    d2 = (d1[i] + d1[i+1])
    N = N - 1
    i = np.arange(N)
    d3 = (d2[i] + d2[i+1])
    N = N - 1
    i = np.arange(N)
    d4 = (d3[i] + d3[i+1])
    
    if N % 2 == 0: N = N - 1
    j3 = np.arange(1, N + 1, 2)
    d5 = d4[j3 - 1]
    N = ((N + 1) // 2) - 1

    # Stage E: 4 Integrators (with division by 2 in e4), Decimation by 2
    i = np.arange(N)
    e1 = (d5[i] + d5[i+1])
    N = N - 1
    i = np.arange(N)
    e2 = (e1[i] + e1[i+1])
    N = N - 1
    i = np.arange(N)
    e3 = (e2[i] + e2[i+1])
    N = N - 1
    i = np.arange(N)
    e4 = (e3[i] + e3[i+1]) / 2  # Note the division by 2 here
    
    if N % 2 == 0: N = N - 1
    j4 = np.arange(1, N + 1, 2)
    e5 = e4[j4 - 1]
    N = ((N + 1) // 2) - 1

    # Stage F: 4 Integrators (with division and floor), Decimation by 2
    i = np.arange(N)
    f1 = np.floor((e5[i] + e5[i+1]) / 2)
    N = N - 1
    i = np.arange(N)
    f2 = np.floor((f1[i] + f1[i+1]) / 2)
    N = N - 1
    i = np.arange(N)
    f3 = np.floor((f2[i] + f2[i+1]) / 2)
    N = N - 1
    i = np.arange(N)
    f4 = np.floor((f3[i] + f3[i+1]) / 2)
    
    if N % 2 == 0: N = N - 1
    j5 = np.arange(1, N + 1, 2)
    f5 = f4[j5 - 1]
    f5 = f5 * 2**(-14)
    
    N = (N + 1) // 2
    
    # First Quantization
    f5_q, _ = quant.quant(f5, 16, 14)
    print(f"Signal length after CIC/Decimation stages (f5_q): {len(f5_q)}")
    
    # --- 2. 補償濾波器 (Compensation Filter) ---
        
    # Quantize coefficients
    comp_q_temp, _ = quant.quant(comp, 16, 14)

    # Convolution (FIR Filtering)
    comp_temp = signal.convolve(f5_q, comp_q_temp, mode='valid')

    # Quantize output
    comp_temp_q, _ = quant.quant(comp_temp, 24, 20)
    
    comp_out = comp_temp_q
    
    # --- 3. 繪圖和 SINAD 分析 (Compensation Filter Output) ---
    
    fs = 48000
    t_comp = np.arange(len(comp_out)) / fs
    
    plt.figure(111)
    plt.plot(t_comp, comp_out)
    plt.title('Compensation Filter Output (comp_out)')
    plt.xlabel('Time (s)')
    plt.ylabel('Amplitude')
    plt.grid(True)

    plt.figure(3)
    plt.text(0.5, 0.5, 'SINAD Calculation Placeholder', ha='center', va='center')
    plt.title('SINAD Analysis (comp_out)')
    plt.grid(True)

    # --- 4. 最終 FIR 濾波器 (Final FIR Filter) ---
        
    # Quantize coefficients
    fir_q_temp, _ = quant.quant(fir, 16, 14)

    M_fir = len(fir_q_temp)
    N_prev = len(comp_out)
    N_fir_out_full = N_prev - M_fir + 1
    
    # Convolution (FIR Filtering)
    fir_temp = signal.convolve(comp_out, fir_q_temp, mode='valid')
    
    # Quantize output
    fir_temp_q, _ = quant.quant(fir_temp, 16, 14)
    
    # Final Decimation by 2
    N = N_fir_out_full - 1
    if N % 2 == 0: N = N - 1
        
    j7 = np.arange(1, N + 1, 2)
    fir_out = fir_temp_q[j7 - 1]
    print(f"Final signal length (fir_out): {len(fir_out)}")
    
    # --- 5. 繪圖 (Final FIR Filter Output) ---
    
    fs_final = fs / 2
    pts_final = len(fir_out)
    t_fir = np.arange(pts_final) / fs_final

    plt.figure(35)
    plt.plot(t_fir, fir_out)
    plt.title('Final FIR Filter Output (fir_out)')
    plt.xlabel('Time (s)')
    plt.ylabel('Amplitude')
    plt.grid(True)
    
    plt.show()

    fs_final = fs / 2
    #fs_final = 24000
    return fir_out, fs_final # 新增這行：回傳處理後的訊號與取樣率


if __name__ == '__main__':
    
    # 載入所有外部檔案數據
    try:
        # 1. 載入輸入訊號
        #raw_data = np.genfromtxt('./shen02_veryGood.csv', delimiter=',').flatten()
        raw_data = np.genfromtxt('./spi_receive.csv', delimiter=',').flatten()
        
        # 2. 載入補償濾波器係數
        comp = np.genfromtxt('coef2.dat').flatten()
        
        # 3. 載入最終 FIR 濾波器係數
        fir = np.genfromtxt('coef_fir_v2.dat').flatten()
        
        print("所有檔案載入成功，開始處理訊號...")
        
        # 執行訊號處理
        filter(raw_data, comp, fir)
        
    except IOError as e:
        print(f"Error: 載入檔案失敗。請檢查檔案是否存在於正確路徑：{e}")
    except Exception as e:
        print(f"處理過程中發生錯誤: {e}")
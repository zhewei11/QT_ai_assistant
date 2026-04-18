import sys
import os
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from scipy import signal

# 匯入您的自定義模組
import filter           
from spi_receive import SerialStreaming

class SPIWorker(QThread):
    """
    負責在背景執行 SPI 接收與標準濾波。
    """
    data_ready = pyqtSignal(np.ndarray)

    def run(self):
        self.stream = SerialStreaming() 
        if not self.stream.connect():
            print(">>> [錯誤] 無法連接 ESP32")
            return
        
        try:
            # 自動計算相對於腳本的 config 資料夾絕對路徑
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_dir = os.path.join(os.path.dirname(script_dir), 'config')
            
            # 載入原始係數
            comp = np.genfromtxt(os.path.join(config_dir, 'coef2.dat')).flatten()
            fir = np.genfromtxt(os.path.join(config_dir, 'coef_fir_v2.dat')).flatten()
        except Exception as e:
            print(f">>> [錯誤] 檔案讀取失敗: {e}")
            return
        
        # --- 串流濾波狀態保存 ---
        fs_final = 24000
        # 僅保留標準帶通濾波器 (0.5 - 55Hz)
        sos_band = signal.butter(3, [0.5, 40], fs=fs_final, btype='band', output='sos')
        zi_band = signal.sosfilt_zi(sos_band)

        print(">>> [背景] 標準濾波監測啟動 (僅降採樣 + 帶通)...")

        while True:
            bits = self.stream.get_chunk()
            if bits is not None:
                try:
                    # 第一級：降採樣解調 (CIC + FIR)
                    fir_out, fs_mid = filter.filter(bits, comp, fir)
                    
                    # 第二級：標準帶通濾波 (不含強力平滑，不含極性修正)
                    final_ecg, zi_band = signal.sosfilt(sos_band, fir_out, zi=zi_band)
                    
                    # 直接發送原始濾波結果
                    self.data_ready.emit(final_ecg)
                    
                except Exception as e:
                    print(f"處理誤差: {e}")
            else:
                self.msleep(1)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Monitor - Standard Filter View")
        
        # --- 為了霸佔 QTrobot 臉部螢幕，設定為無邊框全螢幕 ---
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.showFullScreen()
        self.setStyleSheet("background-color: black;")
        
    # 加入按 ESC 鍵離開全螢幕的功能
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        
        layout = QVBoxLayout()
        # 更新標籤描述
        self.label = QLabel("模式：即時監控 | 濾波：標準帶通 (0.5-55Hz) | 無額外圖形修正")
        self.label.setStyleSheet("color: #FFFFFF; font-family: Microsoft JhengHei; font-size: 14px;")
        layout.addWidget(self.label)

        self.pw = pg.PlotWidget()
        self.pw.setBackground('k')
        self.pw.showGrid(x=True, y=True, alpha=0.3)
        
        # 恢復較寬的觀察範圍，因為沒有修正後的波形振幅可能較大
        self.pw.setYRange(-0.15, 0.15, padding=0.1) 
        
        # 保留 0 位線作為物理基準參考
        self.pw.addLine(y=0, pen=pg.mkPen('r', width=1, style=Qt.DashLine))

        # 繪圖曲線
        self.curve = self.pw.plot(pen=pg.mkPen(color='c', width=1.5)) 
        
        self.fs = 24000
        self.display_len = self.fs * 2
        self.buffer = np.zeros(self.display_len)
        self.time_axis = np.linspace(-2, 0, self.display_len)
        
        layout.addWidget(self.pw)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.worker = SPIWorker()
        self.worker.data_ready.connect(self.update_plot)
        self.worker.start()

    def update_plot(self, data):
        n = len(data)
        if n > 0:
            self.buffer = np.roll(self.buffer, -n)
            self.buffer[-n:] = data
            self.curve.setData(self.time_axis, self.buffer)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
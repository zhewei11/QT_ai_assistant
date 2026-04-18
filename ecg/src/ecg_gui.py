import sys
import numpy as np
import pandas as pd
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# 引入您之前的模組
import spi_receive
import filter
from superfilter import super_filter

class BackendWorker(QThread):
    """ 後端處理執行緒：負責接收與兩級濾波 """
    data_ready = pyqtSignal(np.ndarray, float) # 傳送處理好的數據與取樣率

    def run(self):
        # 預先載入濾波係數
        comp_coef = np.genfromtxt('coef2.dat').flatten()
        fir_coef = np.genfromtxt('coef_fir_v2.dat').flatten()

        while True:
            # 1. SPI 接收 (每次抓取一小段，例如 1M bits)
            raw_bits = spi_receive.receive_and_unpack()
            
            if raw_bits is not None:
                try:
                    # 2. 第一級濾波 (CIC + FIR)
                    input_bits = raw_bits.astype(np.float64).flatten()
                    fir_out, fs_mid = filter.filter(input_bits, comp_coef, fir_coef)
                    
                    # 3. 第二級 Super Filter (0.5-55Hz)
                    final_ecg = super_filter(fir_out, fs_mid, 0.5, 55)
                    
                    # 4. 將結果發送給前端
                    self.data_ready.emit(final_ecg, fs_mid)
                except Exception as e:
                    print(f"後端處理錯誤: {e}")
            
            self.msleep(10) # 稍微暫停，避免 CPU 滿載

class RealTimeECGGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SPI 即時心電訊號監測系統")
        self.setGeometry(100, 100, 1200, 600)

        # 緩衝區：儲存要顯示在螢幕上的點
        self.display_buffer = np.array([])
        self.max_display_points = 2000 # 螢幕顯示的總點數

        self.initUI()

        # 啟動後端執行緒
        self.worker = BackendWorker()
        self.worker.data_ready.connect(self.on_data_received)
        self.worker.start()

    def initUI(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # 建立畫布
        self.fig = Figure(figsize=(10, 5), facecolor='#F8F8F8')
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlim(0, 2.0) # 固定顯示 2 秒
        self.ax.set_ylim(-0.5, 0.5) # 根據您的訊號振幅調整
        self.ax.grid(True, linestyle='--', alpha=0.5)
        self.line, = self.ax.plot([], [], color='#0072BD', linewidth=1.5)
        
        layout.addWidget(self.canvas)
        self.status_label = QLabel("正在等待硬體資料...")
        layout.addWidget(self.status_label)

    def on_data_received(self, ecg_data, fs):
        """ 當後端處理完一整段資料時觸發 """
        self.status_label.setText(f"資料接收中... 取樣率: {fs} Hz")
        
        # 將新資料加入緩衝區
        self.display_buffer = np.concatenate([self.display_buffer, ecg_data])
        
        # 只保留最後 N 個點，實現滾動效果
        if len(self.display_buffer) > self.max_display_points:
            self.display_buffer = self.display_buffer[-self.max_display_points:]

        # 更新畫圖
        t = np.linspace(0, 2.0, len(self.display_buffer))
        self.line.set_data(t, self.display_buffer)
        
        # 動態調整 Y 軸 (可選)
        if len(self.display_buffer) > 0:
            ymin, ymax = np.min(self.display_buffer), np.max(self.display_buffer)
            self.ax.set_ylim(ymin * 1.2, ymax * 1.2)

        self.canvas.draw()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = RealTimeECGGui()
    gui.show()
    sys.exit(app.exec_())
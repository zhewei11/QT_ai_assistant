# import serial
# import numpy as np
# import time

# # --- 參數設定 ---
# COM_PORT = 'COM11'
# BAUD_RATE = 1000000
# CHUNK_SIZE = 16384 * 4  # 每次讀取的 bit 數 (約 0.04 秒資料，增加即時感)
# BYTES_TO_READ = CHUNK_SIZE // 8

# class SerialStreaming:
#     def __init__(self):
#         self.ser = None

#     def connect(self):
#         try:
#             self.ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
#             print("Cleaning buffer...")
#             time.sleep(1)
#             self.ser.reset_input_buffer()
#             print("Sending Start Command...")
#             self.ser.write(bytes([0x09]))
#             return True
#         except Exception as e:
#             print(f"Connect Error: {e}")
#             return False

#     def get_chunk(self):
#         """ 讀取一小塊數據並回傳 bits """
#         if self.ser and self.ser.is_open:
#             raw_bytes = self.ser.read(BYTES_TO_READ)
#             if len(raw_bytes) > 0:
#                 data_array = np.frombuffer(raw_bytes, dtype=np.uint8)
#                 bits = np.unpackbits(data_array)
#                 return bits.astype(np.float64) # 直接轉好型態給濾波器
#         return None

#     def close(self):
#         if self.ser:
#             self.ser.write(b's')
#             self.ser.close()


import serial
import numpy as np
import time

import sys
import glob

# --- 參數設定 ---
# 針對不同作業系統自動尋找 USB ESP32 的串口 (Linux 對應 QTrobot, Windows/Mac 對應你目前開發的電腦)
if sys.platform.startswith('win'):
    COM_PORT = 'COM11'
elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
    # QTrobot (Ubuntu/Raspberry Pi)
    ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
    COM_PORT = ports[0] if len(ports) > 0 else '/dev/ttyUSB0'
elif sys.platform.startswith('darwin'):
    # Mac OSX
    ports = glob.glob('/dev/tty.usbmodem*') + glob.glob('/dev/tty.usbserial*')
    COM_PORT = ports[0] if len(ports) > 0 else '/dev/tty.usbserial'

BAUD_RATE = 1000000
CHUNK_SIZE = 16384 * 4  
BYTES_TO_READ = CHUNK_SIZE // 8

class SerialStreaming:
    def __init__(self):
        self.ser = None

    def connect(self):
        try:
            self.ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
            print("Cleaning buffer...")
            time.sleep(1)
            self.ser.reset_input_buffer()
            print("Sending Start Command...")
            self.ser.write(bytes([0x09]))
            return True
        except Exception as e:
            print(f"Connect Error: {e}")
            return False

    def get_chunk(self):
        if self.ser and self.ser.is_open:
            raw_bytes = self.ser.read(BYTES_TO_READ)
            if len(raw_bytes) > 0:
                data_array = np.frombuffer(raw_bytes, dtype=np.uint8)
                bits = np.unpackbits(data_array)
                return bits.astype(np.float64) 
        return None

    def close(self):
        if self.ser:
            self.ser.write(b's')
            self.ser.close()
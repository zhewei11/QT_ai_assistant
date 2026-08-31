import asyncio
import os
import numpy as np


class HRS:

    def __init__(self, en_file_out=False):
        # ECG processing
        self.__fs = 360
        self.__output_index_offset = round(3 / 4 * self.__fs)
        self.__ext_offset = round(5 * self.__fs)
        self.R_peak_array = []

        # IIR 360
        self.__IIR_A_360 = np.array(
            [-10.3440596568499, 49.3735736910750, -143.800383746135, 284.633669008023, -403.381202948858,
             419.706197144518,
             -323.045356703911, 182.558011278432, -73.8723880311975, 20.3185299499858, -3.41089781661137,
             0.264307862381624])  # ver cheby2
        self.__IIR_B_360 = np.array(
            [0.00169411609740140, -0.0140507299812298, 0.0549209469898199, -0.135712740881473, 0.240530829768216,
             -0.329163673589077, 0.363562503223537, -0.329163673589077, 0.240530829768216, -0.135712740881473,
             0.0549209469898198, -0.0140507299812297, 0.00169411609740140])  # ver cheby2

        self.__coef_a = None
        self.__coef_b = None
        self.__IIR_Buf_A = np.zeros(12)  # ellip ver : 6
        self.__IIR_Buf_B = np.zeros(13)  # ellip ver : 7

        # Hide in Dream
        self.__HiD_360 = np.array(
            [-0.2304, 0, 0, 0, 0, 0, 0, 0, 0, 0.7148, 0, 0, 0, 0, 0, 0, 0, 0, -0.6309, 0, 0, 0, 0, 0, 0, 0, 0,
             -0.0280, 0, 0, 0, 0, 0, 0, 0, 0, 0.1870, 0, 0, 0, 0, 0, 0, 0, 0, 0.0308, 0, 0, 0, 0, 0, 0, 0, 0,
             -0.0329, 0, 0, 0, 0, 0, 0, 0, 0, -0.0106, 0, 0, 0, 0, 0, 0, 0, 0])
        self.__HiD = None

        self.__SQU_BUF = np.zeros(1001)
        self.__HiD_BUF = np.zeros(self.__HiD_360.shape[0])
        self.__MS_BUF = None
        self.__SQU_BUF_index = 0
        self.__BPM_BUF_LEN = 15
        self.__BPM_BUF = np.ones(self.__BPM_BUF_LEN) * (-10000)
        self.__WIN_S_LEN = round(self.__fs * 0.15 * 0.5)  # 75
        self.__WIN_L_LEN = round(self.__fs * 0.5)  # 500
        self.__WIN_S_SUM = 0
        self.__WIN_L_SUM = 0
        self.__SQU_BUF_SIZE = 1001
        self.__SHIFT_num = 1

        self.__FPs_direction_pre = 0  # 0向上 1向下
        self.__FPs_direction_post = 0  # 0向上 1向下
        self.__FPs_IsFirstPoint = True  # 確認是不是第一點
        self.__FPs_RR_counter = -1  # 計算peak間距
        self.__FPs_current_RR = 0
        self.__FPs_RR_Cand = 0
        self.__FPs_pks_Cand = -1  # 紀錄Candidate峰值
        self.__FPs_Cand_detect = 0  # 1 if Candidate for pksloc is found
        self.__FPs_base_hL = np.inf  # for MinPeakProminence left side
        self.__FPs_base_hLCheck = 0
        self.__FPs_data_max = 0
        self.__FPs_data_min = np.inf
        self.__max_BPM_setting = 300
        self.__FPs_MinPeakDistance = round(self.__fs / (self.__max_BPM_setting / 60 + 1))
        self.__FPs_init_range = self.__fs * 5  # 5000 # Original = 4s
        self.__FPs_init_range_cnt = 0
        self.__FPs_MinPeakProminence = 0.6  # 10
        self.__FPs_BUF = np.zeros(3)
        self.__FPs_start_detect = False

        self.__PARAM_SET = False
        self.__HR_VAL_OUTPUT_EN = False

        self.__STD_THR = 25  # 20
        self.__ZC_THR = 130  # 35
        self.__Reset_cnt = 0
        self.__RESET_CNT_NUM = 1
        self.__input_data_cnt = 1
        self.__FPs_BUF_init_cnt = 2
        self.__BPM_BUF_init_cnt = 0

        # RESP Rate parameter
        self.__RR_BUF_init_cnt = 0
        self.__Resp_pks_Count = 0
        self.__Resp_Distance = 0
        self.__Resp_DistanceRecord = np.zeros(20)
        self.__RR_record = np.zeros(3)  # RR_record[0]=new data, RR_record[1]=mid data, RR_record[2]=old data
        self.__RPM = '-'
        # self.__RPM_BUF = np.zeros(20)  # for debug

        # BLE_Loss_Detect
        self.__BLD_stop = 0
        self.__BLD_stop_count = 0
        self.__BLD_CD_LENGTH = 1  # sec

        # Debug
        self.__en_fo = en_file_out
        self.__HR_file = None
        if self.__en_fo:
            self.__currentDir = os.path.abspath(os.getcwd())
            self.__RRCsvFile_path = os.path.join(self.__currentDir, 'RR_record.csv')
            self.__HR_file = open(self.__RRCsvFile_path, 'w', encoding='utf-8')

    # NEED TO MODIFY
    async def BPM_CAL(self, data, freq, ECG_pkg):

        # Frequency determination and initiation
        if not self.__PARAM_SET:
            # NEED TO MODIFY
            self.__fs = freq
            self.__coef_a = self.__IIR_A_360
            self.__coef_b = self.__IIR_B_360
            self.__HiD = self.__HiD_360
            self.__WIN_S_LEN = round(self.__fs * 0.15 * 0.5)
            self.__WIN_L_LEN = round(self.__fs * 0.5)
            self.__SQU_BUF = np.resize(self.__SQU_BUF, (1 + self.__WIN_L_LEN * 2))
            self.__SQU_BUF_SIZE = self.__SQU_BUF.shape[0]
            self.__HiD_BUF = np.zeros(self.__HiD_360.shape[0])
            self.__MS_BUF = np.zeros(2 * self.__WIN_S_LEN)
            self.__FPs_MinPeakDistance = round(self.__fs / (self.__max_BPM_setting / 60 + 1))
            self.__FPs_init_range = 4.5 * freq
            self.__output_index_offset = round(3 / 4 * self.__fs)
            self.__PARAM_SET = True

        # hexStr = ','.join(format(x, '02x') for x in data)
        # print("received:", hexStr)
        # if self.__en_fo:
        # self.__HR_file.write(f'{",".join(str(e) for e in data.tolist())}')
        # self.__HR_file.write(f',{ECG_pkg}\n')

        # ECG BPM calculation

        # init for each call
        self.__input_data_cnt = 0
        self.R_peak_array = []

        for input_val in data:

            self.__input_data_cnt = self.__input_data_cnt + 1

            # IIR Calculation
            self.__IIR_Buf_B[self.__SHIFT_num:] = self.__IIR_Buf_B[:-self.__SHIFT_num]
            self.__IIR_Buf_B[:self.__SHIFT_num] = input_val  # out_NO
            b_sum = np.dot(self.__coef_b, self.__IIR_Buf_B)
            a_sum = np.dot(self.__coef_a, self.__IIR_Buf_A)
            out_IIR = b_sum - a_sum
            # print (self.__IIR_Buf_B,self.__IIR_Buf_A)

            # IIR Shifting
            self.__IIR_Buf_A[self.__SHIFT_num:] = self.__IIR_Buf_A[:-self.__SHIFT_num]
            self.__IIR_Buf_A[:self.__SHIFT_num] = out_IIR

            # Square Ratio
            del_element = self.__SQU_BUF[-1] * self.__SQU_BUF[-1]
            self.__SQU_BUF[self.__SHIFT_num:] = self.__SQU_BUF[:-self.__SHIFT_num]
            self.__SQU_BUF[:self.__SHIFT_num] = out_IIR

            mid_ind = 1 + self.__WIN_L_LEN
            if self.__SQU_BUF_index == self.__SQU_BUF_SIZE:
                self.__WIN_S_SUM = self.__WIN_S_SUM - self.__SQU_BUF[mid_ind + self.__WIN_S_LEN] * self.__SQU_BUF[
                    mid_ind + self.__WIN_S_LEN] + self.__SQU_BUF[mid_ind - self.__WIN_S_LEN - 1] * self.__SQU_BUF[
                                       mid_ind - self.__WIN_S_LEN - 1]
                self.__WIN_L_SUM = self.__WIN_L_SUM - del_element + self.__SQU_BUF[0] * self.__SQU_BUF[0]
                out_SQU = self.__SQU_BUF[mid_ind - 1] * self.__WIN_S_SUM / self.__WIN_L_SUM
            else:
                self.__SQU_BUF_index = self.__SQU_BUF_index + 1
                if self.__SQU_BUF_index == self.__SQU_BUF_SIZE:
                    self.__WIN_S_SUM = np.dot(
                        self.__SQU_BUF[(mid_ind - self.__WIN_S_LEN - 1):(mid_ind + self.__WIN_S_LEN)],
                        self.__SQU_BUF[(mid_ind - self.__WIN_S_LEN - 1):(mid_ind + self.__WIN_S_LEN)])
                    self.__WIN_L_SUM = np.dot(self.__SQU_BUF, self.__SQU_BUF)
                    out_SQU = self.__SQU_BUF[mid_ind - 1] * self.__WIN_S_SUM / self.__WIN_L_SUM

            if self.__SQU_BUF_index == self.__SQU_BUF_SIZE:
                # HiD + ABS
                self.__HiD_BUF[self.__SHIFT_num:] = self.__HiD_BUF[:-self.__SHIFT_num]
                self.__HiD_BUF[:self.__SHIFT_num] = out_SQU
                out_HiD = abs(np.dot(self.__HiD, self.__HiD_BUF))

                # Moving Sum
                self.__MS_BUF[self.__SHIFT_num:] = self.__MS_BUF[:-self.__SHIFT_num]
                self.__MS_BUF[:self.__SHIFT_num] = out_HiD
                out_MS = np.sum(self.__MS_BUF)

                # Findpeaks - init
                self.__FPs_BUF[self.__SHIFT_num:] = self.__FPs_BUF[:-self.__SHIFT_num]
                self.__FPs_BUF[:self.__SHIFT_num] = out_MS

                # BLE Loss Detection : Reset lite(類似掉電極 但不清空buffer)
                if ECG_pkg > 1:
                    self.__BLD_stop = 1
                    self.__BLD_stop_count = 0
                    self.__FPs_direction_pre = 0  # 0向上 1向下
                    self.__FPs_direction_post = 0  # 0向上 1向下
                    self.__FPs_IsFirstPoint = True  # 確認是不是第一點
                    self.__FPs_RR_counter = -1  # 計算peak間距
                    self.__FPs_current_RR = 0
                    self.__FPs_RR_Cand = 0
                    self.__FPs_pks_Cand = -1  # 紀錄Candidate峰值
                    self.__FPs_Cand_detect = 0  # 1 if Candidate for pksloc is found
                    # self.__FPs_base_hL = np.inf  # for MinPeakProminence left side
                    # self.__FPs_data_max = 0
                    # self.__FPs_data_min = np.inf
                    # self.__FPs_init_range_cnt = 0
                    # self.__FPs_start_detect = False

                if self.__BLD_stop == 0:
                    if self.__FPs_BUF_init_cnt > 0:
                        self.__FPs_BUF_init_cnt = self.__FPs_BUF_init_cnt - 1
                    else:
                        if self.__FPs_init_range_cnt < self.__FPs_init_range:
                            if self.__FPs_data_min > self.__FPs_BUF[0]: self.__FPs_data_min = self.__FPs_BUF[0]
                            if self.__FPs_data_max < self.__FPs_BUF[0]: self.__FPs_data_max = self.__FPs_BUF[0]
                            self.__FPs_init_range_cnt = self.__FPs_init_range_cnt + 1
                            if self.__FPs_init_range_cnt == self.__FPs_init_range:
                                self.__FPs_start_detect = True
                                self.__FPs_MinPeakProminence = (self.__FPs_data_max - self.__FPs_data_min) / 6
                                self.__FPs_data_max = 0
                                self.__FPs_data_min = np.inf
                                self.__FPs_init_range_cnt = 0

                    if self.__FPs_start_detect:
                        # Findpeaks - candidate searching
                        self.__FPs_RR_counter = self.__FPs_RR_counter + 1
                        self.__FPs_direction_pre = 0 if (self.__FPs_BUF[1] - self.__FPs_BUF[2] > 0) else 1
                        self.__FPs_direction_post = 0 if (self.__FPs_BUF[0] - self.__FPs_BUF[1] > 0) else 1
                        if self.__FPs_direction_pre == 0 and self.__FPs_direction_post == 1:
                            if (self.__FPs_RR_counter >= self.__FPs_MinPeakDistance or self.__FPs_IsFirstPoint) and (
                                    self.__FPs_BUF[
                                        1] - self.__FPs_base_hL >= self.__FPs_MinPeakProminence or self.__FPs_IsFirstPoint):
                                if self.__FPs_Cand_detect == 1:
                                    if self.__FPs_BUF[1] > self.__FPs_pks_Cand:
                                        self.__FPs_pks_Cand = self.__FPs_BUF[1]
                                        self.__FPs_RR_Cand = self.__FPs_RR_counter - 1
                                else:
                                    self.__FPs_pks_Cand = self.__FPs_BUF[1]
                                    self.__FPs_RR_Cand = self.__FPs_RR_counter - 1
                                    self.__FPs_Cand_detect = 1
                        if self.__FPs_direction_pre == 1 and self.__FPs_direction_post == 0:
                            if self.__FPs_BUF[1] < self.__FPs_base_hL:
                                self.__FPs_base_hL = self.__FPs_BUF[1]

                        # Findpeaks - candidate check
                        if self.__FPs_Cand_detect == 1:
                            if self.__FPs_pks_Cand - self.__FPs_BUF[0] >= self.__FPs_MinPeakProminence:
                                self.__FPs_current_RR = self.__FPs_RR_Cand
                                self.__FPs_RR_counter = self.__FPs_RR_counter - self.__FPs_RR_Cand  # 歸零即可
                                self.__FPs_pks_Cand = -1
                                self.__FPs_Cand_detect = 0
                                self.__FPs_base_hL = np.inf
                                self.__HR_VAL_OUTPUT_EN = False if self.__FPs_IsFirstPoint else True
                                self.__FPs_IsFirstPoint = False

                                output_Rpeak_index = self.__input_data_cnt - self.__output_index_offset - self.__ext_offset
                                if output_Rpeak_index > 0:
                                    self.R_peak_array.append(output_Rpeak_index)
                                    if self.__en_fo:
                                        self.__HR_file.write(f'{output_Rpeak_index}\n')

                elif ECG_pkg == 1:
                    if self.__BLD_stop_count > self.__BLD_CD_LENGTH * self.__fs:
                        self.__BLD_stop = 0
                        self.__BLD_stop_count = 0
                    else:
                        self.__BLD_stop_count = self.__BLD_stop_count + 1

                # RESP RATE
                if self.__HR_VAL_OUTPUT_EN:
                    self.__RR_record[self.__SHIFT_num:] = self.__RR_record[:-self.__SHIFT_num]
                    self.__RR_record[:self.__SHIFT_num] = self.__FPs_current_RR
                    self.__Resp_Distance = self.__Resp_Distance + self.__RR_record[:self.__SHIFT_num]
                    if self.__RR_BUF_init_cnt > 2:
                        if (self.__RR_record[0] - self.__RR_record[1] <= 0) and (
                                self.__RR_record[1] - self.__RR_record[2] > 0):
                            if self.__Resp_pks_Count > 0:
                                self.__Resp_DistanceRecord[self.__SHIFT_num:] = self.__Resp_DistanceRecord[
                                                                                :-self.__SHIFT_num]
                                self.__Resp_DistanceRecord[:self.__SHIFT_num] = self.__Resp_Distance - self.__RR_record[
                                    0] - self.__RR_record[1]
                                if self.__Resp_pks_Count >= 20:  # 20 times avg
                                    self.__RPM = round(
                                        60 / ((np.sum(
                                            self.__Resp_DistanceRecord) / self.__Resp_DistanceRecord.size) / self.__fs))

                            self.__Resp_Distance = self.__RR_record[0] + self.__RR_record[1]
                            if self.__Resp_pks_Count < 20:
                                self.__Resp_pks_Count = self.__Resp_pks_Count + 1

                    else:
                        self.__RR_BUF_init_cnt = self.__RR_BUF_init_cnt + 1  # stop at self.__RR_BUF_init_cnt = 3

                if self.__HR_VAL_OUTPUT_EN:
                    if self.__BPM_BUF_init_cnt < self.__BPM_BUF_LEN:
                        self.__BPM_BUF_init_cnt = self.__BPM_BUF_init_cnt + 1
                    self.__HR_VAL_OUTPUT_EN = False
                    self.__BPM_BUF[self.__SHIFT_num:] = self.__BPM_BUF[:-self.__SHIFT_num]
                    self.__BPM_BUF[:self.__SHIFT_num] = round(
                        60 * self.__fs / self.__FPs_current_RR) if self.__FPs_current_RR != 0 else -1

                '''
                if self.__input_data_cnt % (self.__fs * 1.5) == 0:
                    
                    self.__input_data_cnt = 1
                    BPM_val = round(np.sum(self.__BPM_BUF[
                                           :self.__BPM_BUF_init_cnt]) / self.__BPM_BUF_init_cnt) if self.__BPM_BUF_init_cnt > 1 else '-'

                    
                    # Lead Loss Condition Evaluation
                    std_val = (self.__WIN_L_SUM / self.__SQU_BUF_SIZE - np.mean(self.__SQU_BUF) * np.mean(
                        self.__SQU_BUF)) ** 0.5
                    nonZero_arr = self.__SQU_BUF[np.nonzero(self.__SQU_BUF)]
                    zc_count = np.where(np.diff(np.sign(nonZero_arr)))[0].shape[0]

                    if std_val >= self.__STD_THR or zc_count >= self.__ZC_THR:
                        BPM_val = '-'
                        self.__RPM = '-'
                        self.__Reset_cnt = self.__RESET_CNT_NUM
                    elif self.__Reset_cnt > 0:
                        BPM_val = '-'
                        self.__Reset_cnt = 0
                        self.__IIR_Buf_A = np.zeros(12)  # ellip ver : 6
                        self.__IIR_Buf_B = np.zeros(13)  # ellip ver : 7
                        self.__SQU_BUF = np.resize(self.__SQU_BUF, (1 + self.__WIN_L_LEN * 2))
                        self.__SQU_BUF_index = 0
                        self.__HiD_BUF = np.zeros(self.__HiD_360.shape[0])
                        self.__MS_BUF = np.zeros(2 * self.__WIN_S_LEN)
                        self.__FPs_BUF = np.zeros(3)
                        self.__FPs_BUF_init_cnt = 2
                        self.__FPs_start_detect = False
                        self.__FPs_MinPeakProminence = 0.6
                        self.__FPs_data_max = 0
                        self.__FPs_data_min = np.inf
                        self.__FPs_init_range_cnt = 0
                        self.__FPs_direction_pre = 0
                        self.__FPs_direction_post = 0
                        self.__FPs_IsFirstPoint = True
                        self.__FPs_RR_counter = -1
                        self.__FPs_pks_Cand = -1  # 紀錄Candidate峰值
                        self.__FPs_Cand_detect = 0  # 1 if Candidate for pksloc is found
                        self.__FPs_base_hL = np.inf
                        self.__HR_VAL_OUTPUT_EN = False
                        self.__BPM_BUF_init_cnt = 0
                        self.__BPM_BUF = np.ones(self.__BPM_BUF_LEN) * (-10000)

                        # RESP Reset
                        self.__RPM = '-'
                        self.__RR_BUF_init_cnt = 0
                        self.__Resp_Distance = 0
                        self.__Resp_pks_Count = 0

                    return BPM_val, self.__RPM  # , self.__BLD_stop_count, self.__BLD_stop
                    # return BPM_val
                    
                else:
                    self.__input_data_cnt = self.__input_data_cnt + 1
                '''
        if self.__en_fo:
            self.__HR_file.close()

        return self.R_peak_array

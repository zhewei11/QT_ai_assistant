
import numpy as np
import csv
import re

# import matplotlib.pyplot as plt

def load_file(filename):

    isMatch = re.search(r"mark.csv", filename)  # ^[0-9]+--

    if isMatch:
        return np.array([])

    fs = 400
    AFE_gain = 303
    ADC_full_voltage = 3600
    common_mode_voltage = 1650
    ADC_full_code = 2**12

    sig_raw = []

    # Load file
    with open(filename, 'r') as file:
      csvreader = csv.reader(file)
      for row in csvreader:
        sig_raw.append(row[1:])

    sig_raw = np.array(sig_raw)
    sig_raw = sig_raw.flatten()

    # Hex to Dec
    for i in range(len(sig_raw)):
        sig_raw[i] = int(sig_raw[i], base=16)

    # str to int
    sig_raw = sig_raw.astype(int)

    # decode adc number
    sig = sig_raw * ADC_full_voltage / (ADC_full_code * AFE_gain)


    return sig



# peak_golden = []
# with open("mark.csv", 'r') as file1:
#   csvreader = csv.reader(file1)
#   for row in csvreader:
#     peak_golden.append(row[0])

# peak_golden = np.array(peak_golden).astype(int)

# plt.plot(sig)
# plt.plot(peak_corr, sig[peak_corr], 'ro')
# plt.plot(peak_golden, sig[peak_golden], 'g*')
# plt.show()
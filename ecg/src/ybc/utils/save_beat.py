import numpy as np

def save_beat(r_peak, label, filepath):
    beat = np.zeros((len(r_peak), 2))
    print("r_peak shape = ", r_peak.shape)
    print("label shape = ", label.shape)
    for i in range(len(r_peak)):
        beat[i,0] = r_peak[i]
#        beat[i,1] = label[i]
        if hasattr(label[i], '__len__'):
             beat[i,1] = label[i][0]
        else:
             beat[i,1] = label[i]
    print("filepath = ", filepath)
    with open(filepath, 'w', newline='\n') as f:
        for i in range(len(beat)):
            f.write(str(int(beat[i,0])) + ',' + str(int(beat[i,1])) + '\n')

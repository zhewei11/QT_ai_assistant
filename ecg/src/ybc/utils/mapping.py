import numpy as np

def mapping(sig, center_peak, start_point, end_point, window_size):
    sig_window = np.zeros(window_size) 
    print("sig:",sig.shape)
    #for sig
    right_num_sig = end_point - center_peak - 1 # cause end_point = real end_point + 1
    left_num_sig = center_peak - start_point 
    center_idx_sig = left_num_sig   # array index

    # for sig_window
    center_idx_window = np.floor(window_size/2).astype(int)  # floor, and convert to int (array index)
    right_num_window = window_size - (center_idx_window + 1) 
    left_num_window = window_size - right_num_window - 1 

    sig_window[center_idx_window] = sig[center_idx_sig]   # center align

    # left side
    if (left_num_sig <= left_num_window):
        sig_window[center_idx_window-left_num_sig:center_idx_window] = sig[0:center_idx_sig] 
    else :   # range clipped
        sig_window[0:center_idx_window] = sig[center_idx_sig-left_num_window:center_idx_sig] 

    # right side
    if (right_num_sig <= right_num_window):  
        sig_window[center_idx_window+1:center_idx_window+right_num_sig+1] = sig[center_idx_sig+1:] 
    else :   # range clipped
        sig_window[center_idx_window+1:] = sig[center_idx_sig+1:center_idx_sig+right_num_window+1] 

    return sig_window 

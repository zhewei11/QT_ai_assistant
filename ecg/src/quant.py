import numpy as np

def quant(input_value, bit_num, fraction_num):
    """
    Simulates fixed-point quantization with saturation and truncation.
    
    Equivalent to the quant.m function.

    :param input_value: Input floating-point value (can be a numpy array).
    :param bit_num: Total number of bits.
    :param fraction_num: Number of fractional bits (N_f).
    :return: (q_value, err) - Quantized value and quantization error.
    """

    # 1. 計算整數位元數 (Int part bits, N_i = bit_num - fraction_num - 1)
    int_part = bit_num - fraction_num - 1
    
    # 2. 計算表示範圍 (Range)
    # Max positive value: 2^(N_i) - 2^(-N_f)
    range_pos = 2**int_part - 2**(-fraction_num)
    # Min negative value (Two's complement): -2^(N_i)
    range_neg = -2**int_part
    
    # Ensure input is a numpy array for vectorized operations
    input_value = np.asarray(input_value)
    
    # 3. 截斷 (向下取整，Truncation/floor towards negative infinity)
    # round_value = floor(input_value * (2^fraction_num))
    round_value = np.floor(input_value * (2**fraction_num))
    temp = round_value * (2**(-fraction_num))
    
    # 4. 飽和 (Saturation)
    # temp = arrayfun(@(x) min(x,range_pos),temp);
    # temp = arrayfun(@(x) max(x,range_neg),temp);
    q_value = np.minimum(temp, range_pos)
    q_value = np.maximum(q_value, range_neg)
    
    # 5. 誤差 (Error)
    err = input_value - q_value
    
    return q_value, err

# Example:
if __name__ == '__main__':
    test_value = np.array([1.5, -2.5, 3.999, -4.0, 5.0])
    q_value, err = quant(test_value, 16, 14)
    print(q_value)
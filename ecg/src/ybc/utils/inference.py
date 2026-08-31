import os

import torch
import torch.nn as nn
import numpy as np
from pathlib import Path

# ====================================================
# PyTorch Model Architecture
# ====================================================

class EventDrivenStage(nn.Module):
    def __init__(self):
        super().__init__()
        
        # --- Block 1 ---
        self.dw_conv1 = nn.Conv1d(2, 2, kernel_size=16, stride=1, dilation=2, padding='same', groups=1, bias=False)
        self.bn_dw1 = nn.BatchNorm1d(2)
        self.pool1 = nn.MaxPool1d(kernel_size=4, stride=4)
        self.pw_conv1 = nn.Conv1d(2, 32, kernel_size=1, stride=1)
        self.bn_pw1 = nn.BatchNorm1d(32)
        self.relu1 = nn.ReLU()
        
        # --- Block 2 ---
        self.dw_conv2 = nn.Conv1d(32, 32, kernel_size=8, stride=1, dilation=2, padding='same', groups=32, bias=False)
        self.bn_dw2 = nn.BatchNorm1d(32)
        self.pool2 = nn.MaxPool1d(kernel_size=2, stride=2)
        self.pw_conv2 = nn.Conv1d(32, 128, kernel_size=1, stride=1)
        self.bn_pw2 = nn.BatchNorm1d(128)
        self.relu2 = nn.ReLU()
        
        # --- Block 3 ---
        self.dw_conv3 = nn.Conv1d(128, 128, kernel_size=4, stride=1, dilation=2, padding='same', groups=128, bias=False)
        self.bn_dw3 = nn.BatchNorm1d(128)
        self.pool3 = nn.MaxPool1d(kernel_size=2, stride=2)
        self.pw_conv3 = nn.Conv1d(128, 256, kernel_size=1, stride=1)
        self.bn_pw3 = nn.BatchNorm1d(256)
        self.relu3 = nn.ReLU()
        
        self.gap = nn.AdaptiveAvgPool1d(1)
        self.gmp = nn.AdaptiveMaxPool1d(1)

    def forward(self, x):
        x = self.relu1(self.bn_pw1(self.pw_conv1(self.pool1(self.bn_dw1(self.dw_conv1(x))))))
        x = self.relu2(self.bn_pw2(self.pw_conv2(self.pool2(self.bn_dw2(self.dw_conv2(x))))))
        x = self.relu3(self.bn_pw3(self.pw_conv3(self.pool3(self.bn_dw3(self.dw_conv3(x))))))
        
        f_gap = self.gap(x).squeeze(2)
        f_gmp = self.gmp(x).squeeze(2)
        return torch.cat([f_gap, f_gmp], dim=1) 

class SmallCNN(nn.Module):
    def __init__(self, num_classes=3):
        super().__init__()
        self.stage1 = EventDrivenStage()
        self.visual_dim = 512
        self.classifier = nn.Sequential(
            nn.Linear(self.visual_dim, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, num_classes)
        )

    def forward(self, x):
        visual_features = self.stage1(x)
        logits = self.classifier(visual_features)
        return logits

# class LightweightBlock1D(nn.Module):
#     def __init__(self, in_channels, out_channels):
#         super().__init__()
#         
#         # Branch 1: Kernel = 3
#         self.branch_3 = nn.Sequential(
#             nn.Conv1d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
#             nn.BatchNorm1d(out_channels)
#         )
#         
#         # Branch 2: Kernel = 1
#         self.branch_1 = nn.Sequential(
#             nn.Conv1d(in_channels, out_channels, kernel_size=1, padding=0, bias=False),
#             nn.BatchNorm1d(out_channels)
#         )
#         
#         # Branch 3: Skip Connection (Identity)
#         if in_channels == out_channels:
#             self.identity = nn.BatchNorm1d(in_channels)
#         else:
#             self.identity = None
#             
#         self.relu = nn.ReLU()
# 
#     def forward(self, x):
#         # 1. Kernel 3 Path
#         out = self.branch_3(x)
#         # 2. Kernel 1 Path
#         out = out + self.branch_1(x)
#         # 3. Identity Path
#         if self.identity is not None:
#             out = out + self.identity(x)
#             
#         return self.relu(out)
# 
# # ====================================================
# # SmallCNN (Ultra-Lightweight < 10k params, More Layers)
# # ====================================================
# class SmallCNN(nn.Module):
#     def __init__(self, num_classes=3):
#         super().__init__()
#         
#         # --- Stage 1 ---
#         # Input: 2 channels. Expanding gradually to stay under 10k parameters.
#         self.layer0 = LightweightBlock1D(2, 8)
#         self.layer1 = LightweightBlock1D(8, 8)
#         # MaxPool layer replacing strided convs, limiting to 3 total pools
#         self.pool1 = nn.MaxPool1d(kernel_size=2, stride=2) 
#         
#         # --- Stage 2 ---
#         self.layer2 = LightweightBlock1D(8, 16)
#         self.layer3 = LightweightBlock1D(16, 16)
#         self.pool2 = nn.MaxPool1d(kernel_size=2, stride=2) 
#         
#         # --- Stage 3 ---
#         self.layer4 = LightweightBlock1D(16, 24)
#         self.layer5 = LightweightBlock1D(24, 24)
#         self.pool3 = nn.MaxPool1d(kernel_size=2, stride=2) 
#         
#         # --- Stage 4 ---
#         # Final block before global pooling (Length = 45 samples here)
#         self.layer6 = LightweightBlock1D(24, 24)
#         
#         # ====================================================
#         # Fusion & Classification
#         # ====================================================
#         self.gap = nn.AdaptiveAvgPool1d(1)
#         self.gmp = nn.AdaptiveMaxPool1d(1)
#         
#         # Fusing Global Average and Global Max (24 * 2 = 48 features)
#         self.visual_dim = 48 
#         
#         # Extremely minimal classifier to stay under 10k parameters total
#         self.classifier = nn.Sequential(
#             nn.Dropout(0.3),
#             nn.Linear(self.visual_dim, num_classes)
#         )
# 
#     def forward(self, x):
#         """
#         x: (Batch, 2, 360) - Signal + IR Channel
#         """
#         # Stage 1
#         x = self.layer0(x)
#         x = self.layer1(x)
#         x = self.pool1(x)
#         
#         # Stage 2
#         x = self.layer2(x)
#         x = self.layer3(x)
#         x = self.pool2(x)
#         
#         # Stage 3
#         x = self.layer4(x)
#         x = self.layer5(x)
#         x = self.pool3(x)
#         
#         # Stage 4
#         x = self.layer6(x)
#         
#         # Parallel Pooling
#         f_gap = self.gap(x).squeeze(2)
#         f_gmp = self.gmp(x).squeeze(2)
#         
#         # Concat and Classify
#         visual_features = torch.cat([f_gap, f_gmp], dim=1)
#         logits = self.classifier(visual_features)
#         
#         return logits

# ====================================================
# Inference Wrapper
# ====================================================

_model = None
_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def load_model():
    global _model
    if _model is None:
        default_weight_path = Path(__file__).resolve().parents[1] / "weight" / "icentia_mitbih_ds1_finetuned_73_93.pt"
        weight_path = Path(os.getenv("ECG_YBC_WEIGHT_PATH", str(default_weight_path))).expanduser()
#        weight_path = Path(__file__).resolve().parents[1] / "weight" / "icentia_only_171431.pt"
#        weight_path = Path(__file__).resolve().parents[1] / "weight" / "icentia_repvgg_8771.pt"
        _model = SmallCNN(num_classes=3) # Adjust num_classes if your weights file differs (e.g., 5 for N,S,V,F,Q)
        
        try:
            # Check if weights match class count. If weights are for 5 classes, change num_classes to 5.
            state_dict = torch.load(weight_path, map_location=_device)
            # Check last layer shape to auto-adjust num_classes
            if 'classifier.3.weight' in state_dict:
                num_out = state_dict['classifier.3.weight'].shape[0]
                if num_out != 3:
                    _model = SmallCNN(num_classes=num_out)
            
            _model.load_state_dict(state_dict)
            _model.to(_device)
            _model.eval()
            print(f"PyTorch model loaded successfully on {_device}")
        except Exception as e:
            print(f"Error loading model: {e}")
            raise e

def inference(two_channel_input):
    """
    two_channel_input: np.array of shape (2, 360)
    """
    load_model()
    
    with torch.no_grad():
        # Convert to tensor and add batch dimension (1, 2, 360)
        input_tensor = torch.from_numpy(two_channel_input).float().unsqueeze(0).to(_device)
        logits = _model(input_tensor)
        probs = torch.softmax(logits, dim=1)
        prediction = torch.argmax(probs, dim=1).item()
        
    return prediction


def inference_with_probabilities(two_channel_input):
    """
    two_channel_input: np.array of shape (2, 360)
    returns: (prediction, probabilities)
    """
    load_model()

    with torch.no_grad():
        input_tensor = torch.from_numpy(two_channel_input).float().unsqueeze(0).to(_device)
        logits = _model(input_tensor)
        probs = torch.softmax(logits, dim=1).detach().cpu().numpy()[0]
        prediction = int(np.argmax(probs))

    return prediction, probs.tolist()


def batch_inference_with_probabilities(batch_input):
    """
    batch_input: np.array of shape (N, 2, 360)
    returns: (predictions, probabilities)
    """
    load_model()

    with torch.no_grad():
        input_tensor = torch.from_numpy(batch_input).float().to(_device)
        logits = _model(input_tensor)
        probs = torch.softmax(logits, dim=1).detach().cpu().numpy()
        predictions = np.argmax(probs, axis=1).astype(int)

    return predictions.tolist(), probs.tolist()

"""
Shared model + preprocessing for the item-icon classifier, so train_cls.py and
cls.py stay byte-identical on architecture and normalization.

Backbone: MobileNetV3-small pretrained on ImageNet (its low-level features are
already robust to blur/tint, so it converges in a few CPU epochs where a
from-scratch net stalls), with a fresh linear head over the icon classes.
"""
import torch
import torch.nn as nn
import numpy as np
from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights

INPUT = 96                       # square classifier input
MEAN = np.array([0.485, 0.456, 0.406], np.float32)   # ImageNet
STD = np.array([0.229, 0.224, 0.225], np.float32)


def to_tensor(pil):
    """PIL RGB -> normalized CHW float tensor at INPUT x INPUT (aspect squashed;
    footprint is handled separately by masking the logits)."""
    a = np.asarray(pil.convert("RGB").resize((INPUT, INPUT)), np.float32) / 255.0
    a = (a - MEAN) / STD
    return torch.from_numpy(a.transpose(2, 0, 1).copy())


class IconNet(nn.Module):
    def __init__(self, nclasses, pretrained=True):
        super().__init__()
        w = MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
        m = mobilenet_v3_small(weights=w)
        self.features = m.features
        self.avgpool = m.avgpool
        self.head = nn.Sequential(
            nn.Flatten(), nn.Linear(576, 512), nn.Hardswish(),
            nn.Dropout(0.2), nn.Linear(512, nclasses))

    def forward(self, x):
        return self.head(self.avgpool(self.features(x)))

"""
效果模組：Ken Burns（橫向運鏡）與 Zoom（縮放），設計為可抽換的策略字典。

新增自訂效果：
  1. 在 KEN_BURNS_STRATEGIES 或 ZOOM_STRATEGIES 加入新 key 與 lambda
  2. 在 base_config.yaml 修改 ken_burns_strategy / zoom_strategy 為新 key
"""
import cv2
import numpy as np
from pathlib import Path
from PIL import Image

# =====================================================================
# 策略字典（可抽換）
# =====================================================================

KEN_BURNS_STRATEGIES = {
    "alternate_lr":       lambda scene_idx: "left_to_right" if scene_idx % 2 == 0 else "right_to_left",
    "all_left_to_right":  lambda scene_idx: "left_to_right",
    "all_right_to_left":  lambda scene_idx: "right_to_left",
}

ZOOM_STRATEGIES = {
    "alternate":  lambda scene_idx: "zoom_in" if scene_idx % 2 == 0 else "zoom_out",
    "zoom_in":    lambda scene_idx: "zoom_in",
    "zoom_out":   lambda scene_idx: "zoom_out",
}

# =====================================================================
# 圖片載入與縮放
# =====================================================================

def detect_aspect(image_path: Path) -> str:
    """回傳 '16:9'、'9:16' 或 'other'。"""
    img = Image.open(image_path)
    w, h = img.size
    ratio = w / h
    if ratio > 1.5:
        return "16:9"
    elif ratio < 0.7:
        return "9:16"
    return "other"


def load_image_rgb(image_path: Path) -> np.ndarray:
    """載入圖片並確保回傳 uint8 RGB numpy array（去除 Alpha channel）。"""
    img = Image.open(image_path).convert("RGB")
    return np.array(img)


def scale_16x9(image_np: np.ndarray, canvas_h: int) -> np.ndarray:
    """
    縮放 16:9 圖片使高度 = canvas_h，寬度按比例放大（會超出 canvas 寬度）。
    回傳寬度 > canvas_w 的大圖，供 Ken Burns 水平裁切。
    """
    h, w = image_np.shape[:2]
    new_h = canvas_h
    new_w = int(w * canvas_h / h)
    return cv2.resize(image_np, (new_w, new_h), interpolation=cv2.INTER_LINEAR)


def scale_9x16(image_np: np.ndarray, canvas_w: int, canvas_h: int) -> np.ndarray:
    """縮放 9:16 圖片至恰好填滿畫布。"""
    return cv2.resize(image_np, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)

# =====================================================================
# 逐幀效果函數
# =====================================================================

def make_ken_burns_frame(
    image_np: np.ndarray,
    t: float,
    duration: float,
    direction: str,
    canvas_w: int,
    canvas_h: int,
) -> np.ndarray:
    """
    從寬於 canvas 的 16:9 大圖中，依時間 t 裁出 canvas_w x canvas_h 的視窗。
    direction: 'left_to_right' 或 'right_to_left'
    """
    max_offset = max(0, image_np.shape[1] - canvas_w)
    progress = t / duration if direction == "left_to_right" else 1.0 - t / duration
    x = int(np.clip(progress * max_offset, 0, max_offset))
    return image_np[:, x:x + canvas_w]


def make_zoom_frame(
    image_np: np.ndarray,
    t: float,
    duration: float,
    direction: str,
    canvas_w: int,
    canvas_h: int,
) -> np.ndarray:
    """
    對已縮放至 canvas 大小的 9:16 圖片套用中心縮放效果。
    zoom_in: 1.0x → 1.1x（逐漸放大）
    zoom_out: 1.1x → 1.0x（逐漸縮小）
    """
    progress = t / duration
    scale = (1.0 + 0.1 * progress) if direction == "zoom_in" else (1.1 - 0.1 * progress)

    crop_w = int(canvas_w / scale)
    crop_h = int(canvas_h / scale)
    x = (canvas_w - crop_w) // 2
    y = (canvas_h - crop_h) // 2

    cropped = image_np[y:y + crop_h, x:x + crop_w]
    return cv2.resize(cropped, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)

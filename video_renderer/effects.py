"""
效果模組：Ken Burns（水平/垂直運鏡）與 Zoom（縮放）。

效果選擇邏輯（ratio-aware）：
  圖片比畫布寬 → Ken Burns 水平
  圖片比畫布窄 → Ken Burns 垂直
  比例相近     → Zoom

新增自訂效果：
  在對應的 STRATEGIES dict 加入新 key 與 lambda，
  再於 base_config.yaml 修改對應的 strategy 欄位。
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

KEN_BURNS_V_STRATEGIES = {
    "alternate_tb":       lambda scene_idx: "top_to_bottom" if scene_idx % 2 == 0 else "bottom_to_top",
    "all_top_to_bottom":  lambda scene_idx: "top_to_bottom",
    "all_bottom_to_top":  lambda scene_idx: "bottom_to_top",
}

ZOOM_STRATEGIES = {
    "alternate":  lambda scene_idx: "zoom_in" if scene_idx % 2 == 0 else "zoom_out",
    "zoom_in":    lambda scene_idx: "zoom_in",
    "zoom_out":   lambda scene_idx: "zoom_out",
}

# =====================================================================
# 效果類型判斷
# =====================================================================

def get_effect_type(image_path: Path, canvas_w: int, canvas_h: int, threshold: float = 0.15) -> str:
    """
    比較圖片比例與畫布比例，回傳應套用的效果類型：
      'ken_burns_h' — 圖比畫布寬，水平移動
      'ken_burns_v' — 圖比畫布窄，垂直移動
      'zoom'        — 比例相近，縮放
    """
    img = Image.open(image_path)
    img_ratio = img.width / img.height
    canvas_ratio = canvas_w / canvas_h
    if img_ratio > canvas_ratio + threshold:
        return "ken_burns_h"
    elif img_ratio < canvas_ratio - threshold:
        return "ken_burns_v"
    return "zoom"

# =====================================================================
# 圖片載入與縮放
# =====================================================================

def load_image_rgb(image_path: Path) -> np.ndarray:
    """載入圖片並確保回傳 uint8 RGB numpy array（去除 Alpha channel）。"""
    img = Image.open(image_path).convert("RGB")
    return np.array(img)


def scale_to_cover(image_np: np.ndarray, canvas_w: int, canvas_h: int) -> np.ndarray:
    """
    縮放圖片使兩個維度都 >= 畫布大小（cover，不留黑邊）。
    用於 Ken Burns 效果，縮放後可水平或垂直裁切。
    """
    h, w = image_np.shape[:2]
    scale = max(canvas_w / w, canvas_h / h)
    new_w = max(canvas_w, int(w * scale))
    new_h = max(canvas_h, int(h * scale))
    return cv2.resize(image_np, (new_w, new_h), interpolation=cv2.INTER_LINEAR)


def scale_to_fit(image_np: np.ndarray, canvas_w: int, canvas_h: int) -> np.ndarray:
    """縮放圖片至恰好填滿畫布（用於 Zoom 效果）。"""
    return cv2.resize(image_np, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)


# ── 向後相容別名 ───────────────────────────────────────────────────────
def detect_aspect(image_path: Path) -> str:
    """舊版比例偵測，保留相容性。新程式碼請用 get_effect_type()。"""
    img = Image.open(image_path)
    ratio = img.width / img.height
    if ratio > 1.5:
        return "16:9"
    elif ratio < 0.7:
        return "9:16"
    return "other"

def scale_16x9(image_np: np.ndarray, canvas_h: int) -> np.ndarray:
    h, w = image_np.shape[:2]
    new_w = int(w * canvas_h / h)
    return cv2.resize(image_np, (new_w, canvas_h), interpolation=cv2.INTER_LINEAR)

def scale_9x16(image_np: np.ndarray, canvas_w: int, canvas_h: int) -> np.ndarray:
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
    水平 Ken Burns：從 scale_to_cover 的大圖中依時間裁出 canvas_w×canvas_h 視窗。
    direction: 'left_to_right' 或 'right_to_left'
    """
    max_x = max(0, image_np.shape[1] - canvas_w)
    progress = t / duration if direction == "left_to_right" else 1.0 - t / duration
    x = int(np.clip(progress * max_x, 0, max_x))
    y_off = max(0, (image_np.shape[0] - canvas_h) // 2)
    return image_np[y_off:y_off + canvas_h, x:x + canvas_w]


def make_ken_burns_v_frame(
    image_np: np.ndarray,
    t: float,
    duration: float,
    direction: str,
    canvas_w: int,
    canvas_h: int,
) -> np.ndarray:
    """
    垂直 Ken Burns：從 scale_to_cover 的大圖中依時間裁出 canvas_w×canvas_h 視窗（上下移動）。
    direction: 'top_to_bottom' 或 'bottom_to_top'
    用於圖片比畫布窄的情況（如 9:16 圖在 16:9 畫布）。
    """
    max_y = max(0, image_np.shape[0] - canvas_h)
    progress = t / duration if direction == "top_to_bottom" else 1.0 - t / duration
    y = int(np.clip(progress * max_y, 0, max_y))
    x_off = max(0, (image_np.shape[1] - canvas_w) // 2)
    return image_np[y:y + canvas_h, x_off:x_off + canvas_w]


def make_zoom_frame(
    image_np: np.ndarray,
    t: float,
    duration: float,
    direction: str,
    canvas_w: int,
    canvas_h: int,
    zoom_amount: float = 0.1,
) -> np.ndarray:
    """
    對已縮放至 canvas 大小的圖片套用中心縮放效果。
    zoom_in:  1.0x → (1.0 + zoom_amount)x
    zoom_out: (1.0 + zoom_amount)x → 1.0x
    """
    progress = t / duration
    peak = 1.0 + zoom_amount
    scale = (1.0 + zoom_amount * progress) if direction == "zoom_in" else (peak - zoom_amount * progress)

    crop_w = int(canvas_w / scale)
    crop_h = int(canvas_h / scale)
    x = (canvas_w - crop_w) // 2
    y = (canvas_h - crop_h) // 2

    cropped = image_np[y:y + crop_h, x:x + crop_w]
    return cv2.resize(cropped, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)

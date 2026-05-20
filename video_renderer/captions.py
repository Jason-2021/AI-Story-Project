"""
字幕渲染模組。
使用 PIL 在 numpy frame 上繪製分組高亮字幕。
"""
import platform
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from typing import List, Any


def load_font(font_size: int) -> ImageFont.FreeTypeFont:
    """依作業系統尋找粗體字型，找不到則 fallback 至預設字型。"""
    system = platform.system()
    candidates = {
        "Windows": [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ],
        "Darwin": [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ],
        "Linux": [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ],
    }
    for path in candidates.get(system, []):
        try:
            return ImageFont.truetype(path, font_size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def group_words(timestamps: List[Any], words_per_group: int) -> List[List[Any]]:
    """將逐字時間戳分成每組 N 個字的陣列。"""
    return [timestamps[i:i + words_per_group] for i in range(0, len(timestamps), words_per_group)]


def _find_active(word_groups: List[List[Any]], t: float):
    """
    回傳 (active_group, active_word_idx)。
    找不到則回傳 (None, -1)。
    """
    for group in word_groups:
        if not group:
            continue
        if group[0].start <= t <= group[-1].end:
            # 找當前說到的字（最近一個 start <= t 的 word）
            active_idx = 0
            for i, word in enumerate(group):
                if word.start <= t:
                    active_idx = i
            return group, active_idx
    return None, -1


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def render_captions(
    frame: np.ndarray,
    t: float,
    word_groups: List[List[Any]],
    canvas_w: int,
    canvas_h: int,
    font: ImageFont.FreeTypeFont,
    position_y_ratio: float,
    highlight_color: str,
    uppercase: bool = False,
) -> np.ndarray:
    """
    在 frame 上疊加字幕，當前說的字高亮。
    frame: uint8 HxWx3 numpy array
    uppercase: 由 base_config.yaml 的 caption_uppercase 控制
    回傳: 同格式 numpy array
    """
    active_group, active_idx = _find_active(word_groups, t)
    if active_group is None:
        return frame

    img = Image.fromarray(frame)
    draw = ImageDraw.Draw(img)

    words = [w.word.upper() if uppercase else w.word for w in active_group]
    highlight_rgb = _hex_to_rgb(highlight_color)
    stroke = max(2, int(font.size * 0.05))

    # 計算每個字的寬度
    space_w = draw.textlength(" ", font=font)
    word_widths = [draw.textlength(w, font=font) for w in words]
    total_w = sum(word_widths) + space_w * (len(words) - 1)

    x = int((canvas_w - total_w) / 2)
    y = int(canvas_h * position_y_ratio)

    for i, (word, width) in enumerate(zip(words, word_widths)):
        color = highlight_rgb if i == active_idx else (255, 255, 255)
        # 描邊（黑色）
        for dx, dy in [(-stroke, -stroke), (-stroke, stroke), (stroke, -stroke), (stroke, stroke)]:
            draw.text((x + dx, y + dy), word, font=font, fill=(0, 0, 0))
        # 主要文字
        draw.text((x, y), word, font=font, fill=color)
        x += int(width + space_w)

    return np.array(img)

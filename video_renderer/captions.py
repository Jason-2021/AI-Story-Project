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


def _split_into_lines(
    words: List[str],
    word_widths: List[float],
    space_w: float,
    max_w: float,
) -> List[tuple]:
    """
    將一組字依像素寬度切成多行，每行不超過 max_w。
    回傳 list of (line_words, line_widths, start_idx)。
    start_idx 為該行第一個字在原始 words 中的索引，供 karaoke 高亮使用。
    """
    lines: List[tuple] = []
    cur_words: List[str] = []
    cur_widths: List[float] = []
    cur_w = 0.0
    line_start_idx = 0

    for i, (word, width) in enumerate(zip(words, word_widths)):
        needed = cur_w + (space_w if cur_words else 0) + width
        if needed > max_w and cur_words:
            lines.append((cur_words, cur_widths, line_start_idx))
            cur_words = [word]
            cur_widths = [width]
            cur_w = width
            line_start_idx = i
        else:
            cur_words.append(word)
            cur_widths.append(width)
            cur_w = needed

    if cur_words:
        lines.append((cur_words, cur_widths, line_start_idx))

    return lines


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
    max_width_ratio: float = 0.9,
) -> np.ndarray:
    """
    在 frame 上疊加字幕，當前說的字高亮。
    若字幕寬度超過 canvas_w * max_width_ratio，自動換行。
    frame: uint8 HxWx3 numpy array
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
    space_w = draw.textlength(" ", font=font)
    word_widths = [draw.textlength(w, font=font) for w in words]

    max_w = canvas_w * max_width_ratio
    lines = _split_into_lines(words, word_widths, space_w, max_w)

    line_height = font.size * 1.2
    block_h = len(lines) * line_height
    start_y = int(canvas_h * position_y_ratio - block_h / 2)

    for line_words, line_widths, line_start_idx in lines:
        line_total_w = sum(line_widths) + space_w * (len(line_words) - 1)
        x = int((canvas_w - line_total_w) / 2)
        y = start_y

        for i, (word, width) in enumerate(zip(line_words, line_widths)):
            global_idx = line_start_idx + i
            color = highlight_rgb if global_idx == active_idx else (255, 255, 255)
            for dx, dy in [(-stroke, -stroke), (-stroke, stroke), (stroke, -stroke), (stroke, stroke)]:
                draw.text((x + dx, y + dy), word, font=font, fill=(0, 0, 0))
            draw.text((x, y), word, font=font, fill=color)
            x += int(width + space_w)

        start_y += int(line_height)

    return np.array(img)

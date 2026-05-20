"""
Long-form video merger.

Concatenates N episode MP4s (with optional title cards) into a single
long-form video at workspace/{series_id}/long_form/output.mp4.
"""
import json
import platform
import numpy as np
from pathlib import Path
from typing import List, Optional

from core import series_state_manager

WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"


def merge_episodes(
    series_run_id: str,
    episode_run_ids: List[str],
    add_title_cards: bool = True,
    transition: str = "fade_black",
) -> Path:
    """
    Merges N episode videos into one long-form video.
    Lazy-imports moviepy to avoid startup cost on arc-only runs.
    """
    from moviepy import VideoFileClip, concatenate_videoclips

    series_dir = series_state_manager.get_series_dir(series_run_id)
    arc_data = series_state_manager.load_series_arc_json(series_run_id)
    output_path = series_dir / "long_form" / "output.mp4"
    temp_audio = series_dir / "long_form" / "temp_audio.m4a"

    print(f"\n🎞️  [Merger] 合併 {len(episode_run_ids)} 集 → 長影片")

    clips = []
    for i, ep_run_id in enumerate(episode_run_ids):
        ep_video_path = WORKSPACE_DIR / ep_run_id / "video" / "output.mp4"
        if not ep_video_path.exists():
            raise FileNotFoundError(
                f"[Merger] 找不到 Episode {i + 1} 影片：{ep_video_path}\n"
                f"請先完成所有集數的生成再合併。"
            )

        episode_clip = VideoFileClip(str(ep_video_path))

        if add_title_cards and arc_data and i < len(arc_data.get("episodes", [])):
            ep_info = arc_data["episodes"][i]
            title_text = ep_info.get("episode_title", f"Episode {i + 1}")
            title_card = _make_title_card(title_text, episode_clip.w, episode_clip.h, duration=3.0)
            clips.append(title_card)

        clips.append(episode_clip)
        print(f"  ✅ [Merger] Episode {i + 1} 載入完成")

    final = concatenate_videoclips(clips, method="compose")
    print(f"\n📦 [Merger] 匯出長影片中…")
    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(temp_audio),
        remove_temp=True,
        threads=4,
        logger="bar",
    )
    final.close()
    for c in clips:
        c.close()

    print(f"✅ [Merger] 長影片完成：{output_path}")
    return output_path


def _make_title_card(title: str, width: int, height: int, duration: float = 3.0):
    """
    Creates a static black-background title card using PIL + numpy,
    consistent with the existing caption rendering approach.
    """
    from moviepy import VideoClip
    from PIL import Image, ImageDraw

    from video_renderer.captions import load_font

    font_size = max(60, height // 24)
    font = load_font(font_size)

    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    max_text_width = int(width * 0.85)
    words = title.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_text_width or not current_line:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    line_height = font_size * 1.3
    total_h = line_height * len(lines)
    start_y = (height - total_h) / 2

    for line_idx, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        y = int(start_y + line_idx * line_height)
        draw.text((x, y), line, fill=(255, 255, 255), font=font)

    frame = np.array(img)
    return VideoClip(lambda t, f=frame: f, duration=duration).with_fps(24)

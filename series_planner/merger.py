"""
Long-form video merger.

重新讀取每集的 images/ + audio/ 資料夾，用 16:9 畫布（1920×1080）重新渲染，
輸出至 workspace/{series_id}/long_form/output.mp4。

效果由每張圖片的實際比例 vs 16:9 畫布自動決定（ratio-aware）：
  16:9 圖 + 16:9 畫布 → Zoom
  9:16 圖 + 16:9 畫布 → Ken Burns 垂直
  1:1  圖 + 16:9 畫布 → Ken Burns 垂直（輕微）
"""
from pathlib import Path
from typing import List

from video_renderer.engine import render_longform


def merge_episodes(
    series_run_id: str,
    episode_run_ids: List[str],
    add_title_cards: bool = True,
    transition: str = "fade_black",
) -> Path:
    """
    Merges N episodes into one long-form video by re-rendering on a 16:9 canvas.
    The `transition` parameter is kept for API compatibility but the actual
    transition is read from long_form_renderer.transition in base_config.yaml.
    """
    return render_longform(
        series_id=series_run_id,
        ep_run_ids=episode_run_ids,
        add_title_cards=add_title_cards,
    )

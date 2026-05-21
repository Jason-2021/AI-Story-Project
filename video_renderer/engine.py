"""
Video Renderer 主引擎。
從 workspace 讀取 script、images、audio_results，合成並輸出 MP4。

render_video()     — 短影音（9:16），讀 video_renderer 設定
render_longform()  — 長影音（16:9），讀 long_form_renderer 設定，重新渲染每集
"""
import json
import yaml
from pathlib import Path
from typing import List

import numpy as np
from moviepy import VideoClip, AudioFileClip, concatenate_videoclips

from .effects import (
    KEN_BURNS_STRATEGIES, KEN_BURNS_V_STRATEGIES, ZOOM_STRATEGIES,
    get_effect_type, load_image_rgb,
    scale_to_cover, scale_to_fit,
    make_ken_burns_frame, make_ken_burns_v_frame, make_zoom_frame,
)
from .captions import load_font, group_words, render_captions
from .transitions import TRANSITION_REGISTRY

CONFIG_DIR = Path(__file__).parent.parent / "configs"


# =====================================================================
# 設定讀取
# =====================================================================

def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_settings(section: str = "video_renderer") -> dict:
    raw = _load_yaml(CONFIG_DIR / "base_config.yaml")
    base = raw.get("video_renderer", {})
    if section == "video_renderer":
        return base
    # long_form_renderer 覆蓋 video_renderer，字幕等未設定的欄位繼承
    return {**base, **raw.get(section, {})}


# =====================================================================
# 標題卡
# =====================================================================

def _make_title_card(title: str, width: int, height: int, duration: float = 3.0) -> VideoClip:
    """黑底白字標題卡，用 PIL 渲染後轉成靜態 VideoClip。"""
    from PIL import Image, ImageDraw

    font_size = max(60, height // 24)
    font = load_font(font_size)

    img = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    max_text_width = int(width * 0.85)
    words = title.split()
    lines, current_line = [], []
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

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        y = int(start_y + i * line_height)
        draw.text((x, y), line, fill=(255, 255, 255), font=font)

    frame = np.array(img)
    return VideoClip(lambda t, f=frame: f, duration=duration).with_fps(24)


# =====================================================================
# 場景 Clip 建構
# =====================================================================

def _build_scene_clip(
    scene_idx: int,
    image_path: Path,
    audio_path: Path,
    word_timestamps: list,
    settings: dict,
) -> VideoClip:
    """
    建立單一 scene 的 VideoClip（含 Ken Burns/Zoom 效果 + 字幕 + 音訊）。
    效果類型由圖片比例 vs 畫布比例自動決定（ratio-aware）。
    """
    canvas_w   = settings.get("canvas_width", 1080)
    canvas_h   = settings.get("canvas_height", 1920)
    fps        = settings.get("fps", 24)
    n_words    = settings.get("caption_words_per_group", 3)
    pos_y      = settings.get("caption_position_y_ratio", 0.65)
    font_size  = settings.get("caption_font_size", 100)
    hi_color   = settings.get("caption_highlight_color", "#FFD700")
    uppercase  = settings.get("caption_uppercase", False)
    max_w_ratio = settings.get("caption_max_width_ratio", 0.9)
    kb_strat   = settings.get("ken_burns_strategy", "alternate_lr")
    kb_v_strat = settings.get("ken_burns_v_strategy", "alternate_tb")
    zm_strat   = settings.get("zoom_strategy", "alternate")
    zoom_amt   = settings.get("zoom_amount", 0.1)

    audio_clip = AudioFileClip(str(audio_path))
    duration   = audio_clip.duration

    raw_np = load_image_rgb(image_path)
    effect = get_effect_type(image_path, canvas_w, canvas_h)

    if effect == "ken_burns_h":
        scaled_np = scale_to_cover(raw_np, canvas_w, canvas_h)
        direction = KEN_BURNS_STRATEGIES[kb_strat](scene_idx)
        def _get_frame(t, _img=scaled_np, _dur=duration, _dir=direction):
            return make_ken_burns_frame(_img, t, _dur, _dir, canvas_w, canvas_h)

    elif effect == "ken_burns_v":
        scaled_np = scale_to_cover(raw_np, canvas_w, canvas_h)
        direction = KEN_BURNS_V_STRATEGIES[kb_v_strat](scene_idx)
        def _get_frame(t, _img=scaled_np, _dur=duration, _dir=direction):
            return make_ken_burns_v_frame(_img, t, _dur, _dir, canvas_w, canvas_h)

    else:  # zoom
        scaled_np = scale_to_fit(raw_np, canvas_w, canvas_h)
        direction = ZOOM_STRATEGIES[zm_strat](scene_idx)
        def _get_frame(t, _img=scaled_np, _dur=duration, _dir=direction, _za=zoom_amt):
            return make_zoom_frame(_img, t, _dur, _dir, canvas_w, canvas_h, _za)

    font        = load_font(font_size)
    word_groups = group_words(word_timestamps, n_words)

    def make_frame(t,
                   _get=_get_frame,
                   _groups=word_groups,
                   _font=font,
                   _cw=canvas_w, _ch=canvas_h,
                   _py=pos_y, _hc=hi_color, _uc=uppercase, _mw=max_w_ratio):
        frame = _get(t)
        frame = render_captions(frame, t, _groups, _cw, _ch, _font, _py, _hc, _uc, _mw)
        return frame

    clip = VideoClip(make_frame, duration=duration).with_fps(fps)
    clip = clip.with_audio(audio_clip)
    return clip


# =====================================================================
# 短影音渲染
# =====================================================================

def render_video(run_id: str) -> Path:
    """
    從 workspace/{run_id} 讀取所有素材，輸出 MP4 至 workspace/{run_id}/video/output.mp4。
    使用 video_renderer 設定（預設 9:16 畫布）。
    """
    from core import state_manager
    from text_generator.llm_router import VideoScript

    settings = _get_settings("video_renderer")
    transition_name = settings.get("transition", "hard_cut")

    workspace_dir = state_manager.WORKSPACE_DIR / run_id
    script = VideoScript.model_validate_json(
        (workspace_dir / "script.json").read_text(encoding="utf-8")
    )
    raw_audio = json.loads(
        (workspace_dir / "audio" / "audio_results.json").read_text(encoding="utf-8")
    )
    audio_by_scene = {item["scene_id"]: item for item in raw_audio}

    print(f"\n🎬 [Renderer] 開始渲染 | {len(script.scenes)} 個場景 | 轉場: {transition_name}")

    clips = []
    for i, scene in enumerate(script.scenes):
        sid = scene.scene_id
        image_path = workspace_dir / "images" / f"scene_{sid:02d}.png"
        audio_data = audio_by_scene[sid]
        audio_path = Path(audio_data["file_path"])
        timestamps = [
            type("W", (), {"word": w["word"], "start": w["start"], "end": w["end"]})()
            for w in audio_data["timestamps"]
        ]
        print(f"  🖼️  [Scene {sid}] 建立 clip...")
        clips.append(_build_scene_clip(i, image_path, audio_path, timestamps, settings))

    if transition_name in TRANSITION_REGISTRY:
        clips = TRANSITION_REGISTRY[transition_name](clips)
    else:
        print(f"⚠️  未知轉場 '{transition_name}'，使用 hard_cut。")

    final_clip = concatenate_videoclips(clips, method="compose")

    video_dir = state_manager.get_video_dir(run_id)
    output_path = video_dir / "output.mp4"
    temp_audio  = video_dir / "temp_audio.m4a"

    print(f"\n📦 [Renderer] 匯出中：{output_path}")
    final_clip.write_videofile(
        str(output_path),
        fps=settings.get("fps", 24),
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(temp_audio),
        remove_temp=True,
        threads=4,
        logger="bar",
    )

    final_clip.close()
    for c in clips:
        c.close()

    print(f"✅ [Renderer] 完成！輸出：{output_path}")
    return output_path


# =====================================================================
# 長影音渲染
# =====================================================================

def render_longform(
    series_id: str,
    ep_run_ids: List[str],
    add_title_cards: bool = True,
) -> Path:
    """
    重新讀取每集的 images/ + audio/ 資料夾，用 16:9 畫布渲染後合併為長影片。
    效果由每張圖片的實際比例 vs 畫布比例自動決定（ratio-aware）。
    使用 long_form_renderer 設定（覆蓋自 video_renderer）。
    """
    from core import series_state_manager, state_manager
    from text_generator.llm_router import VideoScript

    settings = _get_settings("long_form_renderer")
    canvas_w = settings.get("canvas_width", 1920)
    canvas_h = settings.get("canvas_height", 1080)
    transition_name = settings.get("transition", "fade_black")

    arc_data = series_state_manager.load_series_arc_json(series_id)
    series_dir = series_state_manager.get_series_dir(series_id)
    output_dir = series_dir / "long_form"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "output.mp4"
    temp_audio_path = output_dir / "temp_audio.m4a"

    print(f"\n🎞️  [LongForm] 重新渲染 {len(ep_run_ids)} 集 → {canvas_w}×{canvas_h} 長影片")

    all_clips = []
    global_scene_idx = 0

    for i, ep_run_id in enumerate(ep_run_ids):
        workspace_dir = state_manager.WORKSPACE_DIR / ep_run_id

        script = VideoScript.model_validate_json(
            (workspace_dir / "script.json").read_text(encoding="utf-8")
        )
        raw_audio = json.loads(
            (workspace_dir / "audio" / "audio_results.json").read_text(encoding="utf-8")
        )
        audio_by_scene = {item["scene_id"]: item for item in raw_audio}

        if add_title_cards and arc_data and i < len(arc_data.get("episodes", [])):
            title_text = arc_data["episodes"][i].get("episode_title", f"Episode {i + 1}")
            all_clips.append(_make_title_card(title_text, canvas_w, canvas_h, duration=3.0))

        for scene in script.scenes:
            sid = scene.scene_id
            image_path = workspace_dir / "images" / f"scene_{sid:02d}.png"
            audio_data = audio_by_scene[sid]
            audio_path = Path(audio_data["file_path"])
            timestamps = [
                type("W", (), {"word": w["word"], "start": w["start"], "end": w["end"]})()
                for w in audio_data["timestamps"]
            ]
            all_clips.append(
                _build_scene_clip(global_scene_idx, image_path, audio_path, timestamps, settings)
            )
            global_scene_idx += 1

        print(f"  ✅ [LongForm] Episode {i + 1} ({len(script.scenes)} 場景) 已建立")

    if transition_name in TRANSITION_REGISTRY:
        all_clips = TRANSITION_REGISTRY[transition_name](all_clips)

    final_clip = concatenate_videoclips(all_clips, method="compose")

    print(f"\n📦 [LongForm] 匯出中：{output_path}")
    final_clip.write_videofile(
        str(output_path),
        fps=settings.get("fps", 24),
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(temp_audio_path),
        remove_temp=True,
        threads=4,
        logger="bar",
    )

    final_clip.close()
    for c in all_clips:
        c.close()

    print(f"✅ [LongForm] 長影片完成：{output_path}")
    return output_path


# =====================================================================
# 測試區塊（從專案根目錄執行：python -m video_renderer.engine）
# =====================================================================
if __name__ == "__main__":
    from core import state_manager

    run_id = state_manager.get_latest_run_id()
    if not run_id:
        print("❌ 找不到任何 run，請先執行其他模組生成素材。")
    elif state_manager.get_stage_status(run_id, "video") == "completed":
        print(f"⚡ [快取] 影片已渲染完成，路徑：workspace/{run_id}/video/output.mp4")
    else:
        state_manager.mark_stage(run_id, "video", "in_progress")
        output = render_video(run_id)
        state_manager.mark_stage(run_id, "video", "completed")
        print(f"\n🎉 影片已儲存：{output}")

"""
Video Renderer 主引擎。
從 workspace 讀取 script、images、audio_results，合成並輸出 MP4。
"""
import json
import yaml
from pathlib import Path

import numpy as np
from moviepy import VideoClip, AudioFileClip, concatenate_videoclips

from .effects import (
    KEN_BURNS_STRATEGIES, ZOOM_STRATEGIES,
    detect_aspect, load_image_rgb,
    scale_16x9, scale_9x16,
    make_ken_burns_frame, make_zoom_frame,
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


def _get_settings() -> dict:
    return _load_yaml(CONFIG_DIR / "base_config.yaml").get("video_renderer", {})


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
    使用 factory 函數閉包，確保每個 scene 的變數各自獨立。
    """
    canvas_w   = settings.get("canvas_width", 1080)
    canvas_h   = settings.get("canvas_height", 1920)
    fps        = settings.get("fps", 24)
    n_words    = settings.get("caption_words_per_group", 3)
    pos_y      = settings.get("caption_position_y_ratio", 0.65)
    font_size  = settings.get("caption_font_size", 100)
    hi_color   = settings.get("caption_highlight_color", "#FFD700")
    uppercase  = settings.get("caption_uppercase", False)
    kb_strat   = settings.get("ken_burns_strategy", "alternate_lr")
    zm_strat   = settings.get("zoom_strategy", "alternate")
    zoom_amt   = settings.get("zoom_amount", 0.1)

    audio_clip = AudioFileClip(str(audio_path))
    duration   = audio_clip.duration

    # 載入圖片與決定效果
    raw_np = load_image_rgb(image_path)
    aspect = detect_aspect(image_path)

    if aspect == "16:9":
        scaled_np = scale_16x9(raw_np, canvas_h)
        direction = KEN_BURNS_STRATEGIES[kb_strat](scene_idx)
        def _get_frame(t, _img=scaled_np, _dur=duration, _dir=direction):
            return make_ken_burns_frame(_img, t, _dur, _dir, canvas_w, canvas_h)

    elif aspect == "9:16":
        scaled_np = scale_9x16(raw_np, canvas_w, canvas_h)
        direction = ZOOM_STRATEGIES[zm_strat](scene_idx)
        def _get_frame(t, _img=scaled_np, _dur=duration, _dir=direction, _za=zoom_amt):
            return make_zoom_frame(_img, t, _dur, _dir, canvas_w, canvas_h, _za)

    else:
        # Fallback: 靜態填滿畫布
        import cv2
        static = cv2.resize(raw_np, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)
        def _get_frame(t, _img=static):
            return _img.copy()

    # 字幕準備
    font       = load_font(font_size)
    word_groups = group_words(word_timestamps, n_words)

    def make_frame(t,
                   _get=_get_frame,
                   _groups=word_groups,
                   _font=font,
                   _cw=canvas_w, _ch=canvas_h,
                   _py=pos_y, _hc=hi_color, _uc=uppercase):
        frame = _get(t)
        frame = render_captions(frame, t, _groups, _cw, _ch, _font, _py, _hc, _uc)
        return frame

    clip = VideoClip(make_frame, duration=duration).with_fps(fps)
    clip = clip.with_audio(audio_clip)
    return clip


# =====================================================================
# 主渲染函數
# =====================================================================

def render_video(run_id: str) -> Path:
    """
    從 workspace/{run_id} 讀取所有素材，輸出 MP4 至 workspace/{run_id}/video/output.mp4。
    """
    from core import state_manager
    from text_generator.llm_router import VideoScript
    from audio_generator.audio_router import AudioResult, WordTimestamp

    settings = _get_settings()
    transition_name = settings.get("transition", "hard_cut")

    # 讀取 workspace 資料
    workspace_dir = state_manager.WORKSPACE_DIR / run_id
    script = VideoScript.model_validate_json(
        (workspace_dir / "script.json").read_text(encoding="utf-8")
    )
    raw_audio = json.loads(
        (workspace_dir / "audio" / "audio_results.json").read_text(encoding="utf-8")
    )
    audio_by_scene = {
        item["scene_id"]: item for item in raw_audio
    }

    print(f"\n🎬 [Renderer] 開始渲染 | {len(script.scenes)} 個場景 | 轉場: {transition_name}")

    clips = []
    for i, scene in enumerate(script.scenes):
        sid = scene.scene_id
        image_path = workspace_dir / "images" / f"scene_{sid:02d}.png"
        audio_data = audio_by_scene[sid]
        audio_path = Path(audio_data["file_path"])

        # 將 timestamp dict 轉成有 .word .start .end 屬性的物件
        timestamps = [
            type("W", (), {"word": w["word"], "start": w["start"], "end": w["end"]})()
            for w in audio_data["timestamps"]
        ]

        print(f"  🖼️  [Scene {sid}] 建立 clip...")
        clip = _build_scene_clip(i, image_path, audio_path, timestamps, settings)
        clips.append(clip)

    # 套用轉場
    if transition_name in TRANSITION_REGISTRY:
        clips = TRANSITION_REGISTRY[transition_name](clips)
    else:
        print(f"⚠️  未知轉場 '{transition_name}'，使用 hard_cut。")

    # 合併
    final_clip = concatenate_videoclips(clips, method="compose")

    # 輸出
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

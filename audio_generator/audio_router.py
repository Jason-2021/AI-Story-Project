import json
import yaml
import asyncio
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()

from .gemini_tts_adapter import generate_tts_with_gemini
from text_generator.llm_router import Scene

# =====================================================================
# 1. Schema
# =====================================================================

class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float

class AudioResult(BaseModel):
    scene_id: int
    file_path: str
    duration: float
    timestamps: List[WordTimestamp]

# =====================================================================
# 2. Whisper 懶載入（首次呼叫才下載模型）
# =====================================================================

_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print("⏳ [Whisper] 載入模型中（首次執行會自動下載 base 模型，約 140MB）...")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        print("✅ [Whisper] 模型載入完成")
    return _whisper_model


def _run_whisper(wav_path: Path) -> tuple:
    """同步函數：分析 WAV 取得逐字時間戳與總時長。由 asyncio.to_thread 包裝呼叫。"""
    model = _get_whisper_model()
    segments, info = model.transcribe(str(wav_path), word_timestamps=True)
    timestamps = []
    for segment in segments:
        if segment.words:
            for word in segment.words:
                timestamps.append(WordTimestamp(
                    word=word.word.strip(),
                    start=round(word.start, 3),
                    end=round(word.end, 3),
                ))
    return timestamps, round(info.duration, 3)

# =====================================================================
# 3. 設定讀取
# =====================================================================

CONFIG_DIR = Path(__file__).parent.parent / "configs"


def _load_yaml(file_path: Path) -> dict:
    if not file_path.exists():
        raise FileNotFoundError(f"[AudioRouter 錯誤] 找不到設定檔: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_tts_settings() -> dict:
    return _load_yaml(CONFIG_DIR / "base_config.yaml").get("tts_settings", {})

# =====================================================================
# 4. 核心路由器
# =====================================================================

async def generate_audio_router(
    scenes: List[Scene],
    output_dir: Path,
    provider: str = "gemini",
) -> List[AudioResult]:
    """
    接收 VideoScript.scenes，並行生成所有 scene 的語音與時間戳。
    output_dir 由呼叫端（state_manager.get_audio_dir）提供。
    回傳 AudioResult 列表，包含音檔路徑、時長與逐字時間戳。
    """
    print(f"\n🎙️  [AudioRouter] 啟動語音生成 | {len(scenes)} 個場景 | 引擎: {provider}")

    tts_settings = _get_tts_settings()
    model_name = tts_settings.get("model_name", "gemini-2.5-flash-preview-tts")
    voice_name = tts_settings.get("voice_name", "Pax")
    sample_rate = tts_settings.get("sample_rate", 24000)

    if provider.lower() == "gemini":
        tasks = [
            _process_single_scene(scene, output_dir, model_name, voice_name, sample_rate)
            for scene in scenes
        ]
        return await asyncio.gather(*tasks)

    raise ValueError(f"❌ [AudioRouter] 不支援的供應商: '{provider}'。請選擇 'gemini'。")


async def _process_single_scene(
    scene: Scene,
    output_dir: Path,
    model_name: str,
    voice_name: str,
    sample_rate: int,
) -> AudioResult:
    wav_path = output_dir / f"scene_{scene.scene_id:02d}.wav"

    # 步驟 1：TTS（非同步 API 呼叫）
    print(f"  📤 [Scene {scene.scene_id}] 送出 TTS 請求...")
    await generate_tts_with_gemini(
        text=scene.narration,
        output_path=wav_path,
        model_name=model_name,
        voice_name=voice_name,
        sample_rate=sample_rate,
    )
    print(f"  🎵 [Scene {scene.scene_id}] 音檔已存至: {wav_path.name}")

    # 步驟 2：Whisper 分析（CPU bound，透過 to_thread 避免阻塞 event loop）
    print(f"  🔍 [Scene {scene.scene_id}] 分析時間戳...")
    timestamps, duration = await asyncio.to_thread(_run_whisper, wav_path)
    print(f"  ✅ [Scene {scene.scene_id}] 完成，時長: {duration:.2f}s，字數: {len(timestamps)}")

    return AudioResult(
        scene_id=scene.scene_id,
        file_path=str(wav_path),
        duration=duration,
        timestamps=timestamps,
    )

# =====================================================================
# 5. 測試區塊（從專案根目錄執行：python -m audio_generator.audio_router）
# =====================================================================
if __name__ == "__main__":
    async def run_test():
        from core import state_manager
        from text_generator.llm_router import VideoScript

        # 1. 從快取載入上次的劇本
        run_id = state_manager.get_latest_run_id()
        if not run_id:
            print("❌ 找不到任何 run，請先執行 text_generator 模組生成劇本。")
            return

        script = state_manager.load_script(run_id, VideoScript)
        if not script:
            print(f"❌ run '{run_id}' 中找不到 script.json，請先執行 text_generator 模組。")
            return

        print(f"✅ 載入劇本: {script.title}（{len(script.scenes)} 個場景）")

        # 2. 若音訊已生成過，直接跳過
        if state_manager.get_stage_status(run_id, "audio") == "completed":
            print("⚡ [快取] 音訊階段已完成，跳過 API 呼叫。")
            print("   若要重新生成，請先執行 text_generator 以建立新的 run。")
            return

        # 3. 並行生成所有場景的音訊與時間戳
        audio_dir = state_manager.get_audio_dir(run_id)
        state_manager.mark_stage(run_id, "audio", "in_progress")

        results = await generate_audio_router(script.scenes, output_dir=audio_dir)

        # 4. 儲存結果 JSON
        results_path = audio_dir / "audio_results.json"
        results_path.write_text(
            json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        state_manager.mark_stage(run_id, "audio", "completed")

        print(f"\n🎉 [結果] 共生成 {len(results)} 個音檔:")
        for r in results:
            print(f"  Scene {r.scene_id}: {r.file_path} | {r.duration:.2f}s | {len(r.timestamps)} 個字")

    asyncio.run(run_test())

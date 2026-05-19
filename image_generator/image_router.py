import yaml
import asyncio
from pathlib import Path
from typing import List
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()

from .gemini_imagen_adapter import generate_image_with_gemini
from text_generator.llm_router import Scene

# =====================================================================
# 1. Schema
# =====================================================================

class ImageResult(BaseModel):
    scene_id: int
    file_path: str  # str 確保 JSON 序列化相容

# =====================================================================
# 2. 設定讀取
# =====================================================================

CONFIG_DIR = Path(__file__).parent.parent / "configs"


def _load_yaml(file_path: Path) -> dict:
    if not file_path.exists():
        raise FileNotFoundError(f"[ImageRouter 錯誤] 找不到設定檔: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_image_settings() -> dict:
    return _load_yaml(CONFIG_DIR / "base_config.yaml").get("image_settings", {})

# =====================================================================
# 3. 核心路由器
# =====================================================================

async def generate_images_router(
    scenes: List[Scene],
    output_dir: Path,
    provider: str = "gemini",
) -> List[ImageResult]:
    """
    接收 VideoScript.scenes，以 asyncio.gather 並行生成所有 scene 的圖片。
    output_dir 由呼叫端（state_manager.get_image_dir）提供，模組本身不依賴 state_manager。
    回傳 ImageResult 列表，包含每個 scene 的本地圖片路徑。
    """
    print(f"\n🖼️  [ImageRouter] 啟動圖片生成 | {len(scenes)} 個場景 | 引擎: {provider}")

    image_settings = _get_image_settings()
    model_name = image_settings.get("model_name", "imagen-3.0-generate-002")
    aspect_ratio = image_settings.get("aspect_ratio", "9:16")

    if provider.lower() == "gemini":
        tasks = [
            _generate_single(scene, output_dir, model_name, aspect_ratio)
            for scene in scenes
        ]
        return await asyncio.gather(*tasks)

    raise ValueError(f"❌ [ImageRouter] 不支援的供應商: '{provider}'。請選擇 'gemini'。")


async def _generate_single(
    scene: Scene,
    output_dir: Path,
    model_name: str,
    aspect_ratio: str,
) -> ImageResult:
    output_path = output_dir / f"scene_{scene.scene_id:02d}.png"
    print(f"  📤 [Scene {scene.scene_id}] 送出圖片請求...")
    await generate_image_with_gemini(
        prompt=scene.image_prompt,
        output_path=output_path,
        model_name=model_name,
        aspect_ratio=aspect_ratio,
    )
    print(f"  ✅ [Scene {scene.scene_id}] 圖片已存至: {output_path.name}")
    return ImageResult(scene_id=scene.scene_id, file_path=str(output_path))


# =====================================================================
# 4. 測試區塊（從專案根目錄執行：python -m image_generator.image_router）
# =====================================================================
if __name__ == "__main__":
    async def run_test():
        from core import state_manager
        from text_generator.llm_router import VideoScript

        # 1. 從快取載入上次的劇本（跳過 LLM 呼叫）
        run_id = state_manager.get_latest_run_id()
        if not run_id:
            print("❌ 找不到任何 run，請先執行 text_generator 模組生成劇本。")
            return

        script = state_manager.load_script(run_id, VideoScript)
        if not script:
            print(f"❌ run '{run_id}' 中找不到 script.json，請先執行 text_generator 模組。")
            return

        print(f"✅ 載入劇本: {script.title}（{len(script.scenes)} 個場景）")

        # 2. 若圖片已生成過，直接跳過
        if state_manager.get_stage_status(run_id, "images") == "completed":
            print("⚡ [快取] 圖片階段已完成，跳過 API 呼叫。")
            print("   若要重新生成，請先執行 text_generator 以建立新的 run。")
            return

        # 3. 並行生成所有圖片
        image_dir = state_manager.get_image_dir(run_id)
        state_manager.mark_stage(run_id, "images", "in_progress")

        results = await generate_images_router(script.scenes, output_dir=image_dir)

        state_manager.mark_stage(run_id, "images", "completed")

        print(f"\n🎉 [結果] 共生成 {len(results)} 張圖片:")
        for r in results:
            print(f"  Scene {r.scene_id}: {r.file_path}")

    asyncio.run(run_test())

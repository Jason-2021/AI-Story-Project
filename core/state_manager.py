import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Type
from pydantic import BaseModel

WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"
_LATEST_RUN_FILE = WORKSPACE_DIR / "latest_run_id.txt"


def create_run(topic: str, profile_name: str) -> str:
    WORKSPACE_DIR.mkdir(exist_ok=True)
    base = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_id = base
    counter = 1
    while (WORKSPACE_DIR / run_id).exists():
        run_id = f"{base}_{counter:02d}"
        counter += 1
    run_dir = WORKSPACE_DIR / run_id
    run_dir.mkdir()
    (run_dir / "images").mkdir()
    (run_dir / "audio").mkdir()

    _write_json(run_dir / "task_status.json", {
        "run_id": run_id,
        "topic": topic,
        "profile_name": profile_name,
        "stages": {
            "text":   "pending",
            "images": "pending",
            "audio":  "pending",
            "video":  "pending",
        },
    })
    _LATEST_RUN_FILE.write_text(run_id, encoding="utf-8")
    print(f"📁 [StateManager] 新 run 建立: {run_id}")
    return run_id


def get_latest_run_id() -> Optional[str]:
    if not _LATEST_RUN_FILE.exists():
        return None
    return _LATEST_RUN_FILE.read_text(encoding="utf-8").strip() or None


def save_script(run_id: str, script: BaseModel) -> None:
    path = WORKSPACE_DIR / run_id / "script.json"
    path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    print(f"💾 [StateManager] 劇本已快取: {path.name}")


def load_script(run_id: str, schema_class: Type[BaseModel]) -> Optional[BaseModel]:
    path = WORKSPACE_DIR / run_id / "script.json"
    if not path.exists():
        return None
    print(f"⚡ [StateManager] 從快取載入劇本: {run_id}")
    return schema_class.model_validate_json(path.read_text(encoding="utf-8"))


def get_image_dir(run_id: str) -> Path:
    image_dir = WORKSPACE_DIR / run_id / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    return image_dir


def get_audio_dir(run_id: str) -> Path:
    audio_dir = WORKSPACE_DIR / run_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


def get_video_dir(run_id: str) -> Path:
    video_dir = WORKSPACE_DIR / run_id / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    return video_dir


def mark_stage(run_id: str, stage: str, status: str) -> None:
    path = WORKSPACE_DIR / run_id / "task_status.json"
    data = _read_json(path)
    data["stages"][stage] = status
    _write_json(path, data)


def get_stage_status(run_id: str, stage: str) -> str:
    path = WORKSPACE_DIR / run_id / "task_status.json"
    if not path.exists():
        return "unknown"
    return _read_json(path).get("stages", {}).get(stage, "unknown")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Type
from pydantic import BaseModel

WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"
_LATEST_SERIES_FILE = WORKSPACE_DIR / "latest_series_id.txt"


def create_series(topic: str, profile_name: str, n_episodes: int) -> str:
    """
    Creates the series workspace directory and all episode subdirectories.
    Each episode dir includes the task_status.json expected by state_manager functions.
    Returns series_run_id (e.g. 'series_20260520_210913').
    """
    WORKSPACE_DIR.mkdir(exist_ok=True)
    series_id = f"series_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    series_dir = WORKSPACE_DIR / series_id
    series_dir.mkdir()
    (series_dir / "long_form").mkdir()

    episodes: dict[str, str] = {}
    for i in range(1, n_episodes + 1):
        ep_key = f"ep{i:02d}"
        ep_run_id = f"{series_id}/{ep_key}"
        ep_dir = series_dir / ep_key
        ep_dir.mkdir()
        (ep_dir / "images").mkdir()
        (ep_dir / "audio").mkdir()
        _write_json(ep_dir / "task_status.json", {
            "run_id": ep_run_id,
            "topic": topic,
            "profile_name": profile_name,
            "stages": {
                "text":   "pending",
                "images": "pending",
                "audio":  "pending",
                "video":  "pending",
            },
        })
        episodes[ep_key] = "pending"

    _write_json(series_dir / "series_manifest.json", {
        "series_run_id": series_id,
        "topic": topic,
        "profile_name": profile_name,
        "n_episodes": n_episodes,
        "episodes": episodes,
    })

    _LATEST_SERIES_FILE.write_text(series_id, encoding="utf-8")
    print(f"📁 [SeriesState] 新 series 建立: {series_id}（{n_episodes} 集）")
    return series_id


def create_anthology(topic: str, profile_name: str, n_episodes: int) -> str:
    """Creates the anthology workspace directory. Same structure as create_series()."""
    WORKSPACE_DIR.mkdir(exist_ok=True)
    anthology_id = f"anthology_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    anthology_dir = WORKSPACE_DIR / anthology_id
    anthology_dir.mkdir()
    (anthology_dir / "long_form").mkdir()

    episodes: dict[str, str] = {}
    for i in range(1, n_episodes + 1):
        ep_key = f"ep{i:02d}"
        ep_run_id = f"{anthology_id}/{ep_key}"
        ep_dir = anthology_dir / ep_key
        ep_dir.mkdir()
        (ep_dir / "images").mkdir()
        (ep_dir / "audio").mkdir()
        _write_json(ep_dir / "task_status.json", {
            "run_id": ep_run_id,
            "topic": topic,
            "profile_name": profile_name,
            "stages": {
                "text":   "pending",
                "images": "pending",
                "audio":  "pending",
                "video":  "pending",
            },
        })
        episodes[ep_key] = "pending"

    _write_json(anthology_dir / "series_manifest.json", {
        "series_run_id": anthology_id,
        "topic": topic,
        "profile_name": profile_name,
        "n_episodes": n_episodes,
        "episodes": episodes,
    })

    print(f"📁 [SeriesState] 新 anthology 建立: {anthology_id}（{n_episodes} 集）")
    return anthology_id


def get_latest_series_id() -> Optional[str]:
    if not _LATEST_SERIES_FILE.exists():
        return None
    return _LATEST_SERIES_FILE.read_text(encoding="utf-8").strip() or None


def save_series_arc(series_run_id: str, arc: BaseModel) -> None:
    path = WORKSPACE_DIR / series_run_id / "series_arc.json"
    path.write_text(arc.model_dump_json(indent=2), encoding="utf-8")
    print(f"💾 [SeriesState] Arc 已快取: series_arc.json")


def load_series_arc(series_run_id: str, schema_class: Type[BaseModel]) -> Optional[BaseModel]:
    path = WORKSPACE_DIR / series_run_id / "series_arc.json"
    if not path.exists():
        return None
    return schema_class.model_validate_json(path.read_text(encoding="utf-8"))


def load_series_arc_json(series_run_id: str) -> Optional[dict]:
    path = WORKSPACE_DIR / series_run_id / "series_arc.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_episode_run_id(series_run_id: str, episode_number: int) -> str:
    """Returns the run_id used by state_manager functions for this episode."""
    return f"{series_run_id}/ep{episode_number:02d}"


def get_series_dir(series_run_id: str) -> Path:
    return WORKSPACE_DIR / series_run_id


def mark_episode_status(series_run_id: str, episode_number: int, status: str) -> None:
    path = WORKSPACE_DIR / series_run_id / "series_manifest.json"
    data = _read_json(path)
    data["episodes"][f"ep{episode_number:02d}"] = status
    _write_json(path, data)


def get_episode_status(series_run_id: str, episode_number: int) -> str:
    path = WORKSPACE_DIR / series_run_id / "series_manifest.json"
    if not path.exists():
        return "unknown"
    return _read_json(path).get("episodes", {}).get(f"ep{episode_number:02d}", "unknown")


def load_manifest(series_run_id: str) -> Optional[dict]:
    path = WORKSPACE_DIR / series_run_id / "series_manifest.json"
    if not path.exists():
        return None
    return _read_json(path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

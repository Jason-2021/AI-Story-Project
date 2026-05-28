"""
aggregate_scripts.py

Given a series workspace folder, collect all episode script.json files
and output a single readable Markdown file.

Usage:
    python tools/aggregate_scripts.py workspace/series_20260520_232258
    python tools/aggregate_scripts.py workspace/series_20260520_232258 --out-dir output/
"""

import argparse
import json
from datetime import date
from pathlib import Path


def aggregate(series_dir: Path, out_dir: Path) -> Path:
    series_name = series_dir.name

    episode_scripts = sorted(series_dir.glob("ep*/script.json"), key=lambda p: p.parent.name)

    if not episode_scripts:
        raise FileNotFoundError(f"No ep*/script.json files found in: {series_dir}")

    lines = [
        f"# Series: {series_name}",
        f"Generated: {date.today()}",
        "",
        "---",
        "",
    ]

    for script_path in episode_scripts:
        ep_folder = script_path.parent.name

        if not script_path.exists():
            print(f"[SKIP] [{ep_folder}] script.json not found")
            continue

        try:
            script = json.loads(script_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[SKIP] [{ep_folder}] Invalid JSON ({e})")
            continue

        ep_num = int("".join(filter(str.isdigit, ep_folder)))
        title = script.get("title", "(no title)")
        description = script.get("description", "")
        tags = script.get("tags", [])
        scenes = sorted(script.get("scenes", []), key=lambda s: s.get("scene_id", 0))

        lines.append(f"## Episode {ep_num} — {title}")
        lines.append("")

        if description:
            lines.append("**Description:**")
            lines.append(description)
            lines.append("")

        if tags:
            tag_str = ", ".join(f"`{t}`" for t in tags)
            lines.append(f"**Tags:** {tag_str}")
            lines.append("")

        if scenes:
            lines.append("**Narration:**")
            for scene in scenes:
                sid = scene.get("scene_id", "?")
                narration = scene.get("narration", "").strip()
                lines.append(f"[Scene {sid}] {narration}")
            lines.append("")

        lines.append("---")
        lines.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{series_name}_scripts.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Aggregate episode scripts into a single Markdown file.")
    parser.add_argument("series_dir", type=Path, help="Path to series workspace folder")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory (default: <series_dir>/exports/)")
    args = parser.parse_args()

    series_dir = args.series_dir.resolve()
    if not series_dir.is_dir():
        parser.error(f"series_dir does not exist or is not a directory: {series_dir}")

    out_dir = args.out_dir.resolve() if args.out_dir else series_dir / "exports"

    output_path = aggregate(series_dir, out_dir)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()

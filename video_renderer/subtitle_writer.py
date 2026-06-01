"""
subtitle_writer.py — 長影音外部字幕生成（SRT + VTT）

從各集的 audio_results.json 讀取 Whisper word timestamps，
重建全域時間軸，分組成字幕 blocks，輸出 subtitles.srt 和 subtitles.vtt。

字幕規格：每行 ≤ 45 字元，最多 2 行，每 block 停留 1.5–4.0 秒。
"""
import json
from pathlib import Path
from typing import Optional


_TITLE_CARD_DURATION = 3.0  # 與 engine.py _make_title_card(duration=3.0) 一致
_MAX_CHARS_PER_LINE  = 45
_MAX_LINES           = 2
_MIN_BLOCK_DUR       = 1.5
_MAX_BLOCK_DUR       = 4.0
_BLOCK_GAP           = 0.05   # 相鄰 block 之間的最小間距


# ── 時間格式轉換 ───────────────────────────────────────────────────────

def _fmt_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_vtt(t: float) -> str:
    return _fmt_srt(t).replace(",", ".")


# ── 字幕 Block 分組 ────────────────────────────────────────────────────

def _words_to_blocks(words: list, offset: float) -> list:
    """
    將一個 scene 的 word list 分組為字幕 blocks。
    每個 block 最多 2 行、每行 ≤ 45 字元。
    """
    blocks = []
    i = 0
    n = len(words)

    while i < n:
        block_words = []
        line_count  = 0
        line_chars  = 0

        while i < n:
            w    = words[i]
            text = w["word"].strip()
            if not text:
                i += 1
                continue

            add = len(text) + (1 if line_chars > 0 else 0)

            if line_chars + add > _MAX_CHARS_PER_LINE:
                if line_count < _MAX_LINES - 1:
                    # 換行（同一 block）
                    line_count += 1
                    line_chars  = len(text)
                    block_words.append(w)
                    i += 1
                else:
                    # block 已滿，結束這個 block
                    break
            else:
                line_chars += add
                block_words.append(w)
                i += 1

        if not block_words:
            i += 1
            continue

        start = offset + block_words[0]["start"]
        end   = offset + block_words[-1]["end"]
        end   = max(end, start + _MIN_BLOCK_DUR)
        end   = min(end, start + _MAX_BLOCK_DUR)

        # 不與下一個 block 重疊
        if i < n:
            next_word = words[i]
            next_start = offset + next_word["start"]
            end = min(end, next_start - _BLOCK_GAP)
            end = max(end, start + 0.1)  # 至少留 100ms

        blocks.append({"start": start, "end": end, "words": block_words})

    return blocks


def _block_to_text(block: dict) -> str:
    """將 block 的 words 排成最多 2 行文字。"""
    words = block["words"]
    lines = []
    current_line = []
    current_chars = 0

    for w in words:
        text = w["word"].strip()
        if not text:
            continue
        add = len(text) + (1 if current_chars > 0 else 0)
        if current_chars + add > _MAX_CHARS_PER_LINE and current_line:
            lines.append(" ".join(current_line))
            current_line = [text]
            current_chars = len(text)
        else:
            current_line.append(text)
            current_chars += add

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines[:_MAX_LINES])


# ── 全域時間軸建立 ─────────────────────────────────────────────────────

def _load_audio_results(run_id_path: Path) -> list:
    path = run_id_path / "audio" / "audio_results.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _build_timeline(
    series_id: str,
    ep_run_ids: list,
    add_title_cards: bool,
    workspace: Path,
) -> list:
    """
    重建 render_longform() 的組裝順序，計算每個 scene 的 global start time。
    返回 list of {offset, words}。
    """
    current_time = 0.0
    timeline = []

    series_dir = workspace / series_id

    # Intro bumper
    intro_dir = series_dir / "intro"
    if intro_dir.exists() and (intro_dir / "audio_results.json").exists():
        intro_raw = json.loads((intro_dir / "audio_results.json").read_text(encoding="utf-8"))
        for item in sorted(intro_raw, key=lambda x: x["scene_id"]):
            timeline.append({"offset": current_time, "words": item["timestamps"]})
            current_time += item["duration"]

    # Episodes
    for ep_run_id in ep_run_ids:
        ep_path = workspace / ep_run_id
        if add_title_cards:
            current_time += _TITLE_CARD_DURATION
        audio_results = _load_audio_results(ep_path)
        # sort by scene_id, skip loop_scene (id=0)
        for item in sorted(audio_results, key=lambda x: x["scene_id"]):
            if item["scene_id"] == 0:
                continue
            timeline.append({"offset": current_time, "words": item["timestamps"]})
            current_time += item["duration"]

    # Outro bumper
    outro_dir = series_dir / "outro"
    if outro_dir.exists() and (outro_dir / "audio_results.json").exists():
        outro_raw = json.loads((outro_dir / "audio_results.json").read_text(encoding="utf-8"))
        for item in sorted(outro_raw, key=lambda x: x["scene_id"]):
            timeline.append({"offset": current_time, "words": item["timestamps"]})
            current_time += item["duration"]

    return timeline


# ── 主入口 ────────────────────────────────────────────────────────────

def generate_longform_subtitles(
    series_id: str,
    ep_run_ids: list,
    add_title_cards: bool,
    output_dir: Path,
    workspace: Optional[Path] = None,
) -> tuple:
    """
    生成長影音字幕檔。

    Returns:
        (srt_path, vtt_path)
    """
    if workspace is None:
        workspace = Path(__file__).parent.parent / "workspace"

    timeline = _build_timeline(series_id, ep_run_ids, add_title_cards, workspace)

    # 收集所有 blocks
    all_blocks = []
    for entry in timeline:
        all_blocks.extend(_words_to_blocks(entry["words"], entry["offset"]))

    # 寫 SRT / VTT（序號只計非空 block，保持連續）
    srt_lines = []
    vtt_lines = ["WEBVTT", ""]
    seq = 0
    for block in all_blocks:
        text = _block_to_text(block)
        if not text.strip():
            continue
        seq += 1
        srt_lines += [str(seq), f"{_fmt_srt(block['start'])} --> {_fmt_srt(block['end'])}", text, ""]
        vtt_lines += [str(seq), f"{_fmt_vtt(block['start'])} --> {_fmt_vtt(block['end'])}", text, ""]

    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / "subtitles.srt"
    vtt_path = output_dir / "subtitles.vtt"
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")

    return srt_path, vtt_path

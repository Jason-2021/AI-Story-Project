# AI-Story-Project — Claude Code Reference

AI 自動生成短影音 pipeline：LLM 腳本 → 圖片 → 語音 → 成片，支援 solo / series / anthology 三種模式。

> **維護規則**：新增或修改任何 feature 後，必須同步更新本文件的 Feature Catalog。

---

## Tech Stack

| 層 | 工具 |
|----|------|
| LLM | Gemini (`google-genai`) / OpenAI (`openai` SDK) |
| Image | Gemini Imagen / OpenAI `gpt-image-2` |
| TTS | Gemini TTS + `faster-whisper`（字幕時間軸） |
| Video | `moviepy` + `Pillow` |
| Config | YAML + Pydantic v2 |
| Retry | `tenacity`（5 次，指數退避 2–60s） |

---

## Module Map

```
main.py                    CLI 入口：solo / series / anthology
configs/
  base_config.yaml         全域設定（模型、renderer、BGM 等）
  profiles/*.yaml          14 個內容風格 profile
  system_prompt.txt        LLM system prompt 模板
  series_arc_prompt.txt    Arc 規劃 prompt
  anthology_topics_prompt.txt  Anthology 自動選題 prompt
core/
  state_manager.py         Solo run 狀態管理（create/load/save/mark）
  series_state_manager.py  Series/anthology 狀態管理
text_generator/
  llm_router.py            主路由：generate_script_router()、call_llm()
  gemini_api.py            Gemini LLM adapter
  openai_api.py            OpenAI LLM adapter
image_generator/
  image_router.py          主路由：generate_images_router()
  gemini_imagen_adapter.py Gemini Imagen adapter
  openai_dalle_adapter.py  OpenAI gpt-image-2 adapter
audio_generator/
  audio_router.py          主路由：generate_audio_router()
  gemini_tts_adapter.py    Gemini TTS adapter
video_renderer/
  engine.py                render_video()（9:16）/ render_longform()（16:9）
  effects.py               Ken Burns、Zoom 效果
  captions.py              PIL 逐字字幕渲染
  transitions.py           TRANSITION_REGISTRY（hard_cut/fade_black/crossfade）
series_planner/
  episode_runner.py        單集 3-stage pipeline：run_episode()
  arc_planner.py           plan_series_arc() / generate_anthology_plan()
  series_runner.py         run_series_mode() / run_anthology_mode()
  merger.py                長形影片合併
tools/                     獨立工具，不屬於主 pipeline
  topic_bank.py            SQLite topic 資料庫
  topic_browser.py         CLI topic 瀏覽器
  topic_scraper.py         Reddit / Wikipedia 抓題（PRAW）
  job_builder.py           從 topic bank 建 Job YAML
```

---

## Feature Catalog

### Text Generation（Stage 1）

- **路由**：`text_generator/llm_router.py` → `generate_script_router(ScriptRequest) → VideoScript`
- **Gemini**：`text_generator/gemini_api.py` → `generate_with_gemini()`
- **OpenAI**：`text_generator/openai_api.py` → `generate_with_openai()`
- **切換**：CLI `--provider gemini|openai|prompt`
- **設定**：`configs/base_config.yaml` → `llm_settings`（Gemini）/ `openai_llm_settings`（OpenAI）
- **Schema**：`Scene`、`VideoScript`、`ScriptRequest`（定義在 `llm_router.py`）

### Image Generation（Stage 2a）

- **路由**：`image_generator/image_router.py` → `generate_images_router(scenes, output_dir)`
- **Gemini**：`image_generator/gemini_imagen_adapter.py` → `generate_image_with_gemini()`
- **OpenAI**：`image_generator/openai_dalle_adapter.py` → `generate_image_with_openai()`
- **切換**：`configs/base_config.yaml` → `image_settings.provider: gemini|openai`（不需改 CLI）
- **設定**：
  - 共用：`image_settings.provider` / `image_settings.scene_ratio_mode`（all_16_9 / all_9_16 / alternate / ...）
  - Gemini：`gemini_image_settings.model_name`
  - OpenAI：`openai_image_settings.model_name` / `quality`（low/medium/high/auto）
- **Aspect ratio → size 對應**（OpenAI）：`16:9→1536x1024`、`9:16→1024x1536`、`1:1→1024x1024`

### Audio / TTS（Stage 2b）

- **路由**：`audio_generator/audio_router.py` → `generate_audio_router(scenes, output_dir)`
- **TTS**：`audio_generator/gemini_tts_adapter.py` → `generate_tts_with_gemini()`
- **Whisper**：`faster-whisper` 在 `audio_router.py` 呼叫，產生逐字時間軸
- **設定**：`configs/base_config.yaml` → `tts_settings`（model_name、voice_name、sample_rate）

### Video Rendering（Stage 3）

- **短形 9:16**：`video_renderer/engine.py` → `render_video(run_id)`，1080×1920
- **長形 16:9**：`video_renderer/engine.py` → `render_longform(series_id, episodes)`，1920×1080
- **BGM 混音**：`video_renderer/engine.py` → `mix_bgm()`
- **設定**：`configs/base_config.yaml` → `video_renderer` / `long_form_renderer` / `bgm_settings`

### Series / Anthology 模式

- **Arc 規劃（Stage 0）**：`series_planner/arc_planner.py`
  - `plan_series_arc()` → `SeriesArc`（series 模式）
  - `generate_anthology_plan()` → `AnthologyPlan`（anthology 模式）
- **單集執行**：`series_planner/episode_runner.py` → `run_episode()`
- **協調**：`series_planner/series_runner.py` → `run_series_mode()` / `run_anthology_mode()`
- **長片合併**：`series_planner/merger.py`
- **Schema**：`EpisodeOutline`、`SeriesArc`、`BumperScene`、`AnthologyPlan`（定義在 `arc_planner.py`）

### Profile 系統

- **目錄**：`configs/profiles/*.yaml`（14 個）
- **欄位**：`tone`、`hooks`、`specific_forbidden_phrases`、`visuals.style`、`visuals.prompt_suffix`
- **CLI**：`--profile finance|science|gaming|...`
- **新增 profile**：複製現有 YAML → 改名 → 修改欄位，不需改程式碼

### Batch Mode（圖片 + TTS，50% 折扣）

- **Submit**：`series_planner/batch_runner.py` → `run_batch_submit(args, job)`
  - 執行 Arc planning（series/anthology）+ 所有集數文字生成
  - 一次打包送出 image batch + TTS batch → 寫 `batch_jobs.json` → EXIT
- **Collect**：`series_planner/batch_collector.py` → `run_batch_collect(batch_id)`
  - 查 API status → 下載結果 → 寫 PNG/WAV → 跑 Whisper → render_video → merge
  - 部分失敗 → realtime fallback 補跑
- **Image batch adapters**：
  - Gemini：`image_generator/gemini_image_batch.py` → `submit_image_batch()` / `collect_image_batch()`
  - OpenAI：`image_generator/openai_image_batch.py` → 同介面
- **TTS batch adapter**：`audio_generator/gemini_tts_batch.py`（OpenAI 不支援 TTS batch）
- **Batch state**：`workspace/{id}/batch_jobs.json`（跨 session 持久化，`collected` 欄位追蹤）
- **狀態工具**：`tools/batch_status.py`（列出所有待收取的 batch）
- **切換**：CLI `--batch`（submit）/ `--batch-check <id>`（collect）
- **Batch mode 只影響 Stage 2**；realtime flow 不動

### Topic Bank 工具

- **SQLite DB**：`tools/topic_bank.py` → `query_by_tag()`、`mark_status_by_title()`
- **瀏覽**：`tools/topic_browser.py`（CLI 互動介面）
- **抓題**：`tools/topic_scraper.py` → `scrape_reddit()` / `scrape_wikipedia()`
- **建 Job**：`tools/job_builder.py` → `build_job_yaml(tag, profile, n)`

---

## Data Flow

```
CLI / Job YAML
  ↓
[Series/Anthology only] Stage 0：arc_planner → LLM → SeriesArc / AnthologyPlan
  ↓
Stage 1：llm_router → gemini_api | openai_api → VideoScript
  ↓
Stage 2a：image_router → gemini_imagen | openai_dalle → PNG × N  ┐ asyncio.gather
Stage 2b：audio_router → gemini_tts + whisper → WAV + timestamps ┘
  ↓
Stage 3：video_renderer/engine → output.mp4（1080×1920）
  ↓ [Series only]
Stage 4：merger → long_form/output.mp4（1920×1080）
```

---

## Adding a New Provider

### LLM Provider
1. 建 `text_generator/{name}_api.py`，函式簽名同 `generate_with_gemini()`
2. `text_generator/llm_router.py` → `call_llm()` 加 `elif p == "{name}":` 分支
3. `configs/base_config.yaml` 加 `{name}_llm_settings: {model_name, temperature}`

### Image Provider
1. 建 `image_generator/{name}_adapter.py`，函式簽名同 `generate_image_with_gemini()`
2. `image_generator/image_router.py` → `generate_images_router()` 加 `if effective_provider == "{name}":` 分支，並加對應的 `_get_{name}_image_settings()` helper
3. `configs/base_config.yaml` 加 `{name}_image_settings`，並改 `image_settings.provider: {name}`

---

## Testing

```bash
# Dry-run（不呼叫任何 API，只印出 prompt）
python main.py --topic "X" --profile general --provider prompt

# 單模組測試（需先有 script.json 快取）
python -m image_generator.run_test
python -m audio_generator.run_test
python -m text_generator.run_test

# 完整 solo run
python main.py --topic "黑洞的誕生" --profile science --provider gemini --fresh

# Series run
python main.py --job jobs/example_series.yaml

# Anthology run
python main.py --job jobs/example_anthology.yaml
```

---

## Key Conventions

- **Retry**：所有外部 API 呼叫必須加 `@retry`（tenacity，5 次，指數退避 2–60s）
- **Provider 切換**：image 靠 `base_config.yaml`；text 靠 CLI `--provider`；不 hardcode
- **Async**：Stage 2 全部用 `asyncio.gather()` 並行
- **No API in tests**：測試用 `--provider prompt` 或 Python unit test，禁止直接觸發 Gemini/OpenAI/TTS API
- **更新 CLAUDE.md**：新增 feature 後必須更新 Feature Catalog

# AI YouTube Shorts 自動化流水線

輸入一個主題與風格，自動產出可上傳的 YouTube Shorts（或長影音）MP4。

**輸入：** 主題字串 + Profile + （選填）背景說明  
**輸出：** `workspace/{run_id}/video/output.mp4` — 1080×1920、H.264、旁白音訊、動態字幕

---

## 快速開始

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 在專案根目錄建立 .env
echo GEMINI_API_KEY=你的金鑰 > .env

# 3. 產生第一支影片
python main.py --topic "2008 金融海嘯的真相" --profile finance
```

輸出路徑：`workspace/run_YYYYMMDD_HHMMSS/video/output.mp4`

---

## 三種模式

### Solo — 單集影片

```bash
# CLI 直接指定
python main.py --topic "2008 金融海嘯" --profile finance
python main.py --topic "..." --profile comedy --details "聚焦雷曼兄弟，目標是 Z 世代"

# 用 Job YAML（主題描述很長時推薦）
python main.py --job jobs/my_video.yaml

# 強制重跑（忽略快取）
python main.py --topic "..." --profile finance --fresh

# 從中斷的 run 繼續
python main.py --resume run_20260519_211046
```

Solo Job YAML 格式（`jobs/my_video.yaml`）：

```yaml
topic: "The 2008 Financial Crisis"
profile: finance
provider: gemini        # 選填，預設 gemini
details: |              # 選填，注入至 LLM prompt
  Focus on Lehman Brothers and the mortgage bubble.
  Target audience: Gen Z who know nothing about finance.
```

---

### Series — 系列影片（有敘事弧度）

N 集圍繞同一主題，由 LLM 先規劃完整 arc，再逐集生成。集與集之間有敘事銜接，可合併成長影音。

```bash
# 完整跑（arc → 8 集 → 合併長影音）
python main.py --job jobs/example_series.yaml

# 只規劃 arc，不生成影片（先看結構再決定）
python main.py --job jobs/example_series.yaml --arc-only

# 只跑前兩集（arc 仍完整規劃）
python main.py --job jobs/example_series.yaml --episodes 1-2

# 只跑指定幾集（不連續）
python main.py --job jobs/example_series.yaml --episodes 1,3,5

# 恢復中斷的 series
python main.py --job jobs/example_series.yaml --resume-series series_20260520_232258

# 只跑文字生成（不產圖/音訊/影片）
python main.py --job jobs/example_series.yaml --text-only
```

Series Job YAML 格式：

```yaml
mode: series
title: "Quantum Computing Explained"
profile: science
provider: gemini
n_episodes: 8                    # 集數，預設 8

arc_details: |                   # 給 arc 規劃 LLM 的背景資料
  Target a general audience with no prior knowledge.
  Build from first principles toward real-world impact.

combine_long_form: true          # 合併成長影音（16:9）
add_title_cards: true            # 集與集之間加標題卡
```

---

### Anthology — 獨立批次

N 個完全無關的主題，相同 profile，批次跑。每集彼此獨立，無 arc、無敘事依賴。

```bash
python main.py --job jobs/my_anthology.yaml

# 只生成文字稿
python main.py --job jobs/my_anthology.yaml --text-only
```

**方式一：手動指定 topics**

```yaml
mode: anthology
profile: evergreen
provider: gemini

topics:
  - "The Psychology of Sunk Cost: Why Smart People Make Terrible Decisions"
  - "The 72-Hour Rule That Saved a Fortune 500 Company"
  - "Why Every Map You've Ever Seen Is Wrong"
```

**方式二：讓 LLM 自動生成主題**（不填 `topics`，改填 `title`）

```yaml
mode: anthology
title: "Elon Musk's Empire"
arc_details: "Focus on business decisions and failures"   # 選填，提供方向
n_episodes: 8                                             # 預設 8
profile: finance
provider: gemini
```

LLM 根據 `title` 和 `arc_details` 自動生成 N 個多元、獨立的主題，每個主題仍是完全獨立的影片，彼此無敘事連結。

---

## CLI 參數總表（main.py）

| 參數 | 預設值 | 適用模式 | 說明 |
|------|--------|----------|------|
| `--topic TEXT` | — | Solo | 影片主題（新 run 必填） |
| `--profile NAME` | `general` | 全部 | 風格名稱 |
| `--provider STR` | `gemini` | 全部 | LLM 供應商：`gemini` / `openai` |
| `--details TEXT` | 空 | Solo | 補充說明，注入至 prompt |
| `--job PATH` | — | 全部 | Job YAML 路徑 |
| `--fresh` | 關 | Solo | 強制建立新 run，忽略快取 |
| `--resume RUN_ID` | — | Solo | 恢復指定的單集 run |
| `--resume-series ID` | — | Series | 恢復指定的 series run |
| `--text-only` | 關 | 全部 | 只跑 Stage 1（文字），跳過圖/音/影 |
| `--arc-only` | 關 | Series | 只規劃 arc，不生成影片 |
| `--episodes STR` | — | Series | 只跑指定集數，如 `1-2` 或 `1,3` |
| `--bgm-only` | 關 | Series | 只對已渲染影片補加 BGM |

---

## Profiles

Profile 控制敘事語氣、開場 hook 風格、禁用詞，以及圖片生成的視覺後綴。
檔案位置：`configs/profiles/`

| Profile | 說明 |
|---------|------|
| `comedy` | 輕鬆、荒誕感、短句有力 |
| `cooking` | 感官描述、步驟清晰 |
| `education` | 知識糾錯風格，清晰結構，適合歷史和事實題材 |
| `evergreen` | 長青紀錄片風格：心理學、歷史謎團、商業賽局、自然奇觀 |
| `finance` | 數據驅動、沉穩權威，無誇大 |
| `fitness` | 高能量、激勵感 |
| `gaming` | 熱情、貼近社群語氣 |
| `general` | 中性 fallback，適合任何主題 |
| `motivation` | 感染力強、情緒弧線、適合個人成長 |
| `science` | 好奇心驅動、充滿驚奇，支援系列銜接 hook |

新增 Profile：複製任一 YAML，修改欄位，以新檔名存入 `configs/profiles/` 即可。

---

## Pipeline 四階段

```
Topic + Profile
      │
      ▼
┌─────────────┐     ┌──────────────────┐
│  Stage 1    │     │    Stage 2       │  （圖片＋音訊平行執行）
│  劇本生成   │────▶│  圖片生成        │
│  Gemini LLM │     │  Gemini Imagen   │
└─────────────┘     ├──────────────────┤
                    │  語音合成        │
                    │  Gemini TTS      │
                    │  + faster-whisper│
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │    Stage 3       │
                    │  影片渲染        │
                    │  moviepy + ffmpeg│
                    └──────────────────┘
```

| Stage | 模組 | 模型 | 輸出 |
|-------|------|------|------|
| 1. 劇本生成 | `text_generator/` | `gemini-2.5-flash` | `script.json`（標題、場景旁白、圖片 prompt、SEO 標籤） |
| 2a. 圖片生成 | `image_generator/` | `gemini-2.5-flash-image` | `scene_0N.png`（依 ratio mode 決定長寬比） |
| 2b. 語音合成 | `audio_generator/` | `gemini-2.5-flash-preview-tts` + faster-whisper | `scene_0N.wav` + 逐字時間戳 |
| 3. 影片渲染 | `video_renderer/` | moviepy + ffmpeg | `output.mp4`（Ken Burns 效果、逐字字幕、轉場、BGM） |

每個 Stage 的輸出皆快取至 `workspace/`，中斷後可從斷點恢復。

---

## 設定檔速查（`configs/base_config.yaml`）

```yaml
# ── 影片內容 ──────────────────────────────────────────────
video_settings:
  target_word_count: "135 to 145"   # 約 60 秒語速
  max_scenes: 5                      # 每集場景數上限

# ── 模型選擇 ──────────────────────────────────────────────
llm_settings:
  model_name: "gemini-2.5-flash"
  temperature: 0.7

tts_settings:
  model_name: "gemini-2.5-flash-preview-tts"
  voice_name: "charon"    # 29 種聲音可選，完整列表見檔案內註解

image_settings:
  model_name: "gemini-2.5-flash-image"
  # 圖片比例模式（每個場景可各自不同）：
  #   all_16_9      — 全部橫式
  #   all_9_16      — 全部直式
  #   all_1_1       — 全部正方
  #   alternate     — 交替 16:9 / 9:16
  #   wide_first    — 第 1 場 16:9，其餘 9:16
  #   portrait_heavy — 9:16, 9:16, 16:9, 9:16, 9:16...
  scene_ratio_mode: "alternate"

# ── 短影音渲染（9:16, 1080×1920）────────────────────────
video_renderer:
  ken_burns_strategy: "alternate_lr"   # all_left_to_right | all_right_to_left
  zoom_strategy: "alternate"           # zoom_in | zoom_out
  zoom_amount: 0.12                    # 0.10–0.20，越大移動越明顯
  transition: "hard_cut"               # hard_cut | fade_black | crossfade
  caption_font_size: 100
  caption_highlight_color: "#FFD700"   # 當前詞高亮顏色
  caption_uppercase: true

# ── 長影音渲染（16:9, 1920×1080）────────────────────────
long_form_renderer:
  transition: "fade_black"

# ── 背景音樂 ──────────────────────────────────────────────
bgm_settings:
  enabled: true
  path: "assets/bgm/Ziv Moran - Shades - Dark.mp3"
  volume: 0.12        # 相對於 TTS（TTS = 1.0）
```

---

## Workspace 輸出結構

**Solo run：**

```
workspace/
└── run_20260521_221009/
    ├── script.json          # 劇本（標題、場景、SEO）
    ├── task_status.json     # 各 Stage 狀態
    ├── images/
    │   └── scene_01.png ... scene_05.png
    ├── audio/
    │   └── scene_01.wav ... scene_05.wav
    └── video/
        └── output.mp4
```

**Series run：**

```
workspace/
└── series_20260521_221153/
    ├── series_arc.json      # Arc 規劃（8 集大綱）
    ├── series_manifest.json # 各集狀態追蹤
    ├── ep01/
    │   ├── script.json
    │   ├── task_status.json
    │   ├── images/
    │   ├── audio/
    │   └── video/output.mp4
    ├── ep02/ ... ep08/
    └── long_form/
        └── output.mp4       # 合併長影音（combine_long_form: true 時生成）
```

---

## 工具（`tools/`）

### `aggregate_scripts.py` — 腳本聚合工具

將 series 資料夾內所有集數的 `script.json` 合併成單一 Markdown 檔，方便審閱或編輯。

```bash
# 輸出到 series_dir/exports/（預設）
python tools/aggregate_scripts.py workspace/series_20260520_232258

# 指定輸出目錄
python tools/aggregate_scripts.py workspace/series_20260520_232258 --out-dir output/
```

輸出：`series_20260520_232258_scripts.md`，包含每集標題、說明文字、標籤、逐場旁白。

---

## 模組獨立測試（`text_generator/run_test.py`）

只跑文字生成（不需要圖片/音訊環境），適合快速驗證 arc 品質或 prompt 效果。

```bash
# 從 job YAML 跑 series（arc + 所有集數）
python text_generator/run_test.py --job jobs/example_series.yaml --out-dir workspace/test_001

# CLI 參數指定 series
python text_generator/run_test.py --topic "Ancient Rome" --profile education --n-episodes 8 --out-dir workspace/test_001

# 單集
python text_generator/run_test.py --topic "Ancient Rome" --profile education --out-dir workspace/test_001

# 只印 prompt，不呼叫 API（零費用預覽）
python text_generator/run_test.py --job jobs/example_series.yaml --out-dir workspace/test_001 --provider prompt
```

| 參數 | 說明 |
|------|------|
| `--job PATH` | Job YAML 路徑 |
| `--topic TEXT` | 主題 |
| `--profile NAME` | Profile 名稱 |
| `--provider STR` | `gemini` / `openai` / `prompt`（prompt = 零費用，只印 prompt） |
| `--n-episodes INT` | 集數（>1 啟動 series + arc；0 或 1 = 單集） |
| `--out-dir PATH` | 輸出目錄（必填） |
| `--details TEXT` | 補充背景資料 |

---

## 專案結構

```
AI-Story-Project/
├── main.py                          # 流水線進入點
├── jobs/                            # Job YAML 構想庫
│   ├── example_series.yaml
│   └── example_anthology.yaml
├── configs/
│   ├── base_config.yaml             # 全域設定（模型、渲染、BGM）
│   ├── system_prompt.txt            # LLM 系統提示模板
│   ├── series_arc_prompt.txt        # Arc 規劃 LLM 提示
│   ├── anthology_topics_prompt.txt  # Anthology 自動主題生成提示
│   └── profiles/                    # 風格 YAML（10 個）
├── core/
│   ├── state_manager.py             # Solo run 狀態管理
│   └── series_state_manager.py      # Series workspace 管理
├── text_generator/
│   ├── llm_router.py                # ScriptRequest schema + prompt 組裝
│   ├── gemini_api.py                # Gemini LLM 適配器（含 retry）
│   ├── openai_api.py                # OpenAI 適配器
│   └── run_test.py                  # 獨立文字生成測試工具
├── image_generator/
│   ├── image_router.py              # 平行圖片生成
│   └── gemini_imagen_adapter.py
├── audio_generator/
│   ├── audio_router.py              # TTS + faster-whisper 逐場處理
│   └── gemini_tts_adapter.py
├── video_renderer/
│   ├── engine.py                    # 渲染主流程
│   ├── effects.py                   # Ken Burns / Zoom 策略
│   ├── captions.py                  # PIL 逐字高亮字幕
│   └── transitions.py               # TRANSITION_REGISTRY
├── series_planner/
│   ├── arc_planner.py               # Arc 規劃 LLM 呼叫
│   ├── episode_runner.py            # 單集 3-stage pipeline
│   ├── series_runner.py             # Series / Anthology orchestration
│   └── merger.py                    # 長影音合併
├── tools/
│   └── aggregate_scripts.py         # 腳本聚合工具
└── workspace/                       # 生成輸出（自動建立，不進 git）
```

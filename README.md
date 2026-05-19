# AI YouTube Shorts 自動化流水線

輸入一個主題與風格設定，自動產出可上傳的 YouTube Shorts MP4。

**輸入：** 主題字串 + 風格 Profile  
**輸出：** `workspace/{run_id}/video/output.mp4` — 1080×1920、H.264、旁白音訊、動態字幕

---

## 運作流程

```
主題 + Profile
      │
      ▼
┌─────────────┐     ┌──────────────┐
│  Stage 1    │     │   Stage 2    │  （平行執行）
│  劇本生成   │────▶│  圖片生成    │
│  (Gemini    │     │  (Gemini     │
│   LLM)      │     │   Image)     │
└─────────────┘     ├──────────────┤
                    │  語音合成    │
                    │  (Gemini TTS │
                    │  + Whisper)  │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   Stage 3    │
                    │  影片渲染    │
                    │  (moviepy)   │
                    └──────────────┘
```

- **Stage 1** — Gemini 生成結構化 JSON 劇本（標題、分場、圖片提示、SEO 標籤）
- **Stage 2** — 圖片與音訊平行生成；faster-whisper 產出逐字時間戳供字幕使用
- **Stage 3** — moviepy 合成：Ken Burns / Zoom 效果、逐字高亮字幕、可抽換轉場

每個 Stage 的輸出皆快取至 `workspace/`，中斷後可自動從斷點恢復。

---

## 環境需求

- Python 3.10+
- 專案根目錄建立 `.env`，填入 `GEMINI_API_KEY=你的金鑰`
- ffmpeg 需在系統 PATH 中（moviepy 依賴）

```
pip install google-genai pydantic python-dotenv pyyaml tenacity moviepy pillow opencv-python faster-whisper
```

---

## 快速開始

### 方式一：直接用 CLI（適合簡短描述）

```powershell
# 產生一支新影片
python main.py --topic "2008 金融海嘯" --profile finance

# 加上補充描述
python main.py --topic "2008 金融海嘯" --profile finance --details "聚焦雷曼兄弟，目標觀眾是對金融一無所知的 Z 世代。"

# 從指定的中斷 run 繼續（跳過已完成的 Stage）
python main.py --resume run_20260519_211046
```

### 方式二：Job YAML（適合長描述或重複使用的構想）

當描述很長，或希望把影片構想儲存起來重複使用時，將所有參數寫進 YAML 檔：

```powershell
python main.py --job jobs/2008_crisis.yaml
```

Job YAML 格式（可參考 `jobs/example.yaml`）：

```yaml
topic: "The 2008 Financial Crisis"
profile: finance
details: |
  Focus on Lehman Brothers and the mortgage bubble.
  Target audience: Gen Z who know nothing about finance.
  Key moments to highlight:
  - The housing bubble of 2003-2007
  - Subprime mortgages and CDOs
  - Lehman Brothers collapse in September 2008
  - The government bailout (TARP)
provider: gemini   # 選填，預設 gemini
```

若同時傳入 `--job` 和 CLI flags（如 `--profile comedy`），CLI 的值優先。

### 所有 CLI 參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `--topic` | 新 run 必填 | 影片核心主題 |
| `--details` | 空 | 補充描述、目標受眾、聚焦方向，注入至 LLM Prompt |
| `--profile` | `general` | 風格名稱（見下方 Profile 列表） |
| `--provider` | `gemini` | LLM 供應商（`gemini`） |
| `--job` | 無 | Job YAML 檔案路徑 |
| `--fresh` | 關 | 放棄尚未完成的 run、強制從頭重跑（有 `--topic`/`--job` 時不需要此旗標） |
| `--resume` | 無 | 指定要恢復的 `run_id` |

---

## Profiles

Profile 檔案放在 `configs/profiles/`，控制敘事語氣、開場 hook 風格、CTA 變體、禁用詞，以及注入每張圖片 Prompt 的視覺風格後綴。

| Profile | 說明 |
|---------|------|
| `comedy` | 輕鬆、簡短有力、荒誕感 |
| `education` | 清晰、結構化、適合初學者 |
| `finance` | 數據驅動、沉穩權威、無誇大成分 |
| `fitness` | 高能量、激勵感 |
| `gaming` | 熱情、貼近社群語氣 |
| `motivation` | 感染力強、情緒弧線 |
| `science` | 好奇心驅動、精準、充滿驚奇 |
| `cooking` | 感官描述、步驟清晰 |
| `general` | 中性 fallback |

新增 Profile：複製 `configs/profiles/` 下任一 YAML，調整欄位即可。

---

## 設定檔

所有可調整的參數集中在 `configs/base_config.yaml`：

```yaml
video_settings:
  target_word_count: "135 to 145"   # 控制約 60 秒語速
  min_scenes: 4
  max_scenes: 5

llm_settings:
  model_name: "gemini-2.5-flash"
  temperature: 0.7

tts_settings:
  model_name: "gemini-2.5-flash-preview-tts"
  voice_name: "charon"              # 完整聲音列表見檔案內註解
  sample_rate: 24000

image_settings:
  model_name: "gemini-2.5-flash-image"
  aspect_ratio: "16:9"

video_renderer:
  canvas_width: 1080
  canvas_height: 1920
  fps: 24
  ken_burns_strategy: "alternate_lr"     # alternate_lr | all_left_to_right | all_right_to_left
  zoom_strategy: "alternate"             # alternate | zoom_in | zoom_out
  transition: "hard_cut"                 # hard_cut | fade_black
  caption_words_per_group: 3
  caption_position_y_ratio: 0.65
  caption_font_size: 80
  caption_highlight_color: "#FFD700"
```

---

## 專案結構

```
AI-Story-Project/
├── main.py                        ← 流水線進入點
├── jobs/                          ← Job YAML 構想庫（影片參數存放區）
│   └── example.yaml
├── configs/
│   ├── base_config.yaml           ← 全域設定
│   ├── system_prompt.txt          ← LLM 系統提示模板
│   └── profiles/                  ← 各風格 YAML
│       ├── finance.yaml
│       ├── comedy.yaml
│       └── ...
├── core/
│   └── state_manager.py           ← Workspace 管理、快取、Stage 狀態追蹤
├── text_generator/
│   ├── gemini_api.py              ← Gemini LLM 適配器（含 retry）
│   └── llm_router.py              ← ScriptRequest schema + 路由邏輯
├── image_generator/
│   ├── gemini_imagen_adapter.py   ← Gemini 圖片生成適配器
│   └── image_router.py            ← 平行圖片生成
├── audio_generator/
│   ├── gemini_tts_adapter.py      ← Gemini TTS 適配器（PCM → WAV）
│   └── audio_router.py            ← TTS + faster-whisper 逐場處理
├── video_renderer/
│   ├── engine.py                  ← 渲染主流程
│   ├── effects.py                 ← Ken Burns / Zoom 效果策略
│   ├── captions.py                ← PIL 逐字高亮字幕渲染
│   └── transitions.py             ← TRANSITION_REGISTRY（hard_cut、fade_black）
└── workspace/
    └── run_YYYYMMDD_HHMMSS/       ← 每次 run 一個資料夾
        ├── script.json
        ├── task_status.json
        ├── images/
        │   ├── scene_01.png
        │   └── image_results.json
        ├── audio/
        │   ├── scene_01.wav
        │   └── audio_results.json
        └── video/
            └── output.mp4
```

---

## 擴充

### 新增 Ken Burns 策略
在 `video_renderer/effects.py` 的 `KEN_BURNS_STRATEGIES` 加一個 key：
```python
KEN_BURNS_STRATEGIES["my_strategy"] = lambda scene_idx: "left_to_right"
```
再把 `base_config.yaml` 的 `ken_burns_strategy` 改成 `"my_strategy"`。

### 新增轉場效果
在 `video_renderer/transitions.py` 的 `TRANSITION_REGISTRY` 加一個 key：
```python
TRANSITION_REGISTRY["my_transition"] = lambda clips: _my_fn(clips)
```
再把 `base_config.yaml` 的 `transition` 改成 `"my_transition"`。

### 單獨測試各 Stage
```powershell
python -m text_generator.llm_router
python -m image_generator.image_router
python -m audio_generator.audio_router
python -m video_renderer.engine
```
各模組從最新快取的 run 讀取素材，已標記 `completed` 的 Stage 會自動跳過。

---

## TODO

- [ ] 長影音模式：將 N 個 `run_id` 合併成一支完整影片
- [ ] 背景音樂混音
- [ ] 透過 YouTube Data API v3 自動上傳

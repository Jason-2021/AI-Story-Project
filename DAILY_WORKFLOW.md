# Daily Workflow — Anthology 日更操作手冊

完整流程分兩個階段：**一次性建庫**（初次執行）和**每日日更**（3 步驟）。

---

## 一、一次性建庫（初次執行）

目標：爬取破萬條主題存入 SQLite，夠撐 3.5 年日更不重複。

```bash
# Wikipedia（不需要帳號）
python tools/topic_scraper.py --source wiki:onthisday --date-range 01-01:12-31 --n 4000
python tools/topic_scraper.py --source wiki:dyk       --n 4000
python tools/topic_scraper.py --source wiki:unusual   --n 400

# Reddit（需要 PRAW 憑證，見 tools/REDDIT_APP_SETUP.md）
python tools/topic_scraper.py --source reddit:todayilearned --n 800
python tools/topic_scraper.py --source reddit:history       --n 500
python tools/topic_scraper.py --source reddit:science       --n 500
python tools/topic_scraper.py --source reddit:psychology    --n 300
python tools/topic_scraper.py --source reddit:business      --n 300
python tools/topic_scraper.py --source reddit:worldnews     --n 400
python tools/topic_scraper.py --source reddit:space         --n 300
```

完成後確認庫存：

```bash
python tools/job_builder.py --stats
```

---

## 二、每週補充爬蟲（可選）

當庫存低於 200 條時，用 `--recent` 模式快速補充（不重新爬整個存檔）：

```bash
python tools/topic_scraper.py --source wiki:dyk --n 50 --recent
python tools/topic_scraper.py --source reddit:todayilearned --n 100 --recent
```

---

## 三、每日日更（3 步驟）

### Step 1. 瀏覽候選主題（可選）

從 DB 匯出候選清單，人工挑選你想要的主題：

```bash
python tools/topic_browser.py --tag history --n 20
```

會在 `topics_bank/exports/` 產生一份 Markdown 檔，格式如下：

```markdown
### 1. [ ] TIL that Genghis Khan would marry off a daughter...
### 2. [ ] TIL the Great Wall of China is not visible from space...
```

用文字編輯器打開，把想要的改成 `[x]`，存檔後執行：

```bash
python tools/topic_browser.py --confirm topics_bank/exports/2026-05-31_history.md
```

這樣選中的主題會在 DB 裡標成 `status='selected'`，job_builder 會優先使用。

> 如果不想人工選，可以跳過 Step 1，job_builder 會自動從 `unused` 中撈取。

**可用的 tag 篩選：**

| Tag | 主題方向 |
|-----|---------|
| `history` | 歷史事件、被遺忘的決定 |
| `science` | 科學發現、反直覺事實 |
| `psychology` | 認知偏誤、人類行為 |
| `nature` | 動物行為、自然奇觀 |
| `technology` | 科技發明、數位歷史 |
| `medicine` | 醫學突破、身體冷知識 |
| `geography` | 地理反直覺、國界故事 |
| `law` | 奇怪法律、法庭案例 |
| `business` | 商業決策、企業崩壞 |
| `language` | 語言起源、詞語由來 |

**額外 style 篩選（可搭配 --tag 使用）：**

```bash
python tools/topic_browser.py --tag history --style counterintuitive --n 20
```

| Style | 說明 |
|-------|------|
| `counterintuitive` | 違反直覺的事實 |
| `record-breaking` | 之最、歷史紀錄 |
| `biographical` | 圍繞某個人物 |
| `statistics` | 含數字/統計 |
| `mystery` | 未解謎題 |
| `dark-history` | 黑暗歷史、道德衝突 |
| `event-based` | 圍繞一個具體事件 |

---

### Step 2. 生成 Job YAML

```bash
python tools/job_builder.py --tag history --profile evergreen --n 8
```

會自動：
1. 優先取 `status='selected'` 的主題，不夠再從 `unused` 補足
2. 選一個 anthology 標題（輪流使用，如 `"History Facts Your Textbook Never Taught You"`）
3. 輸出 `jobs/daily/YYYY-MM-DD_history_evergreen.yaml`

輸出範例：

```yaml
mode: anthology
title: "History Facts Your Textbook Never Taught You"
profile: evergreen
provider: gemini
topics:
  - "TIL Genghis Khan would marry off a daughter to the king..."
  - "TIL in 1916 there was a proposed Amendment to the US Constitution..."
  - ...
```

**參數說明：**

| 參數 | 說明 | 預設 |
|------|------|------|
| `--tag` | 主題類別（必填） | — |
| `--profile` | 風格 profile | `evergreen` |
| `--n` | 集數 | `8` |
| `--out` | 自訂輸出路徑 | 自動產生 |
| `--stats` | 顯示庫存統計，不生成 YAML | — |

---

### Step 3. 執行 Pipeline

```bash
python main.py --job jobs/daily/2026-05-31_history_evergreen.yaml
```

**測試模式（不呼叫真實 API）：**

```bash
# 只跑文字生成，不跑圖片/TTS
python main.py --job jobs/daily/2026-05-31_history_evergreen.yaml --text-only --provider prompt
```

---

## 四、DB 狀態說明

每筆主題在 DB 中有一個 `status` 欄位：

| Status | 說明 |
|--------|------|
| `unused` | 還沒用過，可被 job_builder 撈取 |
| `selected` | 人工從 topic_browser 選中，job_builder 優先使用 |
| `used` | 已被某個 anthology 使用 |
| `skipped` | 手動標記跳過 |
| `rejected` | 手動標記不適合 |

查看目前庫存：

```bash
python tools/job_builder.py --stats
python tools/topic_browser.py --stats
```

---

## 五、快速參考

```bash
# 庫存統計
python tools/job_builder.py --stats

# 瀏覽主題
python tools/topic_browser.py --tag <tag> --n 20

# 確認人工選題
python tools/topic_browser.py --confirm topics_bank/exports/<file>.md

# 生成 Job
python tools/job_builder.py --tag <tag> --profile evergreen --n 8

# 執行 Pipeline
python main.py --job jobs/daily/<yaml_file>
```

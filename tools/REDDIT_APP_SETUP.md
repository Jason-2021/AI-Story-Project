# Reddit App 申請流程

Reddit 爬蟲使用 PRAW（官方 Python Reddit API Wrapper），需要一組免費的 API 憑證。

---

## 前置條件

- 一個 Reddit 帳號（免費）
  - 如果還沒有：https://www.reddit.com/register

---

## 步驟

### 1. 前往 App 管理頁面

https://www.reddit.com/prefs/apps

登入後，頁面最下方會看到「are you a developer? create an app...」按鈕。

### 2. 建立新 App

填寫以下欄位：

| 欄位 | 填寫內容 |
|------|----------|
| name | `AI-Story-Project`（隨意） |
| **type** | **script**（一定要選這個） |
| description | 留空即可 |
| about url | 留空即可 |
| redirect uri | `http://localhost:8080`（隨便填，script app 不會用到） |

按 **[create app]**。

### 3. 複製 Key

建立後頁面會顯示你的 app，格式如下：

```
AI-Story-Project
personal use script

<這一行小字就是 client_id>   ← 複製這個
secret  <這裡是 client_secret>  ← 複製這個
```

- **client_id**：app 名稱下方那行小字（14 個字元左右）
- **client_secret**：`secret` 欄位旁邊的值（27 個字元左右）

### 4. 寫入 .env

在專案根目錄的 `.env` 加入：

```
REDDIT_CLIENT_ID=你的client_id
REDDIT_CLIENT_SECRET=你的client_secret
```

### 5. 安裝 PRAW

```bash
pip install praw
```

### 6. 測試

```bash
python tools/topic_scraper.py --source reddit:todayilearned --n 5 --dry-run
```

應該看到 5 筆 `[DRY]` 輸出，代表憑證正常。

---

## 注意事項

- **免費，個人用途不需要付費**：Reddit 免費 API 有 100 req/min 上限，PRAW 自動處理 rate limit，不需要手動 sleep。
- **不需要使用者登入**：script app 只讀取公開資料，不會動到你的 Reddit 帳號。
- **憑證安全**：`.env` 已在 `.gitignore` 中，不會被 commit。

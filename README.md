# pchome_telegram_bot

https://t.me/duckll_pchome_alarm_bot

PChome 24h 降價通知。

## 用法

- 直接貼商品網址（`https://24h.pchome.com.tw/prod/...`）就能新增，按 Yes 確認。
- `/list` 看目前監控的商品與上次價錢，`/delete` 刪除（刪了可以按「反悔」加回來）。
- 每小時（整點過 1 分）查一次價錢，**降價才通知**，漲價不通知。
- 商品連續 26 次查不到（一天多）就當作下架，通知後自動移除。

## 行為

- 單一程序：Telegram 用 polling（不需要對外開 port），每小時的檢查是同一個程序裡的 JobQueue。
- 呼叫 PChome API 前都等 1 秒並帶瀏覽器 User-Agent，失敗重試 5 次；PChome 回 `[]` 表示查無此商品。
- 新增商品時以當下價格為基準；同一商品多人監控時共用基準價。
- 發送通知時，某個使用者封鎖了 bot 或訊息格式出錯，不影響其他人；格式出錯會改送純文字。
- 狀態存 SQLite（`DB_PATH`），沿用 2022 年版本的資料表，舊的 `bot.db` 可以直接用。舊版留在對話裡的 `/list`、`/delete`、「反悔」按鈕仍然有效。

## 設定（`.env`）

| 變數 | 說明 | 預設 |
| --- | --- | --- |
| `BOT_TOKEN` | Telegram Bot token | 必填（`--check` 除外） |
| `DB_PATH` | SQLite 檔案 | `/data/bot.db` |
| `LOCAL_UID` / `LOCAL_GID` | Docker 執行身分 | `1000` |

## 執行

```bash
uv sync
uv run pytest -q && uv run ruff check .

DB_PATH=./data/bot.db uv run python bot.py --check   # 查一次所有價格，印出會送的通知；不寫入、不傳訊息
uv run --env-file .env python bot.py                 # 常駐
```

同一個 bot token 同時只能有一個程序在 polling（另一個會收到 `Conflict`），換機器時先停舊的。

## Docker

```bash
cp .env.example .env && chmod 600 .env   # 填入 BOT_TOKEN
mkdir -p data && chmod 700 data          # data 須由 LOCAL_UID 擁有；SQLite 要能在裡面建 -wal／-shm
docker compose build
docker compose run --rm bot --check
docker compose up -d
docker compose logs -f
```

以非 root、唯讀 rootfs、移除所有 capabilities 執行，只掛載可寫的 `./data`。

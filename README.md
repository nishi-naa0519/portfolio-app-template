# portfolio-app-template

React + TypeScript (Vite) のフロントエンドと FastAPI のバックエンドで構成された、ポートフォリオサイトのひな形です。

## ディレクトリ構成

```text
.
├── frontend/   # React + TypeScript + Vite
├── backend/    # FastAPI + Pydantic (uv で管理)
├── content/    # サイト固有コンテンツ (リポジトリには *.example.json のみ含める)
├── docs/       # デプロイ手順などのドキュメント
├── Dockerfile  # frontend をビルドし、FastAPI から配信する単一イメージ
└── .env.example
```

## 必要なもの

- Node.js 24 (LTS)
- Python 3.12 と [uv](https://docs.astral.sh/uv/)
- Docker (コンテナで起動する場合)

## ローカル起動

### 1. 環境変数

```sh
cp .env.example .env
```

`.env` は Git 管理外です。秘密情報は `.env.example` に書かないでください。

### 2. Backend (http://localhost:8000)

```sh
cd backend
uv sync
uv run --env-file ../.env uvicorn app.main:app --reload --port 8000
```

動作確認:

```sh
curl http://localhost:8000/api/health
# {"status":"ok"}
```

### お問い合わせ API (`POST /api/contact`)

受け付けた問い合わせを Firestore に保存し、Gmail API でサイト所有者へ通知します。

```text
React (フォーム) → FastAPI → Firestore (保存 + rate limit) → Gmail API (通知)
```

```sh
curl -X POST http://localhost:8000/api/contact   -H 'Content-Type: application/json'   -d '{"name":"Example User","email":"user@example.com","message":"Hello"}'
# {"status":"accepted"}  (HTTP 202)
```

| フィールド | 制約 |
| --- | --- |
| `name` | 必須、1〜100 文字 (前後の空白は除去) |
| `email` | 必須、メールアドレス形式、最大 254 文字 |
| `message` | 必須、1〜5000 文字 |
| `website` | 任意。honeypot 用 (フォームでは非表示にする)。値があれば受理したように見せて破棄 |

| status | 意味 |
| --- | --- |
| `202` | 受理 (保存済み)。Gmail 通知に失敗した場合も、保存できていれば 202 を返します (再送による重複を防ぐため。失敗はログに記録) |
| `422` | 入力値が不正、または未知のフィールドがある |
| `429` | rate limit を超過。`Retry-After` ヘッダーに再試行までの秒数 |
| `503` | 設定の不足、Firestore の障害など。内部の詳細は返しません |

**Abuse 対策** (値は環境変数で変更できます。`.env.example` を参照):

| 制限 | 既定値 | 環境変数 |
| --- | --- | --- |
| 同一 IP (IPv6 は /64 単位) | 3 件 / 時、5 件 / 日 | `CONTACT_RATE_LIMIT_IP_PER_HOUR`、`CONTACT_RATE_LIMIT_IP_PER_DAY` |
| サイト全体 | 20 件 / 日 (= Gmail 送信の上限) | `CONTACT_RATE_LIMIT_SITE_PER_DAY` |

- 時間の区切りは UTC の「時」「日」です (固定ウィンドウ)。受理した問い合わせだけを数え、超過したリクエストでは何も書き込みません。
- rate limit 用のデータ (`contact_rate_limits` コレクション) には、IP アドレスを秘密鍵付きハッシュ (HMAC-SHA256) にした値と件数だけを保存します。期限 (`expire_at`) を過ぎたものは Firestore の TTL で削除されます。
- 問い合わせ (`contacts` コレクション) には `name`・`email`・`message`・`created_at`・`status` (`unread`) だけを保存し、IP アドレスは保存しません。
- 問い合わせの内容はログに出力しません (ログには問い合わせ ID だけを出します)。

**ローカルで実際に保存・通知まで動かす場合**は、`.env` に Firestore のプロジェクトと Gmail の認証情報を設定し、`gcloud auth application-default login` で Application Default Credentials を用意してください。
設定がない場合も backend は起動しますが、`/api/contact` は `503` を返します。
GCP 側の準備 (OAuth クライアント、refresh token、Secret Manager、IAM、TTL) は [docs/deployment.md](docs/deployment.md) の「11. お問い合わせ機能 (Firestore・Gmail・Secret Manager)」を参照してください。

### 3. Frontend (http://localhost:5173)

別のターミナルで:

```sh
cd frontend
npm install
npm run dev
```

Vite の dev server は `/api` へのリクエストを `BACKEND_URL` (デフォルト `http://localhost:8000`) へ proxy します。
画面に `Backend status: ok` と表示されれば frontend から backend へ接続できています。
画面下部の Contact フォームから、お問い合わせ API を呼び出せます。

## Docker で起動

```sh
docker build -t portfolio-app .
docker run --rm -p 8080:8080 portfolio-app
```

- http://localhost:8080/ : frontend
- http://localhost:8080/api/health : `{"status":"ok"}`

## Cloud Run へのデプロイ

Google Cloud の Cloud Run へ deploy する手順は [docs/deployment.md](docs/deployment.md) にまとめています。
GCP プロジェクトの作成、Budget (通知のみ・Spend cap)、Service Account と権限、Artifact Registry、Firestore、Cloud Run の設定値とその理由、コスト防御と緊急停止の方法を扱います。

> Budget Alert は課金を止める機能ではありません。料金の上限は、max instances、Spend cap、通知のみの Budget を組み合わせて抑えます。詳しくは手順書の「コスト防御と緊急停止」を参照してください。

## 検証コマンド

Frontend:

```sh
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

Backend:

```sh
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## コンテンツ

`content/` にはサイト固有のコンテンツを JSON で置きます。
リポジトリには `*.example.json` のみを含め、実際のコンテンツ (`profile.json` など) は `.gitignore` で除外しています。

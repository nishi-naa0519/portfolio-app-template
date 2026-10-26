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
uv run uvicorn app.main:app --reload --port 8000
```

動作確認:

```sh
curl http://localhost:8000/api/health
# {"status":"ok"}
```

お問い合わせ API (現時点では保存・通知は行わず、受信内容を構造化ログへ出力するのみ):

```sh
curl -X POST http://localhost:8000/api/contact \
  -H 'Content-Type: application/json' \
  -d '{"name":"Example User","email":"user@example.com","message":"Hello"}'
# {"status":"accepted"}  (HTTP 202)
```

| フィールド | 制約 |
| --- | --- |
| `name` | 必須、1〜100 文字 (前後の空白は除去) |
| `email` | 必須、メールアドレス形式、最大 254 文字 |
| `message` | 必須、1〜5000 文字 |
| `website` | 任意。honeypot 用 (フォームでは非表示にする)。値があれば受理したように見せて破棄 |

不正なリクエストや未知のフィールドには `422` を返します。

### 3. Frontend (http://localhost:5173)

別のターミナルで:

```sh
cd frontend
npm install
npm run dev
```

Vite の dev server は `/api` へのリクエストを `BACKEND_URL` (デフォルト `http://localhost:8000`) へ proxy します。
画面に `Backend status: ok` と表示されれば frontend から backend へ接続できています。

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

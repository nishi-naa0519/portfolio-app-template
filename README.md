# portfolio-app-template

React + TypeScript (Vite) のフロントエンドと FastAPI のバックエンドで構成された、ポートフォリオサイトのひな形です。

## ディレクトリ構成

```text
.
├── frontend/   # React + TypeScript + Vite
├── backend/    # FastAPI + Pydantic (uv で管理)
├── content/    # サイト固有コンテンツ (リポジトリには *.example.json のみ含める)
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

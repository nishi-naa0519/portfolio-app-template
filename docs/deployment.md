# Cloud Run へのデプロイ

このテンプレートを、自分の Google Cloud プロジェクトの Cloud Run へ deploy する手順です。
コストを可用性より優先し、Always Free の範囲で運用することを目標にした構成です。

> [!IMPORTANT]
> 料金・無料枠・quota・Console の画面は変わることがあります。
> この手順は 2026-10 時点の公式ドキュメントで確認した内容に基づいています。
> 実際に作業するときは、各節にリンクした公式ドキュメントを確認してください。

## 構成

```text
組織 (あれば)
└─ プロジェクト <PROJECT_ID> ── 請求先アカウント <BILLING_ACCOUNT_ID>
   ├─ Artifact Registry  portfolio (Docker, <REGION>)   … コンテナイメージ
   ├─ Cloud Run          portfolio (<REGION>)           … FastAPI + ビルド済み frontend
   │    └─ 実行 SA       portfolio-runtime
   ├─ Firestore          (default) (Native, <REGION>)   … 問い合わせと rate limit の保存
   ├─ Secret Manager                                     … Gmail の認証情報と IP ハッシュ用の鍵
   ├─ OAuth クライアント (デスクトップ アプリ)            … Gmail API での通知メール送信
   └─ deploy 用 SA       portfolio-deployer              … 手元から impersonation で使う

請求先アカウント
├─ Budget (通知のみ)       請求先アカウント全体
└─ Budget (Spend cap)      <PROJECT_ID> × Cloud Run
```

- イメージは手元で `docker build` し、Artifact Registry へ push してから `gcloud run deploy --image` で deploy します。Cloud Build は使いません。
- 公開 URL は Cloud Run が発行する `https://portfolio-<PROJECT_NUMBER>.<REGION>.run.app` です。独自ドメインは使いません。
- 本書ではリージョン `<REGION>` を `asia-northeast1` (東京) として説明します。

## 凡例

| 記号 | 意味 |
| --- | --- |
| 🔒 | 作成後に変更できない (変えるには作り直しが必要、または名前が二度と使えない) |
| 🔁 | 後から変更できる |
| ⚠️ | 変更できるが影響が大きい (URL が変わる、データ移行が必要など) |

## 前提

- Google アカウントと、**有効な**請求先アカウント (後述)
- [Google Cloud CLI (gcloud)](https://cloud.google.com/sdk/docs/install)
- Docker (Cloud Run は `linux/amd64` のイメージを実行します)
- このリポジトリの clone (以下のコマンドはリポジトリのルートで実行します)

コマンドは PowerShell で書いています。bash の場合は、変数を `P=...` の形にし、行継続をバッククォート (`` ` ``) からバックスラッシュ (`\`) に読み替えてください。

```powershell
$P = "<PROJECT_ID>"                 # 例: my-portfolio-123456
$REGION = "asia-northeast1"
$BILLING = "<BILLING_ACCOUNT_ID>"   # 例: 000000-000000-000000
$ME = "<YOUR_GOOGLE_ACCOUNT_EMAIL>"
$RUNTIME = "portfolio-runtime@$P.iam.gserviceaccount.com"
$DEPLOYER = "portfolio-deployer@$P.iam.gserviceaccount.com"
```

作業の前に、gcloud が意図したアカウントで動いているかを確認してください。

```powershell
gcloud auth list
gcloud config list
```

本書のコマンドはすべて `--project` を明示するので、gcloud の既定プロジェクトを変更する必要はありません。

---

## 1. 請求先アカウント

Cloud Run などを使うには、プロジェクトを**有効な**請求先アカウントに紐づける必要があります。
Always Free の無料枠も、請求先アカウントが有効な状態でなければ適用されません。
([Free Tier](https://docs.cloud.google.com/free/docs/free-cloud-features))

状態を確認します。

```powershell
gcloud billing accounts list    # OPEN が True のものを使う
```

- **有効なアカウントがない場合:** Console の「お支払い > 請求先アカウントを管理」→「アカウントを作成」から作成します。gcloud の作成コマンドは文書化されていません。
  - 🔒 請求先アカウントは、作成後に削除も取り消しもできません。
  - 🔒 国は、作成後に変更できません。
- **閉鎖されたアカウントがある場合:** 「再開」できることがあります。ただし、**期限切れの無料トライアルのアカウントは再開できません**。Console に「有効期限の切れた無料トライアル アカウントであるため、再開することはできません」と表示されます。その場合は、新しいアカウントを作成してください。
- **新しく作るアカウントが「無料トライアル」になる場合は注意してください。** トライアルのアカウントは、期間の終了やクレジットの使い切りで自動的に閉鎖されます。
- **閉鎖したアカウントを再開する場合は注意してください。** 再開すると、そのアカウントに紐づいたままのプロジェクトで料金が発生し始めます。不要なプロジェクトは、先に `gcloud billing projects unlink <OLD_PROJECT_ID>` で切り離してください。

参考:
- https://docs.cloud.google.com/billing/docs/how-to/create-billing-account
- https://docs.cloud.google.com/billing/docs/how-to/close-or-reopen-billing-account

## 2. Budget (通知のみ) を作成する

**リソースを作る前に**作成します。

> [!WARNING]
> **通知のみの Budget は、課金を止める機能ではありません。**
> しきい値を超えたときにメールが届くだけで、サービスも課金も止まりません。
> また、費用が反映されるまでには遅延があり、最初の通知まで数時間かかることがあります。
> ([budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets))

| 項目 | 値 | |
| --- | --- | --- |
| 名前 | `billing-account-monthly` | 🔁 |
| 種類 | Alerts only (通知のみ) | |
| 範囲 | 請求先アカウント全体 (すべてのプロジェクト・すべてのサービス) | 🔁 |
| 期間 / 金額 | 月次 / 指定額 (例: ¥1,000) | 🔁 |
| しきい値 | 実績 10%・50%・90%・100%、予測 100% | 🔁 |
| 通知先 | 請求先アカウントの管理者とユーザーへのメール (既定) | 🔁 |

**Console での手順**
1. 「お支払い」を開き、請求先アカウントを選ぶ
2. 「Cost control > **Budgets & caps**」→「**Create new**」
3. 種類に **Alerts only** を選び、上の表のとおりに入力する
4. 既定のしきい値は 50%・90%・100% なので、10% (実績) と 100% (予測) を追加する

**gcloud で作成する場合** (Cloud Billing Budget API `billingbudgets.googleapis.com` の有効化が必要)

```powershell
gcloud billing budgets create `
  --billing-account=$BILLING `
  --display-name=billing-account-monthly `
  --budget-amount=1000JPY `
  --threshold-rule=percent=0.1 `
  --threshold-rule=percent=0.5 `
  --threshold-rule=percent=0.9 `
  --threshold-rule=percent=1.0 `
  --threshold-rule=percent=1.0,basis=forecasted-spend
```

`--budget-amount` の通貨は、請求先アカウントの通貨に合わせてください。

## 3. プロジェクトを作成し、請求先アカウントに紐づける

| 項目 | 値 | |
| --- | --- | --- |
| プロジェクト ID | 任意 (6〜30 文字、英小文字・数字・ハイフン) | 🔒 削除しても同じ ID は再利用できない |
| プロジェクト名 | 任意 | 🔁 |
| 親 | 組織がある場合は組織の下 | ⚠️ 移動はできるが、継承されるポリシーが変わる |

**Console での手順**
1. プロジェクト選択 →「新しいプロジェクト」
2. 名前と ID を入力する。希望の ID が使用済みのときは、Console が接尾辞付きの ID を提案します
3. 作成後、「お支払い」から請求先アカウントをリンクする

**gcloud**

```powershell
gcloud projects create $P --name="portfolio"    # 組織の下に作る場合は --organization=<ORG_ID>
gcloud billing projects link $P --billing-account=$BILLING
gcloud billing projects describe $P             # billingEnabled: true になっていれば OK
```

`PROJECT_NUMBER` は、Cloud Run の URL に使われます。

```powershell
gcloud projects describe $P --format="value(projectNumber)"
```

参考: https://docs.cloud.google.com/resource-manager/docs/creating-managing-projects

## 4. API を有効にする

```powershell
gcloud services enable `
  run.googleapis.com `
  artifactregistry.googleapis.com `
  firestore.googleapis.com `
  secretmanager.googleapis.com `
  gmail.googleapis.com `
  iam.googleapis.com `
  iamcredentials.googleapis.com `
  --project=$P
```

| API | 理由 |
| --- | --- |
| `run` | Cloud Run |
| `artifactregistry` | コンテナイメージの保存 |
| `firestore` | Firestore (App Engine は不要) |
| `secretmanager` | 秘密情報の保存 (11. を参照) |
| `gmail` | 問い合わせの通知メール (11. を参照) |
| `iam` | Service Account の作成 |
| `iamcredentials` | Service Account の impersonation (短命トークンの発行) |

**有効にしない API**
- **Cloud Build** (`cloudbuild.googleapis.com`): 手元でビルドするため不要です。`gcloud run deploy --source` を使う場合は、Cloud Build と Compute Engine デフォルト SA の権限設定が別途必要になります。([deploying-source-code](https://docs.cloud.google.com/run/docs/deploying-source-code))
- **Cloud Billing Budget API**: Budget を Console で作るなら不要です。

API を有効にすること自体には、料金はかかりません。

Console では「API とサービス > ライブラリ」から、各 API を検索して有効にします。

## 5. Budget (Spend cap) を作成する

**Spend cap budget** は、指定したプロジェクトの指定したサービスについて、費用が目標額を超えたときに、**その月の残りの新しい使用を自動で一時停止**する機能です。
Cloud Run (`run.googleapis.com`) が対象サービスに含まれています。
([budgets-spend-caps](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps))

| 項目 | 値 | |
| --- | --- | --- |
| 名前 | `portfolio-cloudrun-cap` | 🔁 |
| 範囲 | 1つのプロジェクト (`<PROJECT_ID>`) × 1つのサービス (Cloud Run) | |
| 期間 | 月次 (固定) | |
| 目標金額 | 例: ¥500 | 🔁 |
| 通知 | 50%・80%・100% で、請求先アカウントの管理者とプロジェクトのオーナーへ (変更不可) | |

**Console での手順**
1. 「お支払い > Budgets & caps」→「Create new」
2. **Spend cap enforcement** を選び、名前を入力する
3. プロジェクトとサービス (`Cloud Run`。`Cloud Run functions` ではない) を1つずつ選ぶ
4. 目標金額を入力し、「Finish」

gcloud での作成コマンドは文書化されていません (Console か Cloud Billing Budget API で作成します)。

**Spend cap の注意点**
- 停止は即時ではありません。それまでに発生した超過分は、通常どおり請求されます。
- サービスによっては、費用を**割引 (無料枠を含む) を差し引く前の推定額**で判定します。そのため、請求額が 0 円のうちに一時停止することもあります。普段の利用額の数倍を目安に、目標金額を決めてください。
- 一時停止しても、リソースやデータは削除されません。翌月1日に自動で解除されます。手動で解除することもできます。
- 通知のみの Budget を、後から Spend cap に変換することはできません。

## 6. Service Account と IAM

権限は「誰が (principal)」「何を (role)」「どこに対して (resource)」の組み合わせで付与します。
付与する範囲は、できるだけ狭くします。

| principal | role | resource | 理由 |
| --- | --- | --- | --- |
| `portfolio-runtime` | Cloud Datastore ユーザー (`roles/datastore.user`) | プロジェクト | 問い合わせと rate limit を Firestore に読み書きするため (11-e で付与) |
| `portfolio-runtime` | Secret Manager のシークレット アクセサー (`roles/secretmanager.secretAccessor`) | **お問い合わせ用の 3 つの secret のみ** | 実行時に secret を読むため (11-e で付与) |
| `portfolio-deployer` | Cloud Run デベロッパー (`roles/run.developer`) | プロジェクト | 初回 deploy でサービスを作成し、以降は更新するため |
| `portfolio-deployer` | サービス アカウント ユーザー (`roles/iam.serviceAccountUser`) | **`portfolio-runtime` のみ** | Cloud Run に実行 SA を割り当てるため |
| `portfolio-deployer` | Artifact Registry 書き込み (`roles/artifactregistry.writer`) | **repository `portfolio` のみ** (7. で付与) | イメージを push するため |
| deploy する人 | サービス アカウント トークン作成者 (`roles/iam.serviceAccountTokenCreator`) | **`portfolio-deployer` のみ** | deployer を impersonate するため |

設計上のポイント:
- **SA キー (JSON) は作りません。** 手元からは impersonation で、約1時間有効な短命トークンを使います。組織によっては、組織ポリシー `iam.disableServiceAccountKeyCreation` でキーの作成自体が禁止されています。
- deployer には **Cloud Run 管理者 (`roles/run.admin`) を与えません**。公開設定 (8-c) に必要な `run.services.setIamPolicy` は管理者にしか含まれないため、公開設定は初回だけプロジェクトのオーナーが行います。公開済みのサービスへの2回目以降の deploy は、deployer の権限だけで行えます (公開設定は保たれます)。
- Artifact Registry の「編集者」(`roles/artifactregistry.editor`) は、repository の削除やクリーンアップポリシーの変更までできてしまいます。「**書き込み**」(`writer`) と取り違えないでください。
- 実行 SA を指定しないと、Cloud Run は Compute Engine のデフォルト SA で動きます。これは避けるよう推奨されています。([service-identity](https://docs.cloud.google.com/run/docs/securing/service-identity))
- SA の ID (メールアドレス) は 🔒、表示名とロールは 🔁 です。

```powershell
gcloud iam service-accounts create portfolio-runtime --project=$P `
  --display-name="portfolio-runtime" --description="Runtime identity for the portfolio Cloud Run service"
gcloud iam service-accounts create portfolio-deployer --project=$P `
  --display-name="portfolio-deployer" --description="Deploys the portfolio service (used via impersonation)"

gcloud projects add-iam-policy-binding $P `
  --member="serviceAccount:$DEPLOYER" --role="roles/run.developer" --condition=None

gcloud iam service-accounts add-iam-policy-binding $RUNTIME --project=$P `
  --member="serviceAccount:$DEPLOYER" --role="roles/iam.serviceAccountUser"

gcloud iam service-accounts add-iam-policy-binding $DEPLOYER --project=$P `
  --member="user:$ME" --role="roles/iam.serviceAccountTokenCreator"
```

Console での手順:
- SA の作成: 「IAM と管理 > サービス アカウント > サービス アカウントを作成」。作成時の「権限」と「プリンシパル」は空のままにします。
- プロジェクトに対するロール: 「IAM と管理 > **IAM** > アクセス権を付与」
- **SA に対するロール**: 「サービス アカウント」一覧で対象の SA を開き、「**権限**」タブ →「アクセス権を付与」。プロジェクトの IAM 画面で付与すると、プロジェクト内のすべての SA が対象になってしまうので注意してください。

## 7. Artifact Registry

| 項目 | 値 | |
| --- | --- | --- |
| repository 名 | `portfolio` | 🔒 |
| 形式 / モード | Docker / 標準 | 🔒 |
| ロケーション | `<REGION>` (Cloud Run と同じリージョン) | 🔒 |
| 暗号化 | Google が管理する鍵 | 🔒 |
| 脆弱性スキャン | 無効 (有効にするとスキャン料金がかかる) | 🔁 |
| クリーンアップ | 1日より古いものは削除、ただし最新3バージョンは保持 | 🔁 |

- 無料枠は 0.5 GB/月 (請求先アカウント単位) です。同じリージョンの Cloud Run への転送は無料です。([pricing](https://docs.cloud.google.com/artifact-registry/pricing))
- クリーンアップポリシーでは、保持の条件が削除の条件より優先されます。そのため、結果として最新3バージョンだけが残ります。反映には最大1日ほどかかります。([cleanup-policy](https://docs.cloud.google.com/artifact-registry/docs/repositories/cleanup-policy))
- ポリシーの定義は [`artifact-registry-cleanup-policy.json`](artifact-registry-cleanup-policy.json) にあります。

```powershell
gcloud artifacts repositories create portfolio --project=$P `
  --location=$REGION --repository-format=docker `
  --description="Container images for the portfolio Cloud Run service"

# 適用前に影響を確認したい場合は、--no-dry-run の代わりに --dry-run を指定する
gcloud artifacts repositories set-cleanup-policies portfolio --project=$P `
  --location=$REGION --policy=docs/artifact-registry-cleanup-policy.json --no-dry-run

gcloud artifacts repositories add-iam-policy-binding portfolio --project=$P `
  --location=$REGION --member="serviceAccount:$DEPLOYER" --role="roles/artifactregistry.writer"
```

Console では「Artifact Registry > リポジトリ > リポジトリを作成」から作成します。
権限の付与は、一覧で repository にチェックを入れ、情報パネルの「権限」タブから行います。

## 8. ビルド・push・deploy

### 8-a. build と push

`docker build` がイメージにするのは、git の commit ではなく**作業フォルダにあるファイル**です。
タグに commit ID を使うので、変更を commit し、`git status` で変更が残っていないことを確認してから実行してください (先に `$TAG` を取ると、タグと中身がずれます)。
Docker Desktop が起動していないと、`failed to connect to the docker API` というエラーになります。

```powershell
git status                          # nothing to commit, working tree clean を確認
$TAG = git rev-parse --short HEAD   # 今の commit ID の短縮形
$IMAGE = "$REGION-docker.pkg.dev/$P/portfolio/portfolio:$TAG"

# deployer の短命トークン (約1時間有効) で docker login する
gcloud auth print-access-token --impersonate-service-account=$DEPLOYER |
  docker login -u oauth2accesstoken --password-stdin "https://$REGION-docker.pkg.dev"

docker build --platform linux/amd64 --provenance=false --sbom=false -t $IMAGE .
docker push $IMAGE
```

- `gcloud auth configure-docker` は使いません。使うと、deployer ではなく自分自身の権限で push されてしまいます。
- `--provenance=false --sbom=false` を付ける理由: Docker Desktop の既定では、来歴情報 (attestation) を付けたイメージインデックスが push されます。そうなると、1回の push で Artifact Registry 上に3つのバージョンができ、クリーンアップポリシーの「最新3つを保持」が想定どおりに働きません。

### 8-b. deploy

```powershell
gcloud run deploy portfolio `
  --project=$P --region=$REGION `
  --image=$IMAGE `
  --service-account=$RUNTIME `
  --cpu=1 --memory=512Mi --concurrency=20 --timeout=15 `
  --cpu-throttling --no-cpu-boost `
  --min=0 --max=1 --min-instances=0 --max-instances=1 `
  --impersonate-service-account=$DEPLOYER
```

お問い合わせ機能を使う場合は、先に 10. と 11. の準備を済ませ、上のコマンドに次の環境変数を加えます (11-f を参照)。

```powershell
  --update-env-vars="CONTACT_NOTIFY_TO=$NOTIFY_TO,GMAIL_OAUTH_CLIENT_ID=$CLIENT_ID,GMAIL_OAUTH_CLIENT_SECRET_SECRET_VERSION=projects/$P/secrets/gmail-oauth-client-secret/versions/latest,GMAIL_REFRESH_TOKEN_SECRET_VERSION=projects/$P/secrets/gmail-refresh-token/versions/latest,CONTACT_IP_HASH_KEY_SECRET_VERSION=projects/$P/secrets/contact-ip-hash-key/versions/latest"
```

- 初回に `Allow unauthenticated invocations to [portfolio] (y/N)?` と聞かれたら、`N` と答えてください。deployer には公開設定の権限がないためです。公開設定は 8-c で行います。
- 2回目以降の deploy も、同じコマンドで行います。

Console で deploy すると、操作する人自身の権限で実行されます (impersonation はできません)。その場合は、「Cloud Run > サービスをデプロイ」で、下の表と同じ値を設定してください。

### 8-c. 公開する (初回のみ。プロジェクトのオーナーが実行)

```powershell
# impersonation を付けずに、自分 (オーナー) の権限で実行する
gcloud run services update portfolio --project=$P --region=$REGION --no-invoker-iam-check
```

- Cloud Run の Invoker IAM チェック (呼び出し元を IAM で確認する仕組み) を無効にして、誰でもアクセスできるようにします。公式に推奨されている方法です。([authenticating/public](https://docs.cloud.google.com/run/docs/authenticating/public))
- 古い gcloud のヘルプには、このフラグが「招待制の機能」と書かれていることがありますが、2026-10 時点では gcloud 550.0.0 で動作しました。
- 使えない環境では、代わりに `gcloud run services add-iam-policy-binding portfolio --project=$P --region=$REGION --member=allUsers --role=roles/run.invoker` を使います。ただし、組織ポリシーで `allUsers` への付与が禁止されている場合は使えません。
- Console では「Cloud Run > portfolio > セキュリティ」タブで、認証を「**パブリック アクセスを許可**」にします。

### 8-d. 確認

```powershell
curl.exe "https://portfolio-<PROJECT_NUMBER>.$REGION.run.app/api/health"
# {"status":"ok"}

curl.exe -o NUL -w "%{http_code}" "https://portfolio-<PROJECT_NUMBER>.$REGION.run.app/openapi.json"
# 404 (API ドキュメントは Cloud Run 上では無効)

gcloud run services describe portfolio --project=$P --region=$REGION
```

`describe` の出力では、次の値を確認します。

| 項目 | 期待値 |
| --- | --- |
| `run.googleapis.com/invoker-iam-disabled` | `'true'` |
| `run.googleapis.com/maxScale` (サービス単位) と `autoscaling.knative.dev/maxScale` (リビジョン単位) | `'1'` |
| `minScale` | 指定なし (= 0) |
| `containerConcurrency` / `timeoutSeconds` | `20` / `15` |
| `cpu` / `memory` | `'1'` / `512Mi` |
| `run.googleapis.com/cpu-throttling` / `run.googleapis.com/startup-cpu-boost` | `'true'` / `'false'` |
| `serviceAccountName` | `portfolio-runtime@...` |

Console では、「Cloud Run > portfolio」の「スケーリング」タブ (最小・最大インスタンス、課金、タイムアウト、同時実行) と、「セキュリティ」タブ (認証、サービスアカウント) で確認できます。

## 9. Cloud Run の設定値と理由

| 設定 | 値 | 理由 | |
| --- | --- | --- | --- |
| サービス名 | `portfolio` | | 🔒 名前は公開され、URL の一部になる |
| リージョン | `asia-northeast1` | 閲覧者に近い。Tier 1 料金で、無料枠も us-central1 と同等 | ⚠️ 変えるには別サービスとして作り直す。URL が変わる |
| min instances | 0 | 待機中は課金されない | 🔁 |
| max instances | 1 | CPU とメモリの費用の上限を決める (ただし、一時的に超えることがあると明記されている) | 🔁 |
| CPU | 1 | 1 未満にすると、concurrency = 1 などが強制され、静的ファイルの配信まで直列になる | 🔁 |
| Memory | 512 MiB | 既定値。この規模のアプリには十分 | 🔁 |
| 課金方式 | リクエストベース (`--cpu-throttling`) | リクエストの処理中・起動中・終了処理中だけ課金される。インスタンスベースは待機中も課金される | 🔁 |
| Concurrency | 20 | max = 1 なので、値はコストに影響しない。512 MiB の1台を過負荷から守るため、既定の 80 より控えめにした (詳しくは [cost-defense.md](cost-defense.md) の 3.) | 🔁 |
| Timeout | 15 秒 | 既定は 300 秒。異常に長いリクエストで課金時間が延びるのを防ぐ (詳しくは [cost-defense.md](cost-defense.md) の 3.) | 🔁 |
| 起動時 CPU ブースト | 無効 (`--no-cpu-boost`) | 新しいサービスでは既定で有効。ブースト中は追加の CPU 分も課金され、アクセスの少ないサイトではコールドスタートのたびに追加課金になる | 🔁 |
| 認証 | 公開 (`--no-invoker-iam-check`) | 公開 Web サイトのため | 🔁 |
| 実行 SA | `portfolio-runtime` | 最小権限のため。Compute Engine のデフォルト SA を避ける | 🔁 |

参考:
- https://cloud.google.com/run/pricing
- https://docs.cloud.google.com/run/docs/configuring/billing-settings
- https://docs.cloud.google.com/run/docs/configuring/services/cpu
- https://docs.cloud.google.com/run/docs/configuring/cpu
- https://docs.cloud.google.com/run/docs/about-concurrency
- https://docs.cloud.google.com/run/docs/configuring/request-timeout
- https://docs.cloud.google.com/run/docs/configuring/max-instances

## 10. Firestore

問い合わせの保存と、問い合わせ API の rate limit に使います。

| 項目 | 値 | |
| --- | --- | --- |
| データベース ID | `(default)` | 🔒 無料枠が付くのは `(default)` だけ |
| エディション | Standard | 🔒 |
| モード | Native | 🔒 |
| ロケーション | `<REGION>` (リージョン) | 🔒 |
| セキュリティルール | すべて拒否 (本番環境モード) | 🔁 |
| 削除保護 | 有効 | 🔁 |
| PITR / バックアップ | 無効 (無料枠の対象外) | 🔁 |

```powershell
gcloud firestore databases create --project=$P `
  --database="(default)" --location=$REGION `
  --edition=standard --type=firestore-native --delete-protection

gcloud firestore databases describe --database="(default)" --project=$P
# freeTier: true、deleteProtectionState: DELETE_PROTECTION_ENABLED を確認する
```

- Console で作成するときは、セキュリティルールに「**本番環境**」を選んでください。「テスト」モードを選ぶと、期限までインターネットから誰でも読み書きできる状態になります。
- 作成後、「ルール」タブが `allow read, write: if false;` になっていることを確認してください (gcloud ではルールを読めません)。
- Console で作成すると、削除保護が無効のまま作られることがあります。その場合は `gcloud firestore databases update --database="(default)" --delete-protection --project=$P` で有効にします。
- 無料枠: 保存容量 1 GiB、読み取り 5万/日、書き込み 2万/日、削除 2万/日、外向き通信 10 GiB/月。TTL による削除は無料枠の対象外です。([pricing](https://docs.cloud.google.com/firestore/pricing))

**アプリが使うコレクション**

| コレクション | 内容 | 削除 |
| --- | --- | --- |
| `contacts` | 問い合わせ (`name`・`email`・`message`・`created_at`・`status`)。IP アドレスは保存しない | 自動では削除しない |
| `contact_rate_limits` | rate limit のカウンタ (`count`・`expire_at`)。ドキュメント ID に IP の HMAC ハッシュと時間枠を含む | `expire_at` を TTL で削除 |

1 件の問い合わせを受理するときの操作は、読み取り 3 件・書き込み 4 件 (1 つのトランザクション) です。
rate limit を超えたリクエストは読み取り 3 件だけで、書き込みはしません。超えたカウンタはインスタンスのメモリに記憶し、同じ時間枠の間の後続のリクエストは Firestore を読まずに `429` にします。
書き込みはサイト全体の上限 (既定 20 件/日) で抑えられるため、TTL による削除も 1 日あたり数十件以下です (TTL の削除料金は 10 万件あたり $0.01 前後。2026-10 時点の us-central1)。

**TTL ポリシー** (rate limit 用のデータを無期限に溜めないため。プロジェクトのオーナーが実行)

```powershell
gcloud firestore fields ttls update expire_at --project=$P `
  --collection-group=contact_rate_limits --enable-ttl

gcloud firestore fields ttls list --project=$P   # state: ACTIVE になれば OK (10 分以上かかることがある)
```

- TTL による削除は、通常は期限切れから 24 時間以内に行われます。期限切れのデータが残っていても、時間枠ごとに別のドキュメントを使うので rate limit の判定には影響しません。([ttl](https://docs.cloud.google.com/firestore/docs/ttl))
- Console では「Firestore > (default) > TTL」から、コレクション グループ `contact_rate_limits`、フィールド `expire_at` で作成します。

**インデックスの除外** (検索に使わないフィールドのインデックスを作らないため。プロジェクトのオーナーが実行)

```powershell
gcloud firestore indexes fields update message --project=$P `
  --collection-group=contacts --disable-indexes
gcloud firestore indexes fields update expire_at --project=$P `
  --collection-group=contact_rate_limits --disable-indexes
gcloud firestore indexes fields update count --project=$P `
  --collection-group=contact_rate_limits --disable-indexes

gcloud firestore indexes fields list --project=$P   # 3 つのフィールドが表示されれば OK
```

- アプリはドキュメント ID で読み書きするだけで、クエリを使わないため、除外しても動作は変わりません。TTL は、インデックスのないフィールドでも動作します。
- 理由は [cost-defense.md](cost-defense.md) の「4. Firestore」を参照してください。
- Console では「Firestore > (default) > インデックス > 単一フィールド > 除外を追加」から設定します (コレクション ID とフィールドを指定し、すべてのインデックスを無効にする)。

## 11. お問い合わせ機能 (Firestore・Gmail・Secret Manager)

```text
ブラウザ → Cloud Run (FastAPI) ─┬→ Firestore: rate limit の確認と問い合わせの保存 (1 トランザクション)
                                ├→ Secret Manager: 認証情報の読み取り (インスタンスごとに初回の問い合わせ時だけ)
                                └→ Gmail API: 通知メールの送信 (保存に成功した問い合わせだけ)
```

- 通知は、OAuth で許可した Gmail アカウントから `CONTACT_NOTIFY_TO` 宛てに送ります。From はそのアカウントになり、Reply-To は問い合わせした人のアドレスです。
- 通知先のアドレスは API の応答に含めません。
- Google Cloud のクライアント ライブラリと secret は、最初の問い合わせのときに読み込みます。ページを閲覧するだけでは、Firestore・Secret Manager・Gmail API へのアクセスは発生しません。

### 11-a. OAuth 同意画面 (Console のみ)

個人の Gmail アカウントから Gmail API でメールを送るには、OAuth 2.0 の refresh token を使います (Workspace のドメイン全体の委任は、個人の Gmail では使えません)。

「**Google Auth Platform**」(旧「API とサービス > OAuth 同意画面」) で設定します。

| 項目 | 値 | |
| --- | --- | --- |
| アプリ名 | 任意 (例: `portfolio-contact`)。認可の画面に表示される | 🔁 |
| ユーザー サポートメール / デベロッパーの連絡先 | 自分のメールアドレス | 🔁 |
| 対象 (User type) | **外部** (個人の Gmail アカウントは、組織の「内部」ユーザーではないため) | ⚠️ |
| 公開ステータス | **本番環境 (In production)** | 🔁 |

> [!IMPORTANT]
> 公開ステータスが「**テスト中**」のままだと、テストユーザーの認可は **7 日で失効し、refresh token も失効**します (通知が止まります)。
> 「対象」の画面で「**アプリを公開**」を押し、本番環境にしてください。
> `gmail.send` は「機密性の高いスコープ」なので、確認 (verification) を受けていないアプリでは、認可するときに「Google はこのアプリを確認していません」と表示されます。
> 自分のアカウントで使うだけなら、「詳細」→「(アプリ名) に移動」で進めます。未確認のアプリを認可できるユーザーは、合計 100 人までに制限されます。
> ([Manage App Audience](https://support.google.com/cloud/answer/15549945)、[OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)、[Gmail API のスコープ](https://developers.google.com/workspace/gmail/api/auth/scopes))

refresh token は、ほかにも次の場合に失効します。失効したら 11-c をやり直して、secret に新しいバージョンを追加します。
- 6 か月間使われなかったとき
- アカウントのパスワードを変更したとき (Gmail のスコープを含むため)
- 同じクライアントで 100 個を超える refresh token を発行したとき (古いものから無効になる)
- アカウントの「サードパーティ製のアプリとサービス」から、アクセス権を削除したとき

### 11-b. OAuth クライアントを作成する (Console のみ)

「Google Auth Platform > クライアント > クライアントを作成」で作成します。

| 項目 | 値 | |
| --- | --- | --- |
| アプリケーションの種類 | **デスクトップ アプリ** (11-c のスクリプトが、ローカルの一時的なポートで認可コードを受け取るため) | 🔒 |
| 名前 | 任意 (例: `portfolio-gmail-sender`) | 🔁 |

作成後に表示されるクライアント ID とクライアント シークレットを控えます。
JSON をダウンロードした場合は、リポジトリの外に置いてください (`client_secret*.json` は `.gitignore` 済みです)。

### 11-c. refresh token を取得する

通知メールを**送信する** Gmail アカウントでログインし、`gmail.send` (メールの送信のみ) を許可します。

```powershell
cd backend
$env:GMAIL_OAUTH_CLIENT_ID = "<CLIENT_ID>"
# クライアント シークレットは、環境変数で渡さなければ入力を求められます (画面には表示されません)
uv run --with google-auth-oauthlib python scripts/get_gmail_refresh_token.py |
  gcloud secrets create gmail-refresh-token --project=$P --replication-policy=automatic --data-file=-
cd ..
```

- ブラウザが開きます。送信に使う Gmail アカウントを選び、未確認アプリの警告 (11-a) を進めて許可します。
- スクリプトは refresh token だけを標準出力に書きます。上のようにパイプで secret に直接保存すれば、画面やファイルに残りません。
- `google-auth-oauthlib` は `--with` で一時的に使うだけで、アプリの依存関係には含めません。
- 2 回目以降 (secret が既にある場合) は、`gcloud secrets create ... --replication-policy=automatic` の代わりに `gcloud secrets versions add gmail-refresh-token --project=$P --data-file=-` を使います。

### 11-d. Secret Manager に secret を作成する

| secret ID | 内容 | |
| --- | --- | --- |
| `gmail-refresh-token` | 11-c で取得した refresh token | 🔒 ID は変更できない |
| `gmail-oauth-client-secret` | 11-b のクライアント シークレット | 🔒 |
| `contact-ip-hash-key` | IP アドレスをハッシュにするための鍵 (ランダムな文字列) | 🔒 |

- レプリケーションは **automatic** にします (🔒 作成後に変更できません。料金は 1 ロケーション分として計算されます)。
- クライアント ID は秘密情報ではないため、secret にせず環境変数で渡します。
- 無料枠は、有効な secret バージョン 6 個、アクセス 1 万回/月です (請求先アカウント単位)。アプリは、インスタンスごとに最初の問い合わせのときだけ 3 つの secret を読み、メモリに保持します。([pricing](https://cloud.google.com/secret-manager/pricing))
- 無効にしただけのバージョンも「有効なバージョン」として数えられます。不要になった古いバージョンは `gcloud secrets versions destroy` で破棄してください。

```powershell
# クライアント シークレット: Console でコピーしてから実行する (画面には表示されない)
$plain = (Get-Clipboard | Out-String).Trim()
$plain.Length; $plain.StartsWith("GOCSPX-")    # 35 前後と True になることを確認する
$plain | gcloud secrets create gmail-oauth-client-secret --project=$P --replication-policy=automatic --data-file=-
Remove-Variable plain
Set-Clipboard -Value " "                        # クリップボードを上書きしておく

# IP ハッシュ用の鍵 (32 バイトの乱数を 16 進数にしたもの)
python -c "import secrets; print(secrets.token_hex(32))" |
  gcloud secrets create contact-ip-hash-key --project=$P --replication-policy=automatic --data-file=-

gcloud secrets list --project=$P
```

- パイプで渡すと末尾に改行が付くことがありますが、アプリは前後の空白を取り除いて使います。
- `Read-Host -AsSecureString` の入力欄では、Ctrl+V で貼り付けられず制御文字が 1 文字だけ入ることがあります。上のようにクリップボードから直接渡すと確実です。Windows の「クリップボードの履歴」(Win+V) を使っている場合は、履歴からも削除してください。
- 値を間違えて登録した場合は、`gcloud secrets versions add <SECRET_ID> --data-file=-` で正しい値を追加し、古いバージョンを `gcloud secrets versions destroy <VERSION> --secret=<SECRET_ID>` で破棄します。アプリは secret をインスタンスのメモリに保持するので、その後に deploy し直して新しいインスタンスで読み込ませます。
- Console では「セキュリティ > Secret Manager > シークレットを作成」で作成します。

### 11-e. 実行 SA に権限を付与する (プロジェクトのオーナーが実行)

```powershell
gcloud projects add-iam-policy-binding $P `
  --member="serviceAccount:$RUNTIME" --role="roles/datastore.user" --condition=None

foreach ($s in "gmail-refresh-token", "gmail-oauth-client-secret", "contact-ip-hash-key") {
  gcloud secrets add-iam-policy-binding $s --project=$P `
    --member="serviceAccount:$RUNTIME" --role="roles/secretmanager.secretAccessor"
}
```

- Secret アクセサーは、プロジェクト全体ではなく **secret ごと**に付与します。
- Firestore のセキュリティルール (すべて拒否) は、サーバーからのアクセス (IAM で制御) には適用されません。ルールは変更しません。
- deployer に追加の権限は不要です。secret を Cloud Run の `--set-secrets` で渡すのではなく、アプリが実行時に Secret Manager から読むためです (`--set-secrets` の設定には Cloud Run 管理者のロールが必要と記載されています。[secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets))。

### 11-f. 環境変数

| 環境変数 | 値 | 備考 |
| --- | --- | --- |
| `CONTACT_NOTIFY_TO` | 通知を受け取るメールアドレス | 応答には含めない |
| `GMAIL_OAUTH_CLIENT_ID` | 11-b のクライアント ID | |
| `GMAIL_OAUTH_CLIENT_SECRET_SECRET_VERSION` | `projects/<PROJECT_ID>/secrets/gmail-oauth-client-secret/versions/latest` | |
| `GMAIL_REFRESH_TOKEN_SECRET_VERSION` | `projects/<PROJECT_ID>/secrets/gmail-refresh-token/versions/latest` | |
| `CONTACT_IP_HASH_KEY_SECRET_VERSION` | `projects/<PROJECT_ID>/secrets/contact-ip-hash-key/versions/latest` | |
| `CONTACT_RATE_LIMIT_IP_PER_HOUR` / `CONTACT_RATE_LIMIT_IP_PER_DAY` / `CONTACT_RATE_LIMIT_SITE_PER_DAY` | 省略可 (既定 3 / 5 / 20) | |

- `latest` を指定しているので、secret に新しいバージョンを追加すると、**新しく起動したインスタンス**から使われます (起動中のインスタンスは古い値を保持します)。
- secret の値を環境変数に直接入れることもできます (`GMAIL_REFRESH_TOKEN` など。ローカル開発用)。ただし、Cloud Run の環境変数の値はサービスを閲覧できる人に見えるため、Cloud Run では Secret Manager を使ってください。
- Cloud Run 上 (`K_SERVICE` がある場合) では、`X-Forwarded-For` の**最後の**値をクライアントの IP アドレスとして使います。クライアントが送った値は前に残り、最後の値は Cloud Run が付けるためです。

```powershell
$NOTIFY_TO = "<NOTIFY_TO_EMAIL>"
$CLIENT_ID = "<CLIENT_ID>"
```

この 2 つを設定してから、8-b の deploy コマンドに `--update-env-vars` を付けて実行します。

### 11-g. 確認

```powershell
$URL = "https://portfolio-<PROJECT_NUMBER>.$REGION.run.app"
curl.exe -i -X POST "$URL/api/contact" -H "Content-Type: application/json" `
  -d '{\"name\":\"Test\",\"email\":\"test@example.com\",\"message\":\"Hello\"}'
# HTTP/1.1 202 Accepted ... {"status":"accepted"}
```

- 通知先にメールが届き、Firestore の `contacts` にドキュメントができていることを確認します。
- 同じ IP アドレスから 1 時間に 4 回目を送ると、`429` (`Retry-After` 付き) になります。
- `503` の場合は、Cloud Logging で `contact_failed` を確認してください (設定や権限の不足など)。設定の読み込みに失敗した後の 60 秒間は、再試行せずに `503` を返し、`contact_unavailable` を記録します。`contact_notification_failed` は、保存はできたが通知に失敗したことを示します。

## 12. コスト防御と緊急停止

**どの設定も、単独では料金の上限を保証しません。** 複数の仕組みを組み合わせます。
アプリ側の制限 (rate limit、body サイズの上限など) を含めた全体は、[cost-defense.md](cost-defense.md) にまとめています。

| 仕組み | 守るもの | 限界 |
| --- | --- | --- |
| max instances = 1 | Cloud Run の CPU とメモリの費用 | 一時的に超えることがある。リクエスト料金と外向き通信料は抑えられない |
| Spend cap (Cloud Run) | Cloud Run の費用全体を自動で一時停止 | 即時ではない。対象は1プロジェクト × 1サービス |
| 通知のみの Budget | 請求先アカウント全体の監視 | 止める機能はない。通知に数時間の遅延がある |
| 緊急停止 (下記) | 公開アクセスの遮断 | 手動での操作が必要 |

**参考となる最悪ケース:**
- 1 vCPU / 512 MiB のインスタンスが1か月間処理し続けると、CPU 約 $58 + メモリ約 $2 になります (無料枠を差し引いた後、us-central1 の料金。2026-10 時点)。
- これにリクエスト料金と外向き通信料が加わります。
- 普段のアクセスなら無料枠 (CPU 180,000 vCPU秒 = 処理中の状態で約50時間/月) に収まりますが、大量アクセスや実装ミス (例: frontend が API を繰り返し呼び続ける) があると、この最悪ケースに近づきます。

**緊急停止:** 公開アクセスを止めます。IAM で拒否されたリクエストは課金されません。([run/pricing](https://cloud.google.com/run/pricing))

```powershell
gcloud run services update portfolio --project=$P --region=$REGION --invoker-iam-check
```

元に戻すときは、8-c を再度実行します。

予算超過時に課金そのものを自動で外す方法もあります ([disable-billing-with-notifications](https://docs.cloud.google.com/billing/docs/how-to/disable-billing-with-notifications))。
ただし、リソースが削除され得ることと、通知の遅延で上限も保証されないことから、このテンプレートでは採用していません。

### quota について

quota で費用の上限をかけられるかを確認した結果 (2026-10):

- **Cloud Run:** リージョン単位の quota (インスタンス数など) は、Console の「IAM と管理 > 割り当てとシステム上限」で「調整不可」と表示されました。また、「Instances per region」は Cloud Run Instances リソース専用で、Services は対象外です。そのため、サービスの上限は max instances で設定します。([run/quotas](https://docs.cloud.google.com/run/quotas))
- **Firestore:** 読み書きの日次上限を設定する quota は文書化されていません。([firestore/quotas](https://docs.cloud.google.com/firestore/quotas))
- **API 全般:** 課金対象の API には日次の上限を設定できるものがあります。ただし、それは個々の API の量の制限で、支出全体の制限ではありません。([capping-api-usage](https://docs.cloud.google.com/apis/docs/capping-api-usage))

## 13. 注意事項

- 問い合わせの内容はログに出力しません。ログに出るのは問い合わせ ID と、rate limit・失敗のイベント名だけです。
- Gmail API は、quota を超えた分に課金することが 2026 年後半に予定されています (少なくとも 90 日前に告知)。問い合わせ API はサイト全体の上限 (既定 20 件/日) で送信数を抑えています。([quota](https://developers.google.com/workspace/gmail/api/reference/quota))
- Docker Desktop で push するときは `--provenance=false --sbom=false` を付けてください (8-a を参照)。
- 組織に属するプロジェクトでは、組織ポリシーが継承されます。`allUsers` への付与が禁止されている場合でも、`--no-invoker-iam-check` で公開できます。

## 公式ドキュメント

- Free Tier: https://docs.cloud.google.com/free/docs/free-cloud-features
- Cloud Run の料金: https://cloud.google.com/run/pricing
- Cloud Run への deploy: https://docs.cloud.google.com/run/docs/deploying
- Cloud Run の IAM ロール: https://docs.cloud.google.com/run/docs/reference/iam/roles
- Service Account の impersonation: https://docs.cloud.google.com/docs/authentication/use-service-account-impersonation
- Budget: https://docs.cloud.google.com/billing/docs/how-to/budgets
- Spend cap: https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps
- Firestore のロケーション: https://docs.cloud.google.com/firestore/docs/locations
- Artifact Registry のクリーンアップポリシー: https://docs.cloud.google.com/artifact-registry/docs/repositories/cleanup-policy

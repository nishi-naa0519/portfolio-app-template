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
   ├─ Firestore          (default) (Native, <REGION>)   … Issue #4 以降で使用
   ├─ Secret Manager                                     … Issue #4 以降で使用
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
| `secretmanager` | 秘密情報の保存 (Issue #4 以降) |
| `gmail` | 問い合わせ通知 (Issue #4 以降)。有効化のみ |
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
| `portfolio-runtime` | (なし) | — | 現時点のアプリは GCP API を呼ばない。Issue #4 で Firestore と Secret Manager に必要な権限だけを追加する |
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

```powershell
$TAG = git rev-parse --short HEAD
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
| Concurrency | 20 | max = 1 なので、値はコストに影響しない。512 MiB の1台を過負荷から守るため、既定の 80 より控えめにした | 🔁 |
| Timeout | 15 秒 | 既定は 300 秒。異常に長いリクエストで課金時間が延びるのを防ぐ | 🔁 |
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

Issue #4 で、問い合わせの保存に使います。ここでは作成までを行います。

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

## 11. Secret Manager

API を有効にするだけで、現時点では secret を作りません (Issue #4 以降で作成します)。
`gcloud secrets list --project=$P` がエラーなく実行できれば、利用できる状態です。

- 無料枠: 有効な secret バージョン 6個、アクセス 1万回/月 (請求先アカウント単位)。([pricing](https://docs.cloud.google.com/secret-manager/pricing))
- 実行 SA には、Secret Accessor (`roles/secretmanager.secretAccessor`) を**必要な secret に対してだけ**付与します。

## 12. コスト防御と緊急停止

**どの設定も、単独では料金の上限を保証しません。** 複数の仕組みを組み合わせます。

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

- **`/api/contact` は、現時点では受信した内容をそのままログに出力します。** Issue #4 で保存と通知を実装するまでは、公開環境に実際の問い合わせ内容を送らないでください。
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

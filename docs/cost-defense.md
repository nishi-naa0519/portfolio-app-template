# コスト防御

予期しない大量アクセス、bot、実装ミス、設定ミスによって、GCP の無料枠を大幅に超える費用が発生するリスクを小さくするための設計です。
このサイトでは、**可用性よりもコストの制御を優先**します。上限に達したときは、問い合わせを受け付けない・ページが一時的に表示されない状態になることを許容します。

> [!IMPORTANT]
> **Budget Alert や max instances など、単独の設定だけで料金の完全なハードキャップを保証するものではありません。**
> 料金の上限は、以下の複数の防御策を組み合わせて抑えます。

> [!NOTE]
> 料金・無料枠・quota は変わることがあります。本書の値は 2026-10 時点の公式ドキュメントで確認したものです。
> 設定の手順は [deployment.md](deployment.md) にあります。本書は「何を守るために、どの制限を設定しているか」をまとめたものです。

## 1. 費用が発生する場所

| サービス | 主な課金対象 | 無料枠 (2026-10) | アクセス量に比例して増えるもの |
| --- | --- | --- | --- |
| Cloud Run | CPU・メモリ (インスタンスがリクエストを処理している時間)、リクエスト数、外向き通信 | 180,000 vCPU 秒・360,000 GiB 秒・200 万リクエスト/月。外向き通信は北米向け 1 GiB/月のみ | **リクエスト料金 ($0.40/100 万件) と外向き通信料**。CPU・メモリは max instances で上限がある |
| Firestore | 読み取り・書き込み・削除の件数、保存容量 | 読み取り 5 万/日、書き込み 2 万/日、削除 2 万/日、保存 1 GiB。**TTL による削除は無料枠の対象外** | 問い合わせ API の呼び出し回数 (下記の対策で抑える) |
| Secret Manager | 有効な secret バージョン数、アクセス回数 | 6 バージョン、1 万アクセス/月 | インスタンスの起動回数 |
| Gmail API | (現在は quota の範囲内で無料) | quota を超えた分への課金が 2026 年後半に予定 (90 日以上前に告知) | 受理した問い合わせ数 |
| Cloud Logging | ログの取り込み量 | 50 GiB/プロジェクト/月 (30 日までの保存を含む) | リクエスト数 (Cloud Run のリクエストログ) |
| Artifact Registry | 保存容量 | 0.5 GB/月 | deploy の回数 (クリーンアップポリシーで抑える) |

参考: [Cloud Run](https://cloud.google.com/run/pricing)、[Firestore](https://cloud.google.com/firestore/pricing)、[Secret Manager](https://cloud.google.com/secret-manager/pricing)、[Gmail API quota](https://developers.google.com/workspace/gmail/api/reference/quota)、[Cloud Logging](https://cloud.google.com/stackdriver/pricing)、[Artifact Registry](https://docs.cloud.google.com/artifact-registry/pricing)

## 2. 防御の一覧

外側 (GCP) から内側 (アプリ) の順に並べています。

| 層 | 制限 | 値 | 守るもの | 限界 |
| --- | --- | --- | --- | --- |
| GCP | 通知のみの Budget | 請求先アカウント全体、実績 10%・50%・90%・100%、予測 100% | 想定外の費用に早く気づく | 止める機能はない。通知まで数時間の遅延がある |
| GCP | Spend cap budget | プロジェクト × Cloud Run | Cloud Run の新しい使用を自動で一時停止 | 即時ではない。Cloud Run 以外は対象外 |
| GCP | 緊急停止 (`--invoker-iam-check`) | 手動 | すべての公開アクセスを遮断 (IAM で拒否されたリクエストは課金されない) | 人が気づいて操作する必要がある |
| Cloud Run | max instances | 1 | CPU・メモリの費用 | 一時的に超えることがある。リクエスト料金と外向き通信料は抑えられない |
| Cloud Run | min instances | 0 | 待機中の費用 | コールドスタートが発生する |
| Cloud Run | 課金方式 | リクエストベース | 処理していない時間の費用 | |
| Cloud Run | 起動時 CPU ブースト | 無効 | コールドスタートごとの追加の CPU 費用 | 起動が少し遅くなる |
| Cloud Run | timeout | 15 秒 | 1 リクエストが課金時間を延ばし続けること (3. を参照) | |
| Cloud Run | concurrency | 20 | 1 台のインスタンスの過負荷 (3. を参照) | |
| アプリ | リクエスト body の上限 | 32 KiB (超えると `413`) | 巨大な payload の受信・解析にかかる CPU とメモリ | Cloud Run 自体の上限は 32 MiB (HTTP/1) |
| アプリ | 入力値の検証 (Pydantic) | 名前 100・メール 254・本文 5000 文字 | Firestore の保存容量と通知メールの大きさ | |
| アプリ | honeypot | `website` に値があれば保存せず `202` | 単純な bot | 人間やフォームを解析する bot には効かない |
| アプリ | rate limit (IP) | 3 件/時、5 件/日 (IPv6 は /64 単位) | 1 つの送信元からの連投 | IP を変える攻撃には効かない |
| アプリ | rate limit (サイト全体) | 20 件/日 | **Firestore の書き込み数と Gmail の送信数の上限** | 上限に達すると、その日は正当な問い合わせも受け付けない |
| アプリ | 上限に達したカウンタの記憶 | インスタンスごと、最大 1000 件 | 上限を超えたリクエストによる Firestore の読み取り | インスタンスが入れ替わると、最初の 1 回は読み取りが発生する |
| アプリ | GCP ライブラリと secret の遅延読み込み | 最初の問い合わせのとき | ページ閲覧で Firestore・Secret Manager・Gmail にアクセスしないこと | |
| アプリ | 構築失敗後の再試行の間隔 | 60 秒 | 設定ミスのときに、リクエストのたびに Secret Manager へアクセスすること | 設定を直しても、最大 60 秒は `503` が続く |
| アプリ | 外部呼び出しの timeout | 5 秒 (Firestore の読み取り・Secret Manager・Gmail) | 外部サービスの遅延で課金時間が延びること | Firestore トランザクションの begin/commit には指定できない (3. を参照) |
| アプリ | uvicorn の access log | 無効 (Dockerfile) | Cloud Logging の取り込み量 | Cloud Run のリクエストログは残る |
| アプリ | API ドキュメント (`/docs`・`/redoc`・`/openapi.json`) | Cloud Run 上では無効 | 不要な公開エンドポイント | ローカルでは有効 |
| Firestore | インデックスの除外 | `contacts.message`、`contact_rate_limits.expire_at`・`count` | 保存容量、TTL フィールドのホットスポット | 手動で設定する (deployment.md の 10.) |
| Firestore | TTL | `contact_rate_limits.expire_at` | rate limit のデータが溜まり続けること | TTL の削除は無料枠の対象外 (件数は少ない) |
| Artifact Registry | クリーンアップポリシー | 最新 3 つを保持 | 保存容量 | 反映に最大 1 日 |

## 3. Cloud Run の設定のレビュー

2026-10-28 に、deploy 済みのサービス (`gcloud run services describe`) が次の値になっていることを確認しました。

| 設定 | 値 | 理由 |
| --- | --- | --- |
| min instances | 0 | アクセスがないときは費用がかからない |
| max instances | 1 (サービス単位とリビジョン単位の両方) | CPU とメモリの費用の上限を「1 台が 1 か月処理し続けた場合」に抑える |
| CPU / memory | 1 vCPU / 512 MiB | 1 未満の CPU では concurrency が 1 に制限され、静的ファイルの配信まで直列になる。メモリは既定値で、このアプリには十分 |
| 課金方式 | リクエストベース | 待機中の課金を避ける |
| 起動時 CPU ブースト | 無効 | ブースト中の CPU も課金されるため |

### concurrency = 20 の理由

- **max instances = 1 なので、concurrency の値は CPU・メモリの費用の上限に影響しません。** リクエストベースの課金では、1 つ以上のリクエストを処理している間だけ、インスタンス 1 台分が課金されます。同時に処理するリクエストが 1 件でも 20 件でも、課金額は同じです。
- **1 にしない理由:** 1 回のページ表示で、HTML・JS・CSS・favicon・`/api/health` など複数のリクエストが同時に発生します。concurrency = 1 で max = 1 だと、これらが直列になり、待ちきれないリクエストは失敗します。
- **既定の 80 より小さくする理由:** インスタンスは 512 MiB の 1 台だけです。問い合わせ API は同期処理 (スレッドプール) で外部 API を呼ぶため、同時に処理する数を抑えて、メモリ不足やすべてのリクエストの遅延を防ぎます。
- 処理できる数を超えたリクエストは、しばらく待機した後、コンテナに届かずに Cloud Run がエラーを返します。公式の料金ページでは、リクエストは「コンテナに届いたとき」に課金されると記載されています。

### timeout = 15 秒の理由

- 既定は 300 秒です。外部 API が応答しない場合や、クライアントが body をゆっくり送り続ける場合に、1 件のリクエストでインスタンスが最大 5 分間課金され続けるのを防ぎます。
- 問い合わせ API の通常の処理 (Firestore のトランザクションと Gmail の送信) は数秒以内です。各外部呼び出しの timeout は 5 秒です。
- Firestore トランザクションの begin/commit には、ライブラリの仕様上 timeout を指定できません (既定は 60 秒)。15 秒の Cloud Run の timeout が最終的な上限になります。
- 15 秒を超えたリクエストは、クライアントには `504` が返ります。問い合わせの保存が完了しているかは不定です。

## 4. Firestore

### 通常のページ閲覧ではアクセスしない

- 静的コンテンツ (ページ、JS、CSS) は Docker イメージに含まれ、FastAPI から配信します。Firestore は使いません。
- Firestore のクライアント ライブラリは、最初の問い合わせのときに読み込みます (テスト: `test_google_cloud_libraries_are_not_loaded_at_startup`)。

### 1 件のリクエストあたりの操作数

| リクエスト | 読み取り | 書き込み | 備考 |
| --- | --- | --- | --- |
| 受理された問い合わせ | 3 | 4 | 1 つのトランザクション。競合したときは最大 3 回まで再試行 |
| rate limit を超えた (このインスタンスで初めて) | 3 | 0 | 超えたカウンタをメモリに記憶する |
| rate limit を超えた (記憶済みのカウンタ) | 0 | 0 | 同じ時間枠の間は Firestore を読まない |
| honeypot、入力値の不正 (`422`)、body が大きすぎる (`413`) | 0 | 0 | |

サイト全体の上限 (既定 20 件/日) に達すると、その日の残りは、どの IP からのリクエストも Firestore を読まずに `429` になります。
そのため、1 日の読み取りは「受理した問い合わせ × 3 + 上限に達したカウンタの数 × 3 + インスタンスの起動回数 × 3」程度に収まります。

> [!NOTE]
> Firestore Console から rate limit のドキュメントを手動で削除しても、記憶済みのカウンタはインスタンスが入れ替わるまで残ります。
> 上限を変える (`CONTACT_RATE_LIMIT_*`) には deploy し直すので、そのときは新しいインスタンスで記憶もリセットされます。

### インデックス

Firestore は既定で、すべてのフィールドに単一フィールドのインデックスを作ります。インデックスは保存容量に含まれます。
アプリはドキュメント ID で読み書きするだけで、クエリを使いません。そこで、次のフィールドをインデックスから除外します (手順は deployment.md の 10.)。

| コレクション | フィールド | 理由 |
| --- | --- | --- |
| `contacts` | `message` | 最大 5000 文字で、検索に使わない |
| `contact_rate_limits` | `expire_at` | TTL のフィールド。タイムスタンプのインデックスはホットスポットの原因になる ([ttl](https://docs.cloud.google.com/firestore/docs/ttl)) |
| `contact_rate_limits` | `count` | 検索に使わない |

`contacts` の `created_at`・`status` などは、Console で問い合わせを並べ替え・絞り込みできるように、インデックスを残します。

## 5. お問い合わせ API の多層の制限

リクエストは、次の順に検査されます。前の段階で拒否されたリクエストは、後の段階 (費用がかかる処理) に進みません。

```text
1. body のサイズ (32 KiB)      → 413   外部アクセスなし
2. 入力値の検証 (Pydantic)      → 422   外部アクセスなし
3. honeypot                     → 202   外部アクセスなし (保存も通知もしない)
4. 記憶済みのカウンタ           → 429   外部アクセスなし
5. rate limit (Firestore)       → 429   読み取り 3
   IP 3 件/時・5 件/日、サイト全体 20 件/日
6. 保存 (同じトランザクション)  → 202   書き込み 4
7. Gmail で通知                  →       送信 1 (失敗しても再試行しない)
```

## 6. Gmail

- 通知メールは、**保存に成功した問い合わせ 1 件につき 1 通だけ**送ります。送信に失敗しても再試行しません (問い合わせは Firestore に保存済みです)。
- そのため、送信数は「受理した問い合わせの数」以下になり、サイト全体の上限 (既定 20 件/日) を超えません。
- `messages.send` は 1 回あたり 100 quota ユニットです。プロジェクトの日次の課金しきい値 (8,000 万ユニット/日) や、ユーザーごとの上限 (6,000 ユニット/分) に対して、20 通/日は十分に小さい値です。
- Gmail API の quota を下げられるかは、公式ドキュメントに記載がありません。アプリ側の上限のほうが厳しいため、quota は変更しません。
- quota を超えた分への課金は「2026 年後半」に予定されています。告知 (90 日以上前) が出たら、内容を確認してください。

## 7. GCP の quota と Budget

- **Budget (通知のみ) と Spend cap** は、deployment.md の 2. と 5. の手順で設定できます。通知のしきい値や金額は、後から変更できます。
- **Cloud Run** のリージョン単位の quota は「調整不可」で、Services は「Instances per region」の対象外でした。サービスの上限は max instances で設定します。
- **Firestore** には、読み書きを日次で制限する quota がありません。アプリ側の rate limit で抑えます。
- **API の quota で上限をかける機能** ([capping-api-usage](https://docs.cloud.google.com/apis/docs/capping-api-usage)) は、API ごとのリクエスト量の制限です。費用全体の上限ではなく、公式にも Budget と組み合わせるよう記載されています。このテンプレートでは使いません。
- **Cloud Logging:** Cloud Run は、リクエストごとにリクエストログを自動で記録します。アプリのログは、問い合わせのイベント (受理・rate limit・失敗) だけです。uvicorn の access log は、リクエストログと重複するため無効にしています。取り込み量が増える場合は、Cloud Logging の除外フィルタで減らせます ([run/logging](https://docs.cloud.google.com/run/docs/logging))。

## 8. 最悪ケースの目安

上の対策を入れても、費用が増え得るのは主に次の 3 つです。いずれも Spend cap (Cloud Run) と Budget の通知で検知・停止します。

| 費用 | 目安 (無料枠を差し引いた後、us-central1、2026-10) |
| --- | --- |
| CPU・メモリ | 1 vCPU / 512 MiB の 1 台が 1 か月処理し続けると、CPU 約 $58 + メモリ約 $2 |
| リクエスト料金 | 毎秒 100 リクエストが 1 か月続くと、約 2.6 億件で約 $100 |
| 外向き通信 | ページの大きさ × 表示回数。北米向け 1 GiB/月を除き無料枠はない |

- リクエスト料金と外向き通信料は、max instances では抑えられません。大量のアクセスに対しては、**Spend cap による自動停止と、緊急停止 (deployment.md の 12.)** が最後の防御です。
- Spend cap が、割引 (無料枠) を差し引く前と後のどちらの金額で判定するのか、外向き通信料が「Cloud Run」の費用に含まれるのかは、公式ドキュメントに明記されていません (Issue #3 の時点)。
- frontend の実装ミス (API を繰り返し呼び続けるなど) は、閲覧者のブラウザからの大量のリクエストとして、この最悪ケースにつながります。frontend を変更するときは、ページ表示 1 回あたりの API 呼び出しが増えていないかを確認してください。

## 9. 定期的に確認すること

- 「お支払い > レポート」で、サービスごとの費用 (特に Cloud Run・Firestore・Cloud Logging)
- Cloud Logging で `contact_rate_limited` (rate limit に達した回数) と `contact_failed` / `contact_unavailable` (設定や障害)
- Artifact Registry のイメージの数と容量
- Gmail API の課金に関する告知

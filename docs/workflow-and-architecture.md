# YOLO Detection プロダクト 仕組みとワークフロー

このドキュメントでは、YOLOv8 を用いた人物滞留ヒートマップ PoC の**動く仕組み**を、図解（Mermaid）を交えて説明します。

---

## 1. プロダクト概要

ブラウザのカメラ映像から **人物（person）** を検出し、足元位置を**床面へ射影**して、部屋平面の**滞留ヒートマップ**を生成するアプリケーションです。

- **バックエンド**: FastAPI（Python）+ YOLOv8（Ultralytics）
- **フロントエンド**: Svelte 5 + TypeScript + Vite
- **計測**: セッション単位で開始・停止し、指定時間（例: 60分）の間、定期的にフレームを送信してヒートマップを蓄積

---

## 2. システムアーキテクチャ

```mermaid
flowchart TB
    subgraph Frontend["フロントエンド (Svelte)"]
        App["App.svelte"]
        ApiClient["api-client.ts"]
        Camera["camera.ts"]
        HeatmapStore["heatmapStore.ts"]
        HeatmapCanvas["HeatmapCanvas.svelte"]
        App --> ApiClient
        App --> Camera
        App --> HeatmapStore
        App --> HeatmapCanvas
        HeatmapStore --> ApiClient
    end

    subgraph Backend["バックエンド (FastAPI)"]
        API["api.py\n(ルート定義)"]
        Detection["detection.py\n(YOLO 推論)"]
        Structure["structure.py\n(構造推定)"]
        Heatmap["heatmap.py\n(セッション・射影・永続化)"]
        API --> Detection
        API --> Structure
        API --> Heatmap
    end

    subgraph Storage["永続化"]
        Artifacts["artifacts/heatmaps/\n(PNG + JSON)"]
        LocalStorage["localStorage\n(履歴)"]
    end

    ApiClient -->|"HTTP"| API
    Heatmap --> Artifacts
    App --> LocalStorage
```

**依存の向き（責務の分離）:**

- `main.py` → FastAPI の生成・静的ファイルマウント・ルート登録のみ
- `api.py` → HTTP の入出力と、detection / structure / heatmap の**呼び出し**
- 推論・構造推定・セッション管理は API 層に引きずられない形でモジュール化

---

## 3. エンドツーエンド ユーザーワークフロー

利用者が「カメラ起動」から「計測完了・履歴確認」まで行う一連の流れです。

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant App as App.svelte
    participant Camera as camera.ts
    participant API as api-client
    participant Backend as FastAPI
    participant Store as heatmapStore

    User->>App: カメラ起動
    App->>Camera: getUserMedia
    Camera-->>App: 映像ストリーム

    User->>App: 部屋の構造推定
    App->>Camera: 1フレーム取得
    App->>API: estimateStructure(blob)
    API->>Backend: POST /estimate-structure
    Backend-->>API: 投影パラメータ
    API-->>App: 投影パラメータ
    App->>App: フォームに反映・プレビュー表示

    opt 家具推定（任意）
        User->>App: 家具推定
        App->>API: estimateFurniture(blob, 投影)
        API->>Backend: POST /estimate-furniture
        Backend-->>API: furniture_items
        App->>App: 構造プレビューに家具描画
    end

    User->>App: 計測開始
    App->>API: startSession(設定)
    API->>Backend: POST /session/start
    Backend-->>API: session_id, status
    App->>Store: startPolling(session_id)
    App->>App: フレーム送信ループ開始

    loop 計測中（intervalMs ごと）
        App->>Camera: フレーム取得
        App->>API: detectFrame(blob, session_id)
        API->>Backend: POST /detect
        Backend->>Backend: YOLO 推論 → 足元射影 → グリッド加算
        Backend-->>API: detections, session status
        API-->>App: 検出結果・セッション状態
        App->>App: オーバーレイに bbox 描画
    end

    loop ヒートマップ更新（heatmapRefreshMs ごと）
        Store->>API: fetchHeatmapData(session_id)
        API->>Backend: GET /session/{id}/heatmap-data
        Backend-->>API: grid, metadata
        API-->>Store: HeatmapData
        Store->>App: heatmapData 更新 → HeatmapCanvas 再描画
    end

    User->>App: 計測停止（または時間切れ）
    App->>API: stopSession(session_id)
    API->>Backend: POST /session/{id}/stop
    Backend->>Backend: セッション停止・PNG/JSON 保存
    Backend-->>API: 最終 status
    App->>Store: stopPolling()
    App->>App: 履歴に追加・localStorage 保存
    App->>User: 計測完了・ヒートマップ表示
```

---

## 4. セッションライフサイクル

計測の「開始」から「停止・永続化」までの状態遷移です。

```mermaid
stateDiagram-v2
    [*] --> なし: 起動時

    なし --> 作成済: POST /session/start

    作成済 --> 計測中: 最初の POST /detect（session_id 付き）

    計測中 --> 計測中: POST /detect（フレーム追加・グリッド加算）
    計測中 --> 停止済: POST /session/{id}/stop または時間切れ

    停止済 --> 永続化済: stop_and_persist() で PNG/JSON 保存

    永続化済 --> [*]: 結果取得・履歴表示後
```

**状態の意味:**

| 状態       | 説明 |
|------------|------|
| なし       | セッション未作成 |
| 作成済     | セッション ID が発行されたが、まだ `/detect` でフレームが来ていない |
| 計測中     | `is_active === true`。`/detect` でフレームを受け取り、ヒートマップグリッドを更新 |
| 停止済     | `ended_at` が設定された。残り時間切れまたは明示的停止 |
| 永続化済   | `artifacts/heatmaps/` に PNG と JSON が保存された |

**永続化のタイミング:**  
`POST /session/{id}/stop` または、`GET /session/{id}/status` で `is_active === false` と判明したときに `stop_and_persist()` が呼ばれ、その時点で PNG/JSON が書き出されます。

---

## 5. 床面射影モデル（投影の仕組み）

カメラ画像上の「足元」を、部屋を上から見た**平面座標（0〜1 の長方形）**に写すためのモデルです。

### 5.1 パラメータの意味

- **floor_top_y_ratio**: 画像の中で「床が始まる」とみなす Y 位置（0〜1）。これより上は床として扱わない。
- **floor_top_width_ratio**: 奥側（画面上部）の床の**見かけの幅**（画像幅に対する比）。
- **floor_bottom_width_ratio**: 手前側（画面下部）の床の見かけの幅。通常 1.0（画面幅いっぱい）。

画像上では奥に行くほど幅が狭く見えるため、**台形**の床領域を、**長方形の部屋平面**に射影します。

```mermaid
flowchart LR
    subgraph Image["カメラ画像"]
        A["画面上部（奥）\n幅 = floor_top_width_ratio"]
        B["画面下部（手前）\n幅 = floor_bottom_width_ratio"]
        A --- B
    end

    subgraph Room["部屋平面（上から見た図）"]
        C["奥 (y=0)"]
        D["手前 (y=1)"]
        C === D
    end

    Image -->|"project_to_plane()\nproject_detection_to_plane()"| Room
```

### 5.2 射影の流れ（人物の足元）

```mermaid
flowchart TD
    subgraph Input["入力"]
        Frame["フレーム画像"]
        Bbox["人物 bbox (x1,y1,x2,y2)"]
    end

    subgraph Calc["計算"]
        Foot["足元 = (bbox 中央x, bbox 下端y)"]
        YRatio["y_ratio = foot_y / frame_height"]
        Depth["depth_ratio = (y_ratio - floor_top_y) / (1 - floor_top_y)"]
        VisibleWidth["visible_width = top_width + (bottom - top) * depth"]
        PlaneX["plane_x = ((x_ratio - 0.5) / visible_width) + 0.5"]
        PlaneY["plane_y = depth_ratio"]
    end

    subgraph Output["出力"]
        Grid["グリッド座標 (grid_x, grid_y)\nheatmap[grid_y, grid_x] += 1"]
    end

    Frame --> Foot
    Bbox --> Foot
    Foot --> YRatio
    YRatio --> Depth
    Depth --> VisibleWidth
    Depth --> PlaneY
    VisibleWidth --> PlaneX
    PlaneX --> Grid
    PlaneY --> Grid
```

- 足元が `floor_top_y_ratio` より上にある場合は射影せず無視します。
- 平面座標 (plane_x, plane_y) をグリッド番号に変換し、`HeatmapSession.heatmap` の該当セルを加算します。

---

## 6. バックエンド リクエストフロー

主要 API ごとに、リクエストがどのモジュールを経由するかを示します。

```mermaid
flowchart TB
    subgraph Routes["api.py"]
        R1["POST /estimate-structure"]
        R2["POST /estimate-furniture"]
        R3["POST /session/start"]
        R4["POST /session/:id/stop"]
        R5["GET /session/:id/status"]
        R6["GET /session/:id/heatmap.png"]
        R7["GET /session/:id/heatmap-data"]
        R8["POST /detect"]
    end

    subgraph Logic["業務ロジック"]
        Structure["structure.py\nestimate_projection_from_frame"]
        Detection["detection.py\ndetect_scene"]
        HeatmapModule["heatmap.py"]
        SessionStore["SessionStore"]
        Projection["project_furniture_detections\nproject_detection_to_plane"]
    end

    R1 --> Structure
    R2 --> Detection
    R2 --> Projection
    R3 --> SessionStore
    R4 --> SessionStore
    R5 --> SessionStore
    R6 --> SessionStore
    R7 --> SessionStore
    R8 --> Detection
    R8 --> SessionStore
    R8 --> HeatmapModule
```

- **POST /detect**: 画像をデコード → `detector.detect_scene()` → `session.add_frame()`（足元射影・グリッド加算・家具マージ）→ セッション状態を返却。
- **POST /session/start**: `SessionStore.create()` で `HeatmapSession` を生成し、ID と status を返却。
- **POST /session/:id/stop**: `SessionStore.stop_and_persist()` で `session.stop()` と `persist_artifacts()` を実行。

---

## 7. フロントエンドのデータフロー

フロントエンド内で、セッション・ヒートマップ・API がどう連携するかを示します。

```mermaid
flowchart LR
    subgraph UI["UI レイヤー"]
        App["App.svelte"]
        HeatmapCanvas["HeatmapCanvas.svelte"]
        ColorBar["ColorBar.svelte"]
    end

    subgraph Data["データ・API"]
        ApiClient["api-client.ts"]
        HeatmapStore["heatmapStore.ts"]
        History["history.ts\nlocalStorage"]
    end

    App -->|"startSession, detectFrame,\nstopSession, estimate*"| ApiClient
    App -->|"startPolling / stopPolling"| HeatmapStore
    HeatmapStore -->|"fetchHeatmapData"| ApiClient
    App -->|"履歴の読み書き"| History

    HeatmapStore -->|"$heatmapData"| App
    App -->|"heatmapData"| HeatmapCanvas
    App -->|"色スケール"| ColorBar
```

- **計測中**: App が `detectFrame()` を一定間隔で呼び出し、同じ `session_id` で `HeatmapStore` が `fetchHeatmapData()` をポーリング。取得した `HeatmapData` が `HeatmapCanvas` に渡され、部屋外形・グリッド・家具が描画されます。

---

## 8. API 一覧（参照）

| メソッド | パス | 役割 |
|----------|------|------|
| GET | `/` | フロントエンド index.html |
| GET | `/health` | 稼働・モデル名確認 |
| POST | `/estimate-structure` | 1 フレームから床・投影パラメータを推定 |
| POST | `/estimate-furniture` | 1 フレーム + 投影から家具を部屋座標で取得 |
| POST | `/session/start` | セッション作成（時間・部屋サイズ・投影パラメータ） |
| POST | `/session/{id}/stop` | セッション停止と PNG/JSON 永続化 |
| GET | `/session/{id}/status` | 残り時間・検出数・家具など |
| GET | `/session/{id}/heatmap.png` | ヒートマップ画像（PNG） |
| GET | `/session/{id}/heatmap-data` | ヒートマップグリッド・メタデータ（JSON） |
| POST | `/detect` | 画像 + 任意で session_id。YOLO 推論とセッション更新 |

---

## 9. 関連ドキュメント

- [README.md](../README.md) … セットアップ・起動・機能概要
- [architecture.md](./architecture.md) … モジュール構成・責務・依存の向き

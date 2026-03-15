# YOLOv8 Person Occupancy Heatmap PoC

Ultralytics YOLOv8 を使い、スマホのブラウザカメラ映像から `person` のみを検出し、足元位置を床面へ推定投影して、部屋平面の長方形ヒートマップを作成する PoC です。

## セットアップ

```bash
make setup
```

## 起動

Svelte + TypeScript フロントエンドを配信するには、最初にビルドします。

```bash
make frontend-build
make run
```

- `make run` は FastAPI を `:8000` で起動し、`frontend/dist` のビルド済みフロントエンドを配信します。
- フロントエンドを単体開発する場合は別ターミナルで `make frontend-dev` を使います。
- `make frontend-dev` の開発サーバは通常 `http://127.0.0.1:5173` で起動し、API は `:8000` に proxy されます。
- PCでサーバを起動し、同じWi-Fiのスマホで `http://<PCのIP>:8000` を開きます。
- `カメラ起動` -> `部屋の構造推定` -> `計測開始` の順で進めます。
- `部屋の構造推定` は現在フレームから床開始位置や見かけ幅を推定し、投影パラメータへ自動反映します。
- 既定値は `60分`、送信間隔は `1000ms` です。
- `計測停止` または計測時間終了後に、部屋平面を長方形で表したヒートマップ画像を確認できます。
- 計測終了時にブラウザの `localStorage` へ履歴保存し、同時にプロジェクト配下 `artifacts/heatmaps/` に PNG と JSON を保存します。

## ヘルスチェック

```bash
curl http://127.0.0.1:8000/health
```

期待値:

```json
{"status":"ok","model":"yolov8n.pt"}
```

## PCのIP確認方法（macOS）

Wi-Fiが `en0` の場合:

```bash
ipconfig getifaddr en0
```

何も出ない場合（環境により `en1`）:

```bash
ipconfig getifaddr en1
```

表示されたIPを使ってスマホから `http://<表示IP>:8000` にアクセスします。

## 機能

- YOLOv8 の COCO クラスから `person` のみ検出
- 各人物 bbox の足元中心を簡易な床面投影で平面グリッドに変換
- セッション開始・停止・残り時間表示
- 1時間など長時間運転向けの逐次送信ループ
- 部屋平面の長方形 occupancy heatmap PNG を生成
- ブラウザの `localStorage` に個人用履歴を保持
- `artifacts/heatmaps/` にヒートマップ画像とメタデータを保存

## API

- `POST /session/start`
  - form: `duration_minutes`, `room_width_units`, `room_height_units`, `floor_top_y_ratio`, `floor_top_width_ratio`, `floor_bottom_width_ratio`
- `POST /estimate-structure`
  - multipart: `file`（カメラの現在フレーム）
- `POST /session/{session_id}/stop`
- `GET /session/{session_id}/status`
- `GET /session/{session_id}/heatmap.png`
- `POST /detect`
  - multipart: `file`, `session_id`（任意）

## ドキュメント

- **[docs/workflow-and-architecture.md](docs/workflow-and-architecture.md)** … プロダクトの動く仕組み・ワークフロー・セッション・床面射影を図解（Mermaid）で解説
- [docs/architecture.md](docs/architecture.md) … モジュール構成・責務・依存の向き

## フロントエンド構成

- `frontend/`: Svelte + TypeScript + Vite のソースコード
- `frontend/dist/`: Vite build の出力先
- FastAPI は `/` で `frontend/dist/index.html` を返し、`/assets` でビルド済み asset を配信します

## 保存先

- ブラウザ履歴: `localStorage` キー `personHeatmapHistory`
- サーバ保存先: `artifacts/heatmaps/heatmap_<timestamp>_<session_id>.png`
- サーバ保存メタデータ: `artifacts/heatmaps/heatmap_<timestamp>_<session_id>.json`

## 推定モデル

- 画像内の人物足元点を観測点として使います
- 画面下ほどカメラ手前、画面上ほど部屋の奥とみなします
- `floor_top_y_ratio` より上は床として扱いません
- 奥側の見かけ幅 `floor_top_width_ratio` と手前側の見かけ幅 `floor_bottom_width_ratio` を使って、台形の床領域を長方形平面へ射影します
- 正確な測量ではなく、定点観測向けの簡易 occupancy 推定です

## 注意

- HTTPS でない環境では、スマホブラウザのカメラ制約により動作しない場合があります。
- 初回推論時に `yolov8n.pt` が自動ダウンロードされます。
- 端末のスリープやブラウザ制約で長時間計測が止まることがあるため、スマホは充電し画面常時点灯を推奨します。
- ヒートマップは簡易な床面投影に基づく推定結果です。厳密な床面座標が必要なら、別途キャリブレーションや射影変換が必要です。

## トラブルシュート

`Cannot read properties of undefined (reading 'getUserMedia')` が出る場合:

- スマホから `http://<PCのIP>:8000` で開いていると、ブラウザ仕様でカメラAPIが無効になることがあります。
- `https://...` でアクセスするか、まずPCの `http://localhost:8000` で動作確認してください。
- iOS は Safari 推奨です（アプリ内ブラウザは制限されることがあります）。

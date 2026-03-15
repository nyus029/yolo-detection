# Minimal Architecture

## Goal

- `main.py` はアプリの起動配線だけにする
- 推論、構造推定、セッション管理を分けて責務を明確にする
- PoC の速さは維持しつつ、機能追加時の編集範囲を狭くする

## Current Issues

- HTTP 入出力と業務ロジックが `app/main.py` に集中している
- YOLO 推論の都合で API 層のテストがしにくい
- 構造推定ロジックの差し替え先がない
- 将来 `storage` や `calibration` を追加するとさらに混ざる

## Target Structure

```text
app/
  main.py          # FastAPI の生成と依存の配線
  api.py           # HTTP endpoint と request/response の責務
  detection.py     # YOLO person detection
  structure.py     # 単一フレームからの床構造推定
  heatmap.py       # セッション、射影、ヒートマップ永続化
static/
  index.html       # DOM 構造と最小限のスタイル
  app.js           # 画面状態の接着
  api-client.js    # FastAPI との通信
  camera.js        # カメラ起動と frame capture
  history.js       # localStorage と履歴描画
docs/
  architecture.md  # この設計メモ
```

## Dependency Direction

```text
static/index.html -> static/app.js
static/app.js -> static/api-client.js
static/app.js -> static/camera.js
static/app.js -> static/history.js
static/api-client.js -> FastAPI API
app/main.py -> app/api.py
app/api.py -> app/detection.py
app/api.py -> app/structure.py
app/api.py -> app/heatmap.py
app/detection.py -> ultralytics
app/structure.py -> cv2 / numpy
app/heatmap.py -> cv2 / numpy / filesystem
```

`api.py` から下は UI や FastAPI の事情に引きずられない構成を維持します。

## Module Responsibilities

### `app/main.py`

- `FastAPI` の生成
- static mount
- detector / session store の生成
- route 登録

### `app/api.py`

- endpoint 定義
- upload decode
- HTTP エラー変換
- session 更新フローの接続

### `app/detection.py`

- YOLO モデルロード
- person のみを抽出した detection payload 生成

### `app/structure.py`

- カメラ画像 1 枚から投影パラメータを推定
- 将来、手動キャリブレーションや射影変換に差し替える入口

### `app/heatmap.py`

- `ProjectionConfig`
- `HeatmapSession`
- `SessionStore`
- PNG / JSON の保存

## Next Step

- API schema が増えたら `pydantic` の request/response model を追加する
- 画面がさらに増えるなら `static/app.js` に残った表示更新も `ui.js` へ切り出す
- 精度改善に進むなら `structure.py` を「簡易推定」と「手動補正」に分ける

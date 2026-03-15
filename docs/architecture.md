# Minimal Architecture

## Goal

- `main.py` はアプリの起動配線だけにする
- 推論、構造推定、セッション管理を分けて責務を明確にする
- PoC の速さは維持しつつ、機能追加時の編集範囲を狭くする

## Current Issues

- HTTP 入出力と業務ロジックが `app/main.py` に集中している
- YOLO 推論の都合で API 層のテストがしにくい
- 構造推定ロジックの差し替え先がない
- フロントエンドは今後 component 単位で分割できる前提が必要

## Target Structure

```text
app/
  main.py          # FastAPI の生成と依存の配線
  api.py           # HTTP endpoint と request/response の責務
  detection.py     # YOLO person detection
  structure.py     # 単一フレームからの床構造推定
  heatmap.py       # セッション、射影、ヒートマップ永続化
frontend/
  src/
    App.svelte     # 単一画面の Svelte component
    lib/
      api-client.ts
      camera.ts
      history.ts
      types.ts
  index.html
  svelte.config.js
  tsconfig.json
  vite.config.ts
  dist/            # Vite build の出力先
docs/
  architecture.md  # この設計メモ
```

## Dependency Direction

```text
frontend/src/App.svelte -> frontend/src/lib/api-client.ts
frontend/src/App.svelte -> frontend/src/lib/camera.ts
frontend/src/App.svelte -> frontend/src/lib/history.ts
frontend/src/lib/api-client.ts -> FastAPI API
frontend build -> frontend/dist
FastAPI / -> frontend/dist/index.html
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
- built frontend の assets mount
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

### `frontend/src/App.svelte`

- 画面全体の state
- 入力フォーム
- カメラ、計測、履歴 UI の統合

### `frontend/src/lib/api-client.ts`

- FastAPI endpoint 呼び出し

### `frontend/src/lib/camera.ts`

- `getUserMedia`
- frame capture

### `frontend/src/lib/history.ts`

- `localStorage` 読み書き

## 関連ドキュメント

- [workflow-and-architecture.md](./workflow-and-architecture.md) … プロダクトの動く仕組み・ワークフロー・セッションライフサイクル・床面射影を Mermaid 図で解説

## Next Step

- API schema が増えたら `pydantic` の request/response model を追加する
- Svelte component が増えるなら `App.svelte` を `components/` と `stores/` に分割する
- 精度改善に進むなら `structure.py` を「簡易推定」と「手動補正」に分ける

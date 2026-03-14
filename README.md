# YOLOv8 Motion Detection PoC

Ultralytics YOLOv8 Pose を使い、スマホのブラウザカメラ映像から簡易動作（手上げ）を検出する PoC です。

## セットアップ

```bash
make setup
```

## 起動

```bash
make run
```

- PCでサーバを起動し、同じWi-Fiのスマホで `http://<PCのIP>:8000` を開きます。
- `カメラ開始` を押すと、定期的にフレームをサーバへ送って推論します。

## ヘルスチェック

```bash
curl http://127.0.0.1:8000/health
```

期待値:

```json
{"status":"ok","model":"yolov8n-pose.pt"}
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

## 動作判定ロジック（簡易）

- 人物キーポイント（肩・手首）を取得
- いずれかの手首 `y` が同側肩の `y` より小さい（画面上側）場合、`hand_raised` と判定

## 注意

- HTTPS でない環境では、スマホブラウザのカメラ制約により動作しない場合があります。
- 初回推論時に `yolov8n-pose.pt` が自動ダウンロードされます。

## トラブルシュート

`Cannot read properties of undefined (reading 'getUserMedia')` が出る場合:

- スマホから `http://<PCのIP>:8000` で開いていると、ブラウザ仕様でカメラAPIが無効になることがあります。
- `https://...` でアクセスするか、まずPCの `http://localhost:8000` で動作確認してください。
- iOS は Safari 推奨です（アプリ内ブラウザは制限されることがあります）。

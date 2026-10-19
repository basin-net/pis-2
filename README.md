# PIS-2 // WICKER BASIN

**A collaborative horror fiction, written as the internal web server of a 1990s classified program.**
The Office of Nonstandard Assets (ONA) does not protect anyone. It acquires, denies, exploits and conceals.
Everything here is invented. See `content/about.md`.

1990年代の米国機密計画の内部サーバー、という体裁の共同創作ホラーです。SCP財団や Backrooms の流れをくみますが、この組織は誰も守りません。未確認の事象を**獲得・阻止・利用・隠蔽**します。すべてフィクションです。

---

## 仕組み

- 1文書＝1ファイル。`content/` 以下の Markdown を `build.py` が1990年代風の HTML に変換し、`_site/` に出力します。
- 日本語版は `ja/content/` にあり、`_site/ja/` に出力されます。英語版と同じファイル名の文書同士が、各ページの「日本語」「English」のリンクで結ばれます。
- 依存ライブラリはありません。Python 3.8 以上があれば動きます。
- `main` ブランチに push すると、GitHub Actions がビルドして GitHub Pages に公開します（`.github/workflows/pages.yml`）。

```
content/            文書（Markdown）。この構成がそのまま URL になる
  index.md          トップページ
  assets/           資産ファイル（BA- / MA- / PA- / LA- / HA-）
  docs/             事故報告・実験・分析・聴取記録など
  j4/               J-4 の残存文書
templates/          ページの雛形（default / box / apache / plain）
ja/content/         日本語版の文書。content/ と同じ構成・同じファイル名・同じ id
ja/templates/       日本語版の雛形
static/             CSS、JavaScript、音声（static/audio/*.wav）。両版で共有
  ja.css            日本語版だけで読み込むフォント設定
tools/make_audio.py 音声の生成・加工ツール（macOS の say を使用）
tools/audio/*.json  音声の台本
build.py            サイト生成
```

## ローカルで見る

```bash
python3 build.py
```

```bash
python3 -m http.server 8000 --directory _site
```

ブラウザで http://localhost:8000 を開きます。最初に警告画面が出るので「I ACKNOWLEDGE」を押してください。日本語版は http://localhost:8000/ja/ です。

リンク切れや ID の重複をエラーにして確認するには、次を実行します。

```bash
python3 build.py --strict
```

## 投稿する

[CONTRIBUTING.md](CONTRIBUTING.md) を読んでください。文書の書式、文体のルール、番号の取り方、運営が予約している主題、音声の作り方をまとめてあります。

## 公開について

- サイトはフィクションであることを `about.html` と警告画面の下に明記しています。消さないでください。
- 実在の人物を加害者・被害者として書かないでください。
- 運営用の正史資料（真相の設定集）は**このリポジトリには入っていません**。今後も入れないでください。

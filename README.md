# FoxDot Radio

FoxDotのパターンをSuperColliderでステレオ音声にし、波形・周波数に反応する映像と一緒にOBSのブラウザソースへ送ります。通常起動では3曲の譜面に続いてローカルの変奏が流れます。Codexライブ作曲では、演奏中の8小節をCodexが順次書き換えます。

## WindowsでOBSに映す

`start-radio.cmd` を起動すると、OBSが同じPC上で映像と音声を読み込めるようになります。映像はOBSのプレビューに、音量はOBSの音声ミキサーに表示されます。

### 初回だけ

1. Python 3.11（PATHに追加）、SuperCollider、OBS Studioを用意します。このフォルダーでPowerShellを開き、次のコマンドを実行します。

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. OBSの **シーンコレクション → シーンコレクションをインポート** で、このフォルダーの `FoxDot_Radio.json` を読み込みます。**シーンコレクション** メニューで **FoxDot Radio** を選びます。映像と音声の設定が入ったシーンが開きます。

既存のシーンに追加する場合は、手順2の代わりに **ソース → ＋ → ブラウザ** を選び、ソース名を **FoxDot Radio** にします。URLを `http://127.0.0.1:18765/?obs=1`、幅を `1920`、高さを `1080` に設定し、**OBSで音声を制御する** を有効にします。

### 配信するたびに

1. `start-radio.cmd` をダブルクリックします。Codexでライブ作曲する場合は `start-codex-radio.cmd` を開きます。起動したウィンドウは配信中そのままにします。
2. OBSで **FoxDot Radio** のシーンコレクション（または設定済みのシーン）を開きます。曲名が表示され、音声ミキサーの **FoxDot Radio** のメーターが動けば準備完了です。
3. 動作確認には **録画開始**、本番では配信先を設定して **配信開始** を押します。終了時はOBSで配信や録画を停止し、起動時のウィンドウで `Ctrl+C` を押します。

### 表示や音声を確認する

- ページの読み込みエラーが出る場合は、起動ウィンドウに `OBS source:` とURLが表示されてから、OBSでソースのプロパティを開き **現在のページのキャッシュを更新** を押します。
- **AUDIO PAUSED** と出た場合は、ソースを右クリックして **対話 (操作)** を開き、**Start audio** を押します。
- 映像のサイズが合わない場合は、ソースを右クリックして **変換 → 画面に合わせる** を選びます。
- OBSを使わず試聴するには [プレビュー](http://127.0.0.1:18765/) を開いて **Play preview** を押します。OBSに戻るときは試聴タブを閉じます。

このPCのSuperCollider 3.14.0では、WAVの出力後に音源プロセスが異常終了する場合があります。試作は、出力ファイルの形式・長さ・音量を検証してから再生に渡します。

## Codexでライブ作曲する

`start-codex-radio.cmd` をダブルクリックし、OBSのソースを表示するか、ブラウザで **Play preview** を押します。OBSの設定は同じです。CodexはPATHとWindows版Codexアプリから探します。見つからない場合はCodex CLIをインストールしてPATHに追加し、未ログインの場合は `codex login` を実行します。

最初の8小節が流れ始めると、アプリは演奏中の譜面を `codex exec` に送ります。以降も45秒以上の間隔で、演奏中の最新版を渡して修正を依頼します。新しい譜面の音声が準備できたら次の8小節の頭で切り替え、待機中やエラー時は今の演奏をループします。呼び出し間隔を変える場合は `python station.py --codex --codex-interval 60` のように秒数を指定します。

ビジュアライザーの背景に演奏中のパターンと小節・ステップが表示されます。鳴った値が光り、修正された値は切り替え後に黄色の下線が付きます。コードの上にはCodexの作曲・音声生成・切り替え待ちの状態が出ます。Codexの呼び出しはログイン中のアカウントの利用枠を消費します。[Codex CLIの公式ドキュメント](https://learn.chatgpt.com/docs/non-interactive-mode)

## 作曲をローカルAIに任せる

Ollamaを起動し、取得済みのモデル名を指定します。初回起動用の2曲に続いてAIが新しい譜面を作ります。生成結果を検証し、応答が遅い場合や譜面が不正な場合はローカル譜面で続行します。

```powershell
python station.py --ollama-model <取得済みのモデル名>
```

画面下部に曲の生成元が表示されます。譜面はJSONの値として扱い、音色・長さ・音高などを検証してから演奏します。

## Ubuntuに移す

Ubuntu DesktopにSuperColliderの言語とサーバー、Pythonの仮想環境、公式版OBS Studioを用意します。プロジェクトをコピーしたあと、以下を実行します。OBSのソース設定とURLは同じです。ブラウザーソースが音声も出すため、この試作では仮想オーディオ出力の設定を省けます。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python station.py
```

`sclang` と `scsynth` をPATHから見つけられない場合は、`--supercollider-dir` に両方が入ったディレクトリを指定します。WindowsではProgram Files内のSuperColliderも探索します。

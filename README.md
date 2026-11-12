# FoxDot Radio

FoxDotのパターンをSuperColliderでステレオ音声にレンダリングし、波形・周波数に反応する映像と一緒にOBSのブラウザーソースへ送る試作です。最初の3曲はCodexが作った譜面です。通常起動では4曲目からローカルのパターン変奏が続きます。曲間はクロスフェードし、次の曲が間に合わないときは今の曲を繰り返します。

## Windowsで起動

Python 3.11、SuperCollider、ブラウザーソース付きのOBS Studioを使います。PythonをPATHに追加し、プロジェクトのフォルダーで依存関係をインストールします。

```powershell
python -m pip install -r requirements.txt
```

1. `start-radio.cmd` をダブルクリックします。開いたターミナルを配信中はそのままにします。
2. 手元で試聴するには [プレビュー](http://127.0.0.1:18765/) を開き、**Play preview** を押します。OBSで確認するときはプレビューを閉じます。
3. OBSの **シーンコレクション → インポート** で `FoxDot_Radio.json` を読み込み、**FoxDot Radio** に切り替えます。既存のシーンを使う場合は **ブラウザー** ソースに `http://127.0.0.1:18765/?obs=1`、サイズ `1920 × 1080` を設定し、**OBSで音声を制御する** を有効にします。
4. OBSのプレビューと音声ミキサーで確認します。ソースが画面からはみ出す場合は **変換 → 画面に合わせる** を選びます。音声が **AUDIO PAUSED** の場合は、ソースを右クリックして **対話** を開き、**Start audio** を押します。

OBSの録画で音声と映像を確認できます。外部への配信は、OBSで配信先を設定してから開始します。

このPCのSuperCollider 3.14.0では、WAVの出力後に音源プロセスが異常終了する場合があります。試作は、出力ファイルの形式・長さ・音量を検証してから再生に渡します。

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

# ナットク台帳

> 一言の説明：（後で書く）

## 審査員が試す手順

### 公開 URL で試す

（後で書く。手元での起動が正の手順です）

### 手元で起動する

必要なもの：[uv](https://docs.astral.sh/uv/)（Python は uv が用意します）。Windows・Mac・Linux で同じ手順です。

```sh
git clone https://github.com/yoshi-tune/visit-ledger.git
cd visit-ledger
uv run uvicorn app.main:app              # http://127.0.0.1:8000/ を開く
```

初めての起動で、見本の台帳 `data/ledger.db` を自動で作ります（乱数の種を固定しているので、誰が作っても同じ中身）。台帳を作り直す時は `uv run python scripts/make_sample.py` を回してください。

**鍵が無くても最後まで試せます。** 効果の画面で「分析を頼む」を押すと、見本の台帳で Claude（Opus 5.5）が実際に分析した時の報告を「見本の報告」として出します（Claude は呼びません。続けての質問はできません）。デモ動画の分析は、鍵を入れた本物の分析です。

本物の分析も試す場合（任意。1回 $1 前後かかります）：

```powershell
# Windows（PowerShell）
$env:ANTHROPIC_API_KEY = "<あなたの鍵>"
uv run python scripts/setup_agent.py     # 分析エージェントを1回だけ作る（ID は data/agent_ids.json に入る）
uv run uvicorn app.main:app
```

```sh
# Mac・Linux
export ANTHROPIC_API_KEY="<あなたの鍵>"
uv run python scripts/setup_agent.py
uv run uvicorn app.main:app
```

効果の画面と分析の画面に出る費用は、定価で数えた目安です（正しい額は Claude Console で確かめてください）。`make_sample.py` で台帳を作り直すと、分析の記録と費用の合計も消えます。1回の上限は環境変数 `VL_BUDGET_CENTS`（セント・既定 300）で変えられます。

## 使い方

アプリの「今日」は **2026-11-07** に固定しています（見本データと時計をそろえるため）。

1. **LP**（スマホ向け）：<http://127.0.0.1:8000/lp/S-EKI?campaign=autumn_check_202610&src=flyer> を開き、「空いている日時を見る」
2. **予約**：メニュー → 日にち（今日 11/7 を選ぶ）→ 空いている時間 → 名前・電話（見本の値で可）→ 確認。送った時点で予約が確定し、予約番号が出る
3. **受付**：<http://127.0.0.1:8000/desk> の「今日の予約」で「来店」
4. **効果の画面**：<http://127.0.0.1:8000/dashboard> でチラシの数字が変わったことを見る →「分析を頼む」
5. **店の設定**：<http://127.0.0.1:8000/settings> で時間帯ごとの台数・休みの曜日・休みの日を変えると、予約の画面にすぐ反映される（見本の初期値：10〜16時の6枠に各2台・毎週水曜は休み）

## Claude の使い方

（後で書く）

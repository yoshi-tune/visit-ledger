"""ナットクに頼むメンテナンス（docs/MAINTENANCE.md 段階 A）：受付に「条件で決まる一覧のタブ」を足す。

    1. 店長が依頼の文を書く（分析の「次の一手」から下書きを出す）
    2. Claude（Sonnet）が、決まった部品だけでタブの条件を提案する。渡すのは今の設定・部品の一覧・依頼の文だけ
       （台帳の行・名前・電話は渡さない）。SQL は書かせない。部品から外れた案はコードで捨てる
    3. アプリが手元で数えて見本を出す（「明日の確定予約 ◯件のうち、条件に合うのは ◯件」とその一覧）
    4. 人が「反映する」を押すと、設定の新しい版として保存する。「さっきの変更を取り消す」で戻せる（お知らせの記録は消えない）

条件の当てはめはこのファイルの match() だけで行う（見本も受付のタブも同じ関数）。
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta

from app import config, ledger

PROPOSE_MODEL = "claude-sonnet-5-5"
SAMPLE_PROPOSAL = config.ROOT / "agent" / "sample_proposal.json"
MAX_TABS = 3

# 条件に使える部品（これ以外は捨てる）。値の範囲もここで決める
STATUS_LABEL = {"confirmed": "予約中", "visited": "来店済み", "cancelled": "取消"}
SRC_LABEL = {"flyer": "チラシ", "line": "LINE", "unknown": "媒体不明"}
PARTS = {
    "status": {"label": "予約の状態", "kind": "choices", "values": list(STATUS_LABEL)},
    "visit_in_days": {"label": "来店予定日が今日から何日後か", "kind": "int", "min": 0, "max": 14},
    "lead_days_min": {"label": "予約を送った日から来店予定日までの日数（◯日以上）", "kind": "int", "min": 0, "max": 60},
    "lead_days_max": {"label": "予約を送った日から来店予定日までの日数（◯日以下）", "kind": "int", "min": 0, "max": 60},
    "menus": {"label": "メニュー", "kind": "choices", "values": list(ledger.MENUS)},
    "srcs": {"label": "媒体", "kind": "choices", "values": list(SRC_LABEL)},
}
# タブの名前に入れてはいけないもの（SQL らしい語・記号）
_SQLISH = re.compile(r"(?i)\b(select|insert|update|delete|drop|where|from|union|join)\b|[;`]|--|/\*")


class ProposalError(Exception):
    """部品から外れた提案（捨てる）。"""


def _day_word(n: int) -> str:
    return {0: "今日", 1: "明日", 2: "明後日"}.get(n, f"{n}日後")


def validate_tab(tab) -> dict:
    """提案されたタブを、決まった部品だけの形に直して返す。外れていれば ProposalError。"""
    if not isinstance(tab, dict) or set(tab) - {"title", "conditions"}:
        raise ProposalError("タブには「名前」と「条件」しか書けません")
    title = tab.get("title")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 20:
        raise ProposalError("タブの名前は1〜20文字です")
    if _SQLISH.search(title):
        raise ProposalError("タブの名前に、使えない語や記号があります")
    cond = tab.get("conditions")
    if not isinstance(cond, dict) or not cond:
        raise ProposalError("条件が1つもありません")
    out: dict = {}
    for key, value in cond.items():
        part = PARTS.get(key)
        if not part:
            raise ProposalError(f"決まった部品に無い条件です：{key}")
        if part["kind"] == "int":
            if isinstance(value, bool) or not isinstance(value, int) or not part["min"] <= value <= part["max"]:
                raise ProposalError(f"{part['label']}は {part['min']}〜{part['max']} の整数です")
            out[key] = value
        else:
            if not isinstance(value, list) or not value or len(set(value)) != len(value) \
                    or any(v not in part["values"] for v in value):
                raise ProposalError(f"{part['label']}に、選べない値があります")
            out[key] = [v for v in part["values"] if v in value]  # 並びを決まった順にそろえる
    if "lead_days_min" in out and "lead_days_max" in out and out["lead_days_min"] > out["lead_days_max"]:
        raise ProposalError("日数の「以上」が「以下」より大きくなっています")
    return {"title": title.strip(), "conditions": out}


def describe(cond: dict) -> list[str]:
    """条件を日本語で全部書く。"""
    out = []
    if "status" in cond:
        out.append("・".join(STATUS_LABEL[s] for s in cond["status"]))
    if "visit_in_days" in cond:
        out.append(f"来店予定日が{_day_word(cond['visit_in_days'])}")
    lo, hi = cond.get("lead_days_min"), cond.get("lead_days_max")
    if lo is not None and hi is not None:
        out.append(f"予約を送った日から来店予定日まで{lo}〜{hi}日")
    elif lo is not None:
        out.append(f"予約を送った日から来店予定日まで{lo}日以上")
    elif hi is not None:
        out.append(f"予約を送った日から来店予定日まで{hi}日以下")
    if "menus" in cond:
        out.append("メニューが" + "・".join(cond["menus"]))
    if "srcs" in cond:
        out.append("媒体が" + "・".join(SRC_LABEL[s] for s in cond["srcs"]))
    return out


def lead_days(r: dict) -> int:
    """予約を送った日から来店予定日までの日数（日時を変えた予約は、変えた後の来店予定日で数える）。設計書 §6 と同じ。"""
    return (date.fromisoformat(r["confirmed_for"][:10]) - date.fromisoformat(r["created_at"][:10])).days


def match(rows: list[dict], cond: dict, today: date) -> list[dict]:
    """条件に合う予約（見本と受付のタブの両方がこれを使う）。"""
    out = []
    for r in rows:
        if "status" in cond and r["status"] not in cond["status"]:
            continue
        if "visit_in_days" in cond and r["confirmed_for"][:10] != (today + timedelta(days=cond["visit_in_days"])).isoformat():
            continue
        if "lead_days_min" in cond and lead_days(r) < cond["lead_days_min"]:
            continue
        if "lead_days_max" in cond and lead_days(r) > cond["lead_days_max"]:
            continue
        if "menus" in cond and r["menu"] not in cond["menus"]:
            continue
        if "srcs" in cond and r["src"] not in cond["srcs"]:
            continue
        out.append(r)
    return out


def preview(rows: list[dict], cond: dict, today: date) -> dict:
    """見本：「明日の確定予約 ◯件のうち、条件に合うのは ◯件」と、その一覧（受付の画面と同じ見え方の項目だけ）。"""
    base_cond = {"status": cond.get("status", ["confirmed"])}
    if "visit_in_days" in cond:
        base_cond["visit_in_days"] = cond["visit_in_days"]
    base = match(rows, base_cond, today)
    hit = match(rows, cond, today)
    where = _day_word(cond["visit_in_days"]) if "visit_in_days" in cond else "これから"
    status = "・".join(STATUS_LABEL[s] for s in base_cond["status"])
    return {
        "base_label": f"{where}の{status}の予約",
        "base_count": len(base),
        "count": len(hit),
        "sentence": f"{where}の{status}の予約 {len(base)}件のうち、条件に合うのは {len(hit)}件です",
        "rows": [{k: r[k] for k in ("reserve_no", "customer_name", "menu", "confirmed_for", "src")}
                 | {"lead_days": lead_days(r)} for r in hit],
    }


# ---- 提案（Claude） --------------------------------------------------------------

PROPOSAL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["possible", "reply"],
    "properties": {
        "possible": {"type": "boolean", "description": "決まった部品で表せるか"},
        "reply": {"type": "string", "description": "店長への返事（2〜4文。表せない時は、何が部品に無いかを言う）"},
        "tab": {
            "type": "object", "additionalProperties": False, "required": ["title", "conditions"],
            "properties": {
                "title": {"type": "string", "description": "受付のタブの名前（20文字まで）"},
                "conditions": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "status": {"type": "array", "items": {"type": "string", "enum": PARTS["status"]["values"]}},
                        "visit_in_days": {"type": "integer"},
                        "lead_days_min": {"type": "integer"},
                        "lead_days_max": {"type": "integer"},
                        "menus": {"type": "array", "items": {"type": "string", "enum": PARTS["menus"]["values"]}},
                        "srcs": {"type": "array", "items": {"type": "string", "enum": PARTS["srcs"]["values"]}},
                    },
                },
            },
        },
    },
}

PROPOSE_SYSTEM = """あなたは、地域の店の受付の道具を直す係「ナットク」です。店長の依頼を読み、受付に足す「一覧のタブ」の条件を提案します。
使える条件は、渡される部品の一覧にあるものだけです。部品の組み合わせ（すべてを満たす予約を出す）で表してください。
- SQL・式・部品に無い条件は書かない。部品で表せない依頼なら possible を false にして、何が部品に無いかを reply で言う
- 「前日にお知らせ」のような依頼は、来店予定日が明日（visit_in_days = 1）・予約中（status = confirmed）にする
- 日数は「予約を送った日から来店予定日までの日数」。日時を変えた予約は、変えた後の来店予定日で数える
- reply は店長向けの日本語で2〜4文。数え方（来店までの道のり・来店率）は変わらないことを添える。件数は書かない（件数はアプリが数えて見せる）
"""


def _parts_for_prompt() -> list[dict]:
    return [{"key": k, "label": v["label"], **({"values": v["values"]} if v["kind"] == "choices"
                                              else {"min": v["min"], "max": v["max"]})} for k, v in PARTS.items()]


def propose_request(text: str, settings: dict) -> dict:
    """Claude に渡す中身（今の設定・部品の一覧・依頼の文だけ）。確かめのために関数を分けている。"""
    tabs = [{"title": t["title"], "conditions": t["conditions"]} for t in settings.get("desk_tabs", [])]
    content = (f"## 今の受付のタブ（足したもの）\n```json\n{json.dumps(tabs, ensure_ascii=False)}\n```\n\n"
               f"## 条件に使える部品\n```json\n{json.dumps(_parts_for_prompt(), ensure_ascii=False, indent=1)}\n```\n\n"
               f"## 店長の依頼\n{text}")
    return {"model": PROPOSE_MODEL, "max_tokens": 2000, "system": PROPOSE_SYSTEM,
            "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default",
            "output_config": {"format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}},
            "messages": [{"role": "user", "content": content}]}


def propose(text: str, settings: dict) -> tuple[dict, str]:
    """(提案, mode)。鍵が無い時は、本物の提案を保存した見本を返す（mode = sample）。"""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        if not SAMPLE_PROPOSAL.exists():
            raise ProposalError("鍵が無く、見本の提案もありません")
        return json.loads(SAMPLE_PROPOSAL.read_text(encoding="utf-8"))["proposal"], "sample"
    import anthropic

    resp = anthropic.Anthropic().beta.messages.create(**propose_request(text, settings))
    raw = next((b.text for b in resp.content if b.type == "text"), "")
    if not raw:
        raise ProposalError(f"提案が返ってきませんでした（{resp.stop_reason}）")
    return json.loads(raw), "claude"


def sample_text() -> str:
    """見本の提案を出した時の依頼の文（鍵が無い時の画面に、そのまま書く）。"""
    return json.loads(SAMPLE_PROPOSAL.read_text(encoding="utf-8"))["text"] if SAMPLE_PROPOSAL.exists() else ""


def check_proposal(proposal: dict, settings: dict) -> dict | None:
    """提案を確かめる。表せないと言った提案は None。部品から外れていれば ProposalError（捨てる）。"""
    if not isinstance(proposal, dict) or set(proposal) - {"possible", "reply", "tab"}:
        raise ProposalError("提案の形が決まりと違います")
    if not proposal.get("possible"):
        return None
    tab = validate_tab(proposal.get("tab"))
    if len(settings.get("desk_tabs", [])) >= MAX_TABS:
        raise ProposalError(f"足せるタブは {MAX_TABS} つまでです")
    if any(t["title"] == tab["title"] for t in settings.get("desk_tabs", [])):
        raise ProposalError("同じ名前のタブがもうあります")
    return tab


def with_tab(settings: dict, tab: dict, tab_id: str) -> dict:
    """add_desk_tab：今の設定にタブを1つ足した新しい設定。"""
    return {**settings, "desk_tabs": [*settings.get("desk_tabs", []), {"id": tab_id, **tab}]}


def draft_text(next_action: dict | None) -> str:
    """分析の「次の一手」から、依頼の文の下書きを作る。"""
    if not next_action or not next_action.get("action"):
        return ""
    return f"分析の次の一手「{next_action['action']}」を受付でできるようにしたい。対象の予約が受付で一覧で分かるようにして。"

// @ts-check
// ナットクに頼む（docs/MAINTENANCE.md 段階 A）：依頼 → ナットクの提案（決まった部品だけの条件）→ アプリが数えた見本 → 人が反映。
// 反映すると受付に一覧のタブが出る。「さっきの変更を取り消す」で戻せる（お知らせの記録は消えない）。
import { api, byId, el, fmtDateTime, pageLoading, srcLabel, toast } from "./common.js";
import { say } from "./mascot.js";

let staff = sessionStorage.getItem("vl:staff") || "A";
let busy = false;
const params = new URLSearchParams(location.search);
const fromAnalysis = params.get("from") || "";

const STATUS = {
  proposed: ["反映を待っています", "warn"], applied: ["反映した", "good"], rejected: ["やめた", "bad"],
  reverted: ["取り消した", "bad"], failed: ["捨てた", "bad"],
};

/** 押している間は、ほかの操作をしない @param {HTMLButtonElement} b @param {() => Promise<void>} fn */
async function act(b, fn) {
  if (busy) return;
  busy = true;
  b.disabled = true;
  try { await fn(); } catch (e) { toast(/** @type {Error} */ (e).message, true); b.disabled = false; } finally { busy = false; }
}

/** @param {string} label @param {string} cls @param {() => Promise<void>} fn @param {string} [ask] */
function button(label, cls, fn, ask) {
  const b = /** @type {HTMLButtonElement} */ (el("button", { class: cls, type: "button" }, [label]));
  b.addEventListener("click", () => { if (!ask || confirm(ask)) act(b, fn); });
  return b;
}

/** 提案の見え方：返事・条件（日本語で全部）・見本（件数と一覧）・反映／やめる @param {any} it */
function proposalCard(it) {
  const children = [];
  if (it.mode === "sample") {
    children.push(el("p", { class: "banner" }, [`見本の提案です。鍵が設定されていないため、依頼「${it.sample_text || "（見本の依頼）"}」で Claude が実際に出した提案をそのまま出しています（今の依頼の文に合わせて作ったものではありません）。件数と一覧は、今の台帳でアプリが数えています。`]));
  }
  if (it.reply) children.push(say(it.reply, it.tab ? "happy" : "think"));
  if (it.status === "failed" || (!it.tab && it.reason)) {
    children.push(el("p", { class: "error-box" }, [it.reason || "提案を使えませんでした"]));
  }
  if (it.tab) {
    children.push(el("h3", {}, [`タブ「${it.tab.title}」の条件`]));
    children.push(el("ul", {}, it.conditions_text.map((/** @type {string} */ t) => el("li", {}, [t]))));
    const p = it.preview;
    children.push(el("p", {}, [el("b", {}, [p.sentence])]));
    if (p.rows.length) {
      children.push(el("div", { class: "cards" }, p.rows.map((/** @type {any} */ r) => el("div", { class: "card rcard" }, [
        el("div", { class: "name" }, [`${r.customer_name} 様`]),
        el("div", { class: "meta" }, [
          el("span", {}, [r.menu]), el("span", {}, [`来店予定 ${fmtDateTime(r.confirmed_for)}`]),
          el("span", { class: "tag" }, [el("span", { class: `dot ${r.src}` }), srcLabel(r.src)]),
          el("span", { class: "muted" }, [`予約を送ってから${r.lead_days}日`]),
        ]),
      ]))));
    }
    if (it.status === "proposed") {
      children.push(el("div", { class: "actions", style: "display:flex;gap:10px;margin-top:12px" }, [
        button("反映する", "btn", async () => {
          await api(`/api/change-requests/${it.id}/apply`, { json: { staff } });
          toast("反映しました。受付にタブが出ています");
          await load();
        }, `受付に「${it.tab.title}」のタブを足します。よいですか？`),
        button("やめる", "btn ghost", async () => {
          await api(`/api/change-requests/${it.id}/reject`, { json: { staff } });
          toast("この提案はやめました");
          await load();
        }),
      ]));
    }
  }
  const [label, tone] = STATUS[/** @type {keyof typeof STATUS} */ (it.status)] || [it.status, "warn"];
  return el("section", { class: "card improve-card", style: "margin-top:16px" }, [
    el("div", { class: "improve-head" }, [
      el("h2", {}, [`依頼 ${it.id}`]), el("span", { class: `badge ${tone}` }, [label]),
      el("span", { class: "muted" }, [`${fmtDateTime(it.created_at)}・${it.requested_by || "—"}`]),
    ]),
    el("p", { class: "muted" }, [`依頼：${it.text}`]),
    ...children,
  ]);
}

async function load() {
  const data = await api("/api/change-requests");
  const tabs = byId("tabs");
  tabs.replaceChildren(...(data.tabs.length
    ? data.tabs.map((/** @type {any} */ t) => el("div", { style: "margin-bottom:8px" }, [
      el("b", {}, [t.title]), el("span", { class: "muted" }, [`　${t.conditions_text.join("・")}`]),
    ]))
    : [el("p", { class: "muted" }, ["足したタブはまだありません（受付は、はじめからあるタブだけです）。"])]));
  tabs.append(el("p", { class: "muted" }, [`設定の版 ${data.version}`]));
  if (data.can_revert) {
    tabs.append(button("さっきの変更を取り消す", "btn ghost", async () => {
      await api("/api/change-requests/revert-last", { json: { staff } });
      toast("取り消しました（お知らせの記録は残っています）");
      await load();
    }, "さっき反映したタブを外します。お知らせの記録は消えません。よいですか？"));
  }
  const first = data.tabs[data.tabs.length - 1];
  tabs.append(el("p", {}, [el("a", { href: first ? `/desk?tab=${encodeURIComponent(`x:${first.id}`)}` : "/desk" }, ["受付で見る →"])]));
  const open = data.items.find((/** @type {any} */ i) => i.status === "proposed");
  byId("result").replaceChildren(...(open ? [proposalCard(open)] : []));
  byId("history").replaceChildren(...data.items.filter((/** @type {any} */ i) => i !== open).map(proposalCard));
}

async function main() {
  const conf = await api("/api/config");
  if (conf.store) byId("store").textContent = conf.store.name;
  const seg = byId("staff");
  for (const s of conf.staff) {
    const b = el("button", { type: "button", "aria-pressed": String(s === staff) }, [s]);
    b.addEventListener("click", () => {
      staff = s;
      sessionStorage.setItem("vl:staff", s);
      for (const x of seg.children) x.setAttribute("aria-pressed", String(x === b));
    });
    seg.append(b);
  }
  const text = /** @type {HTMLTextAreaElement} */ (byId("text"));
  if (fromAnalysis) {
    try {
      const d = await api(`/api/change-requests/draft?from_analysis=${encodeURIComponent(fromAnalysis)}`);
      text.value = d.text;
      byId("source").textContent = "分析の「次の一手」から下書きを作りました。直してから相談できます。";
    } catch { byId("source").textContent = ""; }
  }
  byId("ask").addEventListener("submit", (e) => {
    e.preventDefault();
    const b = /** @type {HTMLButtonElement} */ (byId("send"));
    if (!text.value.trim()) { toast("依頼の文を書いてください", true); return; }
    act(b, async () => {
      byId("result").replaceChildren(say("考えています…", "think"));
      await api("/api/change-requests", { json: { staff, text: text.value.trim(), source_analysis_id: fromAnalysis || null } });
      b.disabled = false;
      await load();
    });
  });
  await load();
}

main().finally(pageLoading()).catch((e) => { byId("error").textContent = e.message; });

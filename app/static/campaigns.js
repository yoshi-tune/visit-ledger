// @ts-check
// 施策を始める（店の設定の画面）：キャンペーンの名前・期間・媒体を入れると、媒体ごとの LP の URL と QR が出る。
// 足した施策は、効果の画面でキャンペーンを選んで見られ、分析にもそのまま入る。
import { api, byId, el, fmtDay, toast } from "./common.js";

/** @param {any} c */
function campaignView(c) {
  return el("div", { class: "campaign-item" }, [
    el("div", { class: "campaign-head" }, [
      el("b", {}, [c.title]),
      el("span", { class: "muted" }, [`${c.started_on ? fmtDay(c.started_on) : "—"} 〜 ${c.ended_on ? fmtDay(c.ended_on) : "—"}・番号 ${c.campaign}`]),
      el("a", { class: "btn sm soft", href: `/dashboard?campaign=${encodeURIComponent(c.campaign)}` }, ["効果の画面で見る →"]),
    ]),
    el("div", { class: "campaign-media-list" }, c.media.map((/** @type {any} */ m) => {
      const url = location.origin + m.lp_path;
      const copy = el("button", { type: "button", class: "btn sm ghost" }, ["URL をコピー"]);
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(url); toast("URL をコピーしました"); } catch { toast(url); }
      });
      return el("div", { class: "campaign-medium" }, [
        el("img", { src: `/api/campaigns/${encodeURIComponent(c.campaign)}/${encodeURIComponent(m.src)}/qr.svg`,
          alt: `${c.title}（${m.label}）の QR コード`, width: "120", height: "120", loading: "lazy" }),
        el("div", {}, [
          el("div", {}, [el("b", {}, [m.label]), m.distributed != null ? el("span", { class: "muted" }, [`　配る数 ${m.distributed}`]) : ""]),
          el("a", { href: m.lp_path, target: "_blank", rel: "noopener", class: "small campaign-url" }, [url]),
          el("div", { style: "margin-top:6px" }, [copy]),
        ]),
      ]);
    })),
  ]);
}

async function load() {
  const { campaigns } = await api("/api/campaigns");
  byId("campaign-list").replaceChildren(...[...campaigns].reverse().map(campaignView));
}

/** @param {string} id */
const input = (id) => /** @type {HTMLInputElement} */ (byId(id));

async function main() {
  const conf = await api("/api/config");
  input("c-start").value = conf.today;
  input("c-end").value = conf.period?.to || conf.today;
  byId("campaign-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    byId("c-error").textContent = "";
    /** @type {Record<string, number | null>} */
    const distributed = {};
    for (const src of ["flyer", "line"]) {
      if (!input(`c-${src}`).checked) continue;
      const n = input(`c-${src}-n`).value;
      distributed[src] = n === "" ? null : Number(n);
    }
    if (!Object.keys(distributed).length) { byId("c-error").textContent = "媒体を1つ以上選んでください"; return; }
    try {
      await api("/api/campaigns", { json: {
        title: input("c-title").value.trim(), started_on: input("c-start").value, ended_on: input("c-end").value, distributed,
      } });
      toast("施策を足しました。QR と URL を使えます");
      input("c-title").value = "";
      await load();
    } catch (e) {
      byId("c-error").textContent = /** @type {Error} */ (e).message;
    }
  });
  await load();
}

main().catch((e) => { byId("c-error").textContent = `読み込めませんでした：${e.message}`; });

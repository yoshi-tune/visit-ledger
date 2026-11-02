// @ts-check
// 画面どうしで使う小さな道具。API の呼び出しと、日時・割合の表示。

/**
 * @param {string} path
 * @param {RequestInit & {json?: unknown}} [opts]
 * @returns {Promise<any>}
 */
export async function api(path, opts = {}) {
  /** @type {RequestInit} */
  const init = { method: opts.method || (opts.json === undefined ? "GET" : "POST") };
  if (opts.json !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const res = await fetch(path, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    throw new Error(detail || `${res.status}`);
  }
  return body;
}

/** @param {string | null | undefined} iso */
export function fmtDateTime(iso) {
  if (!iso) return "—";
  const [d, t] = iso.split("T");
  const [, m, day] = d.split("-");
  return `${Number(m)}/${Number(day)} ${t ? t.slice(0, 5) : ""}`.trim();
}

/** @param {number | null | undefined} rate */
export function fmtRate(rate) {
  return rate === null || rate === undefined ? "算出不可" : `${Math.round(rate * 100)}%`;
}

/** @param {string} src */
export function srcLabel(src) {
  return { flyer: "チラシ", line: "LINE", unknown: "施策不明" }[src] || src;
}

/**
 * @param {string} tag
 * @param {Record<string, string>} [attrs]
 * @param {(Node | string)[]} [children]
 */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

/** @param {string} id */
export function byId(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`#${id} がありません`);
  return node;
}

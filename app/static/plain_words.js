// @ts-check
// 分析担当の報告に出る中の名前（集計のファイル名・台帳の書き出しの表と列の名前）を、画面に出す時だけ店の言葉に置き換える。
// 元の報告と道具の記録は元の名前のまま残す（報告の根拠と道具の記録を照らし合わせる確かめに使う）。
// 表と列は app/export.py の ALLOWED と同じ。表に無い英字はそのまま出る。

/** @type {Record<string, string>} */
const TABLES = {
  sessions: "LP を開いた記録", events: "LP での操作の記録", reservations: "予約", visits: "来店の記録",
  reservation_changes: "予約の変更の記録", campaigns: "施策", coupons: "クーポン",
};

/** @type {Record<string, string>} */
const COLUMNS = {
  session_id: "開いた人の番号", started_at: "LP を開いた時刻", campaign: "施策", src: "媒体", store_id: "店",
  at: "時刻", name: "操作の名前", reserve_no: "予約番号", menu: "メニュー", requested_for: "希望の日時",
  confirmed_for: "来店予定の日時", status: "予約の状態", created_at: "予約した時刻", visited_at: "来店した時刻",
  recorded_at: "来店を記録した時刻", from_status: "変更前の状態", to_status: "変更後の状態", distributed: "配った数",
  started_on: "施策の始まりの日", ended_on: "施策の終わりの日", issued_at: "クーポンを出した時刻",
  redeemed_at: "クーポンを使った時刻",
};

/** @type {Record<string, string>} */
const FILES = { "funnel.json": "アプリの集計", "previous.json": "前回の分析", "report.json": "報告" };

/** @type {Record<string, string>} */
const VALUES = { flyer: "チラシ", unknown: "媒体不明" };

/** 英字の名前の前後が英数字でないこと（単語の一部は置き換えない） @param {string} words */
const token = (words) => new RegExp(`(?<![A-Za-z0-9_])(${words})(?![A-Za-z0-9_])`, "g");
const COLUMN_RE = token(Object.keys(COLUMNS).sort((a, b) => b.length - a.length).join("|"));
const VALUE_RE = token(Object.keys(VALUES).join("|"));

/** 文の中の中の名前を、店の言葉に置き換える @param {string} text */
export function plainWords(text) {
  return text
    .replace(/(?<![A-Za-z0-9_])step_(\d+)(?:\.py)?/g, (_, n) => `集計${Number(n)}`)
    .replace(/(?<![A-Za-z0-9_])chat_(\d+)(?:\.py)?/g, (_, n) => `質問への集計${Number(n)}`)
    .replace(/(?<![A-Za-z0-9_])(funnel|previous|report)\.json/g, (m) => FILES[m])
    .replace(/(?<![A-Za-z0-9_])([a-z_]+)\.csv/g, (m, t) => (TABLES[t] ? `台帳の書き出し（${TABLES[t]}）` : m))
    .replace(/(?<![A-Za-z0-9_])CSV(?![A-Za-z0-9_])/g, "台帳の書き出し")
    .replace(COLUMN_RE, (m) => `「${COLUMNS[m]}」`)
    .replace(VALUE_RE, (m) => VALUES[m])
    // 英字の前後に入っていた空白が、置き換えた後に日本語どうしの間に残るので詰める
    .replace(/(?<=[^\u0000-\u007F]) (?=[^\u0000-\u007F])/g, "")
    // 「アプリの集計（funnel.json）」のように元から言い換えが添えてあると、同じ言葉が括弧で続くので1つにする
    .replace(/([^\s（）]+)（\1）/g, "$1");
}

/** 報告の文をすべて置き換えた写し（元の報告は変えない） @param {any} value @returns {any} */
export function plainReport(value) {
  if (typeof value === "string") return plainWords(value);
  if (Array.isArray(value)) return value.map(plainReport);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plainReport(v)]));
  }
  return value;
}

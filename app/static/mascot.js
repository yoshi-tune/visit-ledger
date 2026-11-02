// @ts-check
// 案内役のキャラクター（スパナの形）。この作品のために描いたもの。
// 表情：normal（ふつう）・happy（にっこり）・think（考え中）・cheer（応援・両手を上げる）

const FACES = {
  normal: `
    <circle cx="41" cy="47" r="3.4" fill="var(--mascot-face)"/>
    <circle cx="59" cy="47" r="3.4" fill="var(--mascot-face)"/>
    <path d="M44 56 Q50 61 56 56" fill="none" stroke="var(--mascot-face)" stroke-width="2.6" stroke-linecap="round"/>`,
  happy: `
    <path d="M37 48 Q41 42 45 48" fill="none" stroke="var(--mascot-face)" stroke-width="2.8" stroke-linecap="round"/>
    <path d="M55 48 Q59 42 63 48" fill="none" stroke="var(--mascot-face)" stroke-width="2.8" stroke-linecap="round"/>
    <path d="M42 55 Q50 65 58 55 Z" fill="var(--mascot-face)"/>`,
  think: `
    <circle cx="43" cy="46" r="3.2" fill="var(--mascot-face)"/>
    <circle cx="61" cy="46" r="3.2" fill="var(--mascot-face)"/>
    <circle cx="52" cy="58" r="2.6" fill="none" stroke="var(--mascot-face)" stroke-width="2.4"/>`,
};

const ARMS = {
  down: `
    <path d="M39 84 Q30 92 31 101" fill="none" stroke="var(--ink)" stroke-width="3" stroke-linecap="round"/>
    <path d="M61 84 Q70 92 69 101" fill="none" stroke="var(--ink)" stroke-width="3" stroke-linecap="round"/>`,
  up: `
    <path d="M39 84 Q20 80 11 62" fill="none" stroke="var(--ink)" stroke-width="3" stroke-linecap="round"/>
    <path d="M61 84 Q80 80 89 62" fill="none" stroke="var(--ink)" stroke-width="3" stroke-linecap="round"/>
    <circle cx="11" cy="60" r="3.2" fill="var(--mascot)" stroke="var(--ink)" stroke-width="2"/>
    <circle cx="89" cy="60" r="3.2" fill="var(--mascot)" stroke="var(--ink)" stroke-width="2"/>`,
  chin: `
    <path d="M39 84 Q30 92 31 101" fill="none" stroke="var(--ink)" stroke-width="3" stroke-linecap="round"/>
    <path d="M61 86 Q78 84 74 72" fill="none" stroke="var(--ink)" stroke-width="3" stroke-linecap="round"/>`,
};

/**
 * キャラクターの SVG を作る。
 * @param {"normal" | "happy" | "think" | "cheer"} [mood]
 * @param {number} [size] 高さ（px）
 */
export function mascot(mood = "normal", size = 72) {
  const face = mood === "cheer" ? FACES.happy : FACES[mood];
  const arms = mood === "cheer" ? ARMS.up : mood === "think" ? ARMS.chin : ARMS.down;
  const id = `m${Math.random().toString(36).slice(2, 8)}`;
  const wrap = document.createElement("span");
  wrap.className = `mascot mood-${mood}`;
  wrap.setAttribute("aria-hidden", "true");
  wrap.innerHTML = `
  <svg viewBox="0 0 100 130" width="${Math.round(size * 100 / 130)}" height="${size}">
    <defs>
      <mask id="${id}">
        <rect width="100" height="130" fill="#fff"/>
        <path d="M38 0 H62 V19 Q62 28 50 28 Q38 28 38 19 Z" fill="#000"/>
      </mask>
    </defs>
    ${arms}
    <rect x="38" y="66" width="24" height="56" rx="12" fill="var(--mascot)" stroke="var(--ink)" stroke-width="3"/>
    <circle cx="50" cy="114" r="4" fill="none" stroke="var(--ink)" stroke-width="2" opacity="0.5"/>
    <g mask="url(#${id})">
      <circle cx="50" cy="46" r="32" fill="var(--mascot)" stroke="var(--ink)" stroke-width="3"/>
    </g>
    <path d="M38 16.7 V19 Q38 28 50 28 Q62 28 62 19 V16.7" fill="none" stroke="var(--ink)" stroke-width="3" stroke-linejoin="round"/>
    <circle cx="35" cy="57" r="4.5" fill="var(--series-flyer)" opacity="0.45"/>
    <circle cx="65" cy="57" r="4.5" fill="var(--series-flyer)" opacity="0.45"/>
    ${face}
  </svg>`;
  return wrap;
}

/**
 * キャラクターと吹き出し。
 * @param {string | Node} text
 * @param {"normal" | "happy" | "think" | "cheer"} [mood]
 * @param {{size?: number, cls?: string}} [opt]
 */
export function say(text, mood = "normal", opt = {}) {
  const box = document.createElement("div");
  box.className = `say ${opt.cls || ""}`.trim();
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.append(text);
  box.append(mascot(mood, opt.size || 72), bubble);
  return box;
}

// @ts-check
// 案内役のキャラクター「ナットク」。スパナの形のドット絵（この作品のために描いたもの）。
// 名前は整備の部品「ナット」と「納得」から。数字の根拠を見せて、店長に納得してもらう役。
// 表情：normal（ふつう）・happy（にっこり）・think（考え中）・cheer（応援・両手を上げる）

export const NAME = "ナットク";

// 18×28 のドット。o=輪郭 b=体 h=光 （顔・腕は下で重ねる）。丸い頭（口が上に開く）＋長い持ち手
const BODY = [
  "..oooo......oooo..",
  ".obhbbo....obbbbo.",
  "obhbbbo....obbbbbo",
  "obhbbbo....obbbbbo",
  "obbbbbo....obbbbbo",
  "obbbbbboooobbbbbbo",
  "obbbbbbbbbbbbbbbbo",
  "obbbbbbbbbbbbbbbbo",
  "obbbbbbbbbbbbbbbbo",
  "obbbbbbbbbbbbbbbbo",
  ".obbbbbbbbbbbbbbo.",
  "..obbbbbbbbbbbbo..",
  "...oobbbbbbbboo...",
  ".....obbbbbbo.....",
  ".....obhbbbbo.....",
  ".....obhbbbbo.....",
  ".....obhbbbbo.....",
  ".....obbbbbbo.....",
  ".....obbbbbbo.....",
  ".....obbbbbbo.....",
  ".....obbbbbbo.....",
  ".....obbbbbbo.....",
  ".....obbbbbbo.....",
  ".....obbbbbbo.....",
  ".....obbbbbbo.....",
  ".....obbbbbbo.....",
  "......obbbbo......",
  ".......oooo.......",
];
const W = 18;
const H = BODY.length;

/** @typedef {[number, number, string][]} Pixels  [x, y, 色の記号] */

/** @type {Record<string, Pixels>} */
const FACES = {
  normal: [
    [4, 6, "e"], [5, 6, "e"], [4, 7, "e"], [5, 7, "e"],
    [12, 6, "e"], [13, 6, "e"], [12, 7, "e"], [13, 7, "e"],
    [7, 8, "e"], [10, 8, "e"], [8, 9, "e"], [9, 9, "e"],
    [2, 8, "c"], [15, 8, "c"],
  ],
  happy: [
    [5, 6, "e"], [4, 7, "e"], [6, 7, "e"],
    [12, 6, "e"], [11, 7, "e"], [13, 7, "e"],
    [7, 8, "e"], [8, 8, "e"], [9, 8, "e"], [10, 8, "e"], [8, 9, "m"], [9, 9, "m"],
    [2, 8, "c"], [15, 8, "c"],
  ],
  think: [
    [5, 6, "e"], [6, 6, "e"], [5, 7, "e"], [6, 7, "e"],
    [13, 6, "e"], [14, 6, "e"], [13, 7, "e"], [14, 7, "e"],
    [10, 9, "e"], [11, 9, "e"],
    [2, 8, "c"], [15, 8, "c"],
  ],
};

/** @type {Record<string, Pixels>} */
const ARMS = {
  down: [[4, 15, "o"], [3, 16, "o"], [2, 17, "o"], [13, 15, "o"], [14, 16, "o"], [15, 17, "o"]],
  up: [[4, 15, "o"], [3, 14, "o"], [2, 13, "o"], [1, 12, "o"], [13, 15, "o"], [14, 14, "o"], [15, 13, "o"], [16, 12, "o"]],
  chin: [[4, 15, "o"], [3, 16, "o"], [2, 17, "o"], [13, 15, "o"], [14, 14, "o"], [14, 13, "o"]],
};

const COLORS = {
  o: "var(--px-line)",
  b: "var(--px-body)",
  h: "var(--px-light)",
  e: "var(--px-face)",
  m: "var(--px-mouth)",
  c: "var(--px-cheek)",
};

/**
 * キャラクターの SVG を作る（ドットは横に続く同じ色をまとめて描く）。
 * @param {"normal" | "happy" | "think" | "cheer"} [mood]
 * @param {number} [size] 高さ（px）
 */
export function mascot(mood = "normal", size = 72) {
  const grid = BODY.map((row) => row.split(""));
  const face = FACES[mood === "cheer" ? "happy" : mood];
  const arms = ARMS[mood === "cheer" ? "up" : mood === "think" ? "chin" : "down"];
  for (const [x, y, c] of [...arms, ...face]) grid[y][x] = c;

  let rects = "";
  grid.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const c = row[x];
      let w = 1;
      while (x + w < row.length && row[x + w] === c) w++;
      if (c !== ".") rects += `<rect x="${x}" y="${y}" width="${w}" height="1" fill="${COLORS[/** @type {keyof typeof COLORS} */ (c)]}"/>`;
      x += w;
    }
  });
  const wrap = document.createElement("span");
  wrap.className = `mascot mood-${mood}`;
  wrap.setAttribute("aria-hidden", "true");
  wrap.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${Math.round(size * W / H)}" height="${size}" shape-rendering="crispEdges">${rects}</svg>`;
  return wrap;
}

/**
 * キャラクターと吹き出し（吹き出しの上に名前の札）。
 * @param {string | Node} text
 * @param {"normal" | "happy" | "think" | "cheer"} [mood]
 * @param {{size?: number, cls?: string}} [opt]
 */
export function say(text, mood = "normal", opt = {}) {
  const box = document.createElement("div");
  box.className = `say ${opt.cls || ""}`.trim();
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const who = document.createElement("b");
  who.className = "who";
  who.textContent = NAME;
  bubble.append(who, text);
  box.append(mascot(mood, opt.size || 72), bubble);
  return box;
}

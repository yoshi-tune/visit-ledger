// @ts-check
// 案内役のキャラクター「ナットク」。ナットをくわえたスパナのドット絵（この作品のために描いたもの）。
// 名前は整備の部品「ナット」と「納得」から。ナットをきゅっと締めるように、数字の根拠で店長に納得してもらう役。
// 表情：normal（ふつう）・happy（にっこり）・think（考え中）・cheer（応援・両手を上げる）・work（ナットを締めている＝読み込み中）

export const NAME = "ナットク";

// 18×32 のドット。o=輪郭 b=体 h=光。丸い頭の口に六角のナットをくわえ、長い持ち手が付く。
// 上の4行はナットの出っ張りの分。顔・腕・ナットは下で重ねる
const BODY = [
  "..................",
  "..................",
  "..................",
  "..................",
  "..oooo......oooo..",
  ".obhbo......obbbo.",
  "obhbbo......obbbbo",
  "obhbbo......obbbbo",
  "obbbbo......obbbbo",
  "obbbbboooooobbbbbo",
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
const Y = 4; // 頭の上端の行（顔と腕の位置はここからの行で書く）

/** @typedef {[number, number, string][]} Pixels  [x, y, 色の記号] */

/** @param {Pixels} list 頭の上端からの行で書いた点を、全体の行に直す */
const at = (list) => list.map(([x, y, c]) => /** @type {[number, number, string]} */ ([x, y + Y, c]));

// くわえているナット（六角・真ん中に穴）。n=銀 l=光 k=穴
const NUT = at([
  [8, -3, "o"], [9, -3, "o"],
  [7, -2, "o"], [8, -2, "l"], [9, -2, "n"], [10, -2, "o"],
  [6, -1, "o"], [7, -1, "l"], [8, -1, "n"], [9, -1, "n"], [10, -1, "n"], [11, -1, "o"],
  [6, 0, "o"], [7, 0, "n"], [8, 0, "k"], [9, 0, "k"], [10, 0, "n"], [11, 0, "o"],
  [6, 1, "o"], [7, 1, "n"], [8, 1, "k"], [9, 1, "k"], [10, 1, "n"], [11, 1, "o"],
  [6, 2, "o"], [7, 2, "n"], [8, 2, "n"], [9, 2, "n"], [10, 2, "n"], [11, 2, "o"],
  [7, 3, "o"], [8, 3, "n"], [9, 3, "n"], [10, 3, "o"],
  [8, 4, "o"], [9, 4, "o"],
]);

// 応援の時のきらっ
const SPARK = at([[4, -3, "s"], [3, -2, "s"], [4, -2, "s"], [5, -2, "s"], [4, -1, "s"], [14, -4, "s"], [14, -2, "s"], [13, -3, "s"], [15, -3, "s"]]);

/** @type {Record<string, Pixels>} */
const FACES = {
  normal: at([
    [4, 6, "e"], [5, 6, "e"], [4, 7, "e"], [5, 7, "e"],
    [12, 6, "e"], [13, 6, "e"], [12, 7, "e"], [13, 7, "e"],
    [7, 8, "e"], [10, 8, "e"], [8, 9, "e"], [9, 9, "e"],
    [2, 8, "c"], [15, 8, "c"],
  ]),
  happy: at([
    [5, 6, "e"], [4, 7, "e"], [6, 7, "e"],
    [12, 6, "e"], [11, 7, "e"], [13, 7, "e"],
    [7, 8, "e"], [8, 8, "e"], [9, 8, "e"], [10, 8, "e"], [8, 9, "m"], [9, 9, "m"],
    [2, 8, "c"], [15, 8, "c"],
  ]),
  think: at([
    [5, 6, "e"], [6, 6, "e"], [5, 7, "e"], [6, 7, "e"],
    [13, 6, "e"], [14, 6, "e"], [13, 7, "e"], [14, 7, "e"],
    [10, 9, "e"], [11, 9, "e"],
    [2, 8, "c"], [15, 8, "c"],
  ]),
};

/** @type {Record<string, Pixels>} */
const ARMS = {
  down: at([[4, 15, "o"], [3, 16, "o"], [2, 17, "o"], [13, 15, "o"], [14, 16, "o"], [15, 17, "o"]]),
  up: at([[4, 15, "o"], [3, 14, "o"], [2, 13, "o"], [1, 12, "o"], [13, 15, "o"], [14, 14, "o"], [15, 13, "o"], [16, 12, "o"]]),
  chin: at([[4, 15, "o"], [3, 16, "o"], [2, 17, "o"], [13, 15, "o"], [14, 14, "o"], [14, 13, "o"]]),
};

const COLORS = {
  o: "var(--px-line)",
  b: "var(--px-body)",
  h: "var(--px-light)",
  e: "var(--px-face)",
  m: "var(--px-mouth)",
  c: "var(--px-cheek)",
  n: "var(--px-nut)",
  l: "var(--px-nut-light)",
  k: "var(--px-line)",
  s: "var(--px-spark)",
};

/** @typedef {"normal" | "happy" | "think" | "cheer" | "work"} Mood */

/**
 * キャラクターの SVG を作る（ドットは横に続く同じ色をまとめて描く）。
 * work のときは、くわえたナットを中心にスパナごと回して「締める」動きをする。
 * @param {Mood} [mood]
 * @param {number} [size] 高さ（px）
 */
export function mascot(mood = "normal", size = 72) {
  const grid = BODY.map((row) => row.split(""));
  const face = FACES[mood === "cheer" ? "happy" : mood === "work" ? "happy" : mood];
  const arms = ARMS[mood === "cheer" ? "up" : mood === "think" ? "chin" : "down"];
  const extra = mood === "cheer" ? SPARK : [];
  for (const [x, y, c] of [...NUT, ...arms, ...face, ...extra]) grid[y][x] = c;

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
  wrap.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${Math.round(size * W / H)}" height="${size}" shape-rendering="crispEdges">${rects}</svg>`
    + (mood === "work" ? `<span class="kyu">きゅっ</span>` : "");
  return wrap;
}

/**
 * 読み込み中の表示：ナットクがナットを締めている。
 * @param {string} [text]
 * @param {number} [size]
 */
export function loader(text = "読み込んでいます", size = 120) {
  const box = document.createElement("div");
  box.className = "loader";
  box.setAttribute("role", "status");
  const label = document.createElement("div");
  label.className = "loader-text";
  label.textContent = text;
  box.append(mascot("work", size), label);
  return box;
}

/**
 * キャラクターと吹き出し（吹き出しの上に名前の札）。
 * @param {string | Node} text
 * @param {Mood} [mood]
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

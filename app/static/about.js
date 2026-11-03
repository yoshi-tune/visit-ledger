// @ts-check
// ナットク台帳のしくみ（1ページの図）：デモ動画の「全体の形」で映す。上の並びには載せない。
import { byId } from "./common.js";
import { mascot } from "./mascot.js";

byId("mascot").replaceChildren(mascot("normal", 88));

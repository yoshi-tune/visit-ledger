// @ts-check
// ナットク台帳のしくみ（お客様の道のり＋役割の分け方）：デモ動画の「道のり」で映す。上の並びには載せない。
import { byId } from "./common.js";
import { mascot } from "./mascot.js";

byId("mascot").replaceChildren(mascot("normal", 88));

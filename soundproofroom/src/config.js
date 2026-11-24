/**
 * 聲學測試室 —— 場景設定(組裝層)
 *
 * 這個檔案本身**沒有任何數字**,只負責把兩份資料合起來:
 *
 *     spec.json ⭐ 規格尺寸 —— 要改尺寸改這裡(純資料,每區的 _src 寫出處)
 *     look.js      顏色 / 材質 / 燈光 / 相機 —— 要改外觀改這裡
 *              ↓
 *     CONFIG       builders.js 與 main.js 讀這個
 *
 * 分成兩份的理由:規格數字會拿去對現場、會被人質疑「這 0.42 哪來的」,
 * 所以要能單獨拿出來看。顏色不會。混在一起的話,改尺寸時要在
 * 一堆 0x9aa3ad 裡面找 0.42,很容易改錯。
 *
 * spec.json 用瀏覽器原生的 JSON module(import attributes)載入,
 * 免 build 模式與 Vite 都吃這個寫法。以 _ 開頭的欄位是說明,這裡濾掉。
 */

import RAW_SPEC from './spec.json' with { type: 'json' };
import { LOOK } from './look.js';

const isPlain = (v) => v && typeof v === 'object' && !Array.isArray(v);

/** 拿掉 _readme / _src 這類說明欄位 */
function stripNotes(v) {
  if (Array.isArray(v)) return v.map(stripNotes);
  if (!isPlain(v)) return v;
  return Object.fromEntries(Object.entries(v)
    .filter(([k]) => !k.startsWith('_'))
    .map(([k, x]) => [k, stripNotes(x)]));
}

const SPEC = stripNotes(RAW_SPEC);

/** 深層合併:同名的物件往下併,其他直接覆蓋(陣列整個換掉) */
function merge(base, over) {
  const out = { ...base };
  for (const k of Object.keys(over)) {
    out[k] = isPlain(over[k]) && isPlain(base[k]) ? merge(base[k], over[k]) : over[k];
  }
  return out;
}

export const CONFIG = merge(SPEC, LOOK);

export const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

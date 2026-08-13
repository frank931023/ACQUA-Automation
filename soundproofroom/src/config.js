/**
 * 聲學測試室 —— 場景常數
 *
 * 單位一律「公尺」。要改尺寸只動這個檔案。
 *
 * 座標系(three.js 慣例,Y 朝上),原點在房間正中央的地板:
 *    X = 寬 3.41  ・  Y = 高 2.35  ・  Z = 深 5.20
 *    喇叭陣列在 -Z 端,大螢幕在 +Z 端(兩者相對)
 *
 * ⚠️ 標「推估」的是圖面沒標、依比例抓的,對照現場再調。
 */

export const CONFIG = {
  room: {
    width: 3.41, depth: 5.20, height: 2.35,
    color: 0x9aa3ad, opacity: 0.16,
    floorColor: 0x7d858e, floorOpacity: 0.55,
  },

  // ── 天花板:喇叭主滑軌 ──────────────────────────
  mainRail: {
    length: 2.00, z: -1.75, y: 2.20, barSize: 0.055, color: 0xd8dde3,
    travel: { min: -0.85, max: 0.85, default: 0.0 },
  },
  bracketRail: {
    length: 0.80, min: 0.50, max: 0.80, default: 0.65,
    barSize: 0.04, color: 0xc3c9d1,
  },
  speakerArray: {
    cols: 2, rows: 4, spacingX: 0.30, spacingY: 0.42,
    speaker: { radius: 0.085, depth: 0.26, color: 0x24282e, coneColor: 0x15181c },
    frame: { width: 0.72, thickness: 0.05, color: 0x3a4048 },
  },

  // ── 大螢幕(喇叭陣列的對面)可上下 + 前後 ────────
  screen: {
    width: 1.22,          // 推估:約 55 吋
    height: 0.71,
    thickness: 0.055,
    bezel: 0.022,
    panelColor: 0x14171b,
    frameColor: 0x3a4048,
    standColor: 0xc0c6cd,
    /** 螢幕中心離地高度 */
    lift: { min: 0.70, max: 1.90, default: 1.25 },
    /** 前後行程 */
    travelZ: { min: 1.20, max: 2.35, default: 2.05 },
  },

  // ── 地面:HATS 雙層滑軌 ────────────────────────
  floorRailZ: {
    length: 4.61, gauge: 0.54, barSize: 0.05, y: 0.05, color: 0xd8dde3,
    travel: { min: -1.85, max: 1.85, default: -0.30 },
  },
  floorRailX: {
    length: 1.60,         // 推估
    barSize: 0.045, y: 0.115, color: 0xc8ced5,
    travel: { min: -0.55, max: 0.55, default: 0.0 },
  },

  // ── HATS:B&K 4128 + HMS II.3 立架 ──────────────
  hats: {
    totalHeight: 0.695,
    torso: { width: 0.410, height: 0.460, depth: 0.183, color: 0xe8e4de },
    neck: { diameter: 0.112 },
    head: { radius: 0.098, color: 0xf0ece6 },
    /** 頭部前傾角:規格標「垂直 或 17°」,但這裡做成連續可調 */
    headAngle: { min: -15, max: 35, default: 0, presets: [0, 17] },
    stand: {
      test: 1.20, min: 0.75, max: 1.50,
      columnRadius: 0.055, baseSize: 0.42, color: 0xd0d6dc,
    },
    mrpOffset: 0.225,     // HMS II.3 托座 → MRP
    platform: { size: 0.80, height: 0.10, color: 0xe4e8ec },
    turntable: { radius: 0.30, height: 0.05, color: 0xb9c0c8, defaultAngleDeg: 0 },
    mouth: { radius: 0.032, depth: 0.05, color: 0x8a9099 },
  },

  // ── 桌台(升降 + 前後可移動)────────────────────
  tables: {
    size: 0.80, thickness: 0.05,
    color: 0xeceff2, columnColor: 0xc0c6cd,
    items: [
      {
        key: 'tableFront', label: '前方 DUT 升降台',
        lift: { test: 0.90, min: 0.40, max: 2.30 },
        travelZ: { min: 0.55, max: 2.00, default: 1.35 },
      },
      {
        key: 'tableBack', label: '後方 Dixie 升降台',
        lift: { test: 1.20, min: 0.40, max: 2.30 },
        travelZ: { min: -2.00, max: -0.55, default: -0.95 },
      },
    ],
  },

  // ── 天花板麥克風吊架 × 2 組 ─────────────────────
  micRig: {
    bridge: { length: 2.60, barSize: 0.05, y: 2.28, color: 0xd8dde3 },
    /** 高度規格:測試 0.95 / 1.25 m,範圍 0.70 ~ 1.50 m */
    height: { min: 0.70, max: 1.50, presets: [0.95, 1.25] },
    mic: {
      bodyRadius: 0.0135, bodyLength: 0.10,
      preampRadius: 0.0125, preampLength: 0.12,
      color: 0xd8dde0, capsuleColor: 0x2f343b,
    },
    rod: { radius: 0.014, color: 0xbfc6cd },
    /** 兩組吊架各自的行程與預設 */
    items: [
      {
        key: 'micRig1', label: '麥克風吊架 1',
        travelX: { min: -1.10, max: 1.10, default: -0.35 },
        travelZ: { min: -1.30, max: 1.70, default: 0.55 },
        heightDefault: 0.95,
      },
      {
        key: 'micRig2', label: '麥克風吊架 2',
        travelX: { min: -1.10, max: 1.10, default: 0.40 },
        travelZ: { min: -1.30, max: 1.70, default: -0.35 },
        heightDefault: 1.25,
      },
    ],
  },

  /** KEF LS50 Meta 主喇叭(靜態擺放) */
  kef: {
    width: 0.200, height: 0.302, depth: 0.281,
    color: 0x2b3036, coneRadius: 0.062, standHeight: 0.30,
    x: 1.30, z: 0.90,     // 推估
  },

  highlight: 0x4f8ef7,

  camera: {
    fov: 50, near: 0.05, far: 100,
    position: [4.2, 3.0, 5.4],
    target: [0, 1.0, 0],
  },
};

export const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

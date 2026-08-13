/**
 * 聲學測試室 —— 場景常數
 *
 * ⚠️ 所有尺寸單位都是「公尺」,跟現場圖面一致。
 *    要改尺寸只要動這個檔案,其他程式碼都是從這裡讀。
 *
 * 座標系(three.js 慣例:Y 朝上):
 *    X = 房間寬度  (3.41)  —— 主滑軌沿這個方向
 *    Y = 房間高度  (2.50)
 *    Z = 房間深度  (5.20)  —— 地面滑軌沿這個方向
 *
 * 原點在房間正中央的地板上,所以:
 *    X ∈ [-1.705, +1.705]
 *    Y ∈ [0, 2.5]
 *    Z ∈ [-2.60, +2.60]
 */

export const CONFIG = {
  /** 房間外框 */
  room: {
    width: 3.41,          // X
    depth: 5.20,          // Z
    height: 2.50,         // Y
    wallThickness: 0.06,
    color: 0x9aa3ad,
    opacity: 0.18,        // 半透明,才看得到裡面
    floorColor: 0x7d858e,
    floorOpacity: 0.55,
  },

  /** 天花板主滑軌 —— 喇叭陣列掛在上面,沿 X 移動 */
  mainRail: {
    length: 2.00,         // 滑軌本身長度
    z: -1.55,             // 靠近房間一端(圖面上喇叭那側)
    y: 2.34,              // 離地高度
    barSize: 0.055,       // 軌道方管邊長
    color: 0xd8dde3,
    /** 掛車可移動的範圍(沿 X)。以滑軌中心為 0,兩端各留一點餘裕 */
    travel: { min: -0.85, max: 0.85, default: 0.0 },
  },

  /** 喇叭支架滑軌 —— 控制喇叭陣列吊掛的下降量 */
  bracketRail: {
    length: 0.80,         // 支架滑軌長度
    min: 0.50,            // 可調節下限
    max: 0.80,            // 可調節上限
    default: 0.65,
    barSize: 0.04,
    color: 0xc3c9d1,
  },

  /** 喇叭陣列:2 欄 × 4 列 = 8 顆 */
  speakerArray: {
    cols: 2,
    rows: 4,
    spacingX: 0.30,       // 欄距
    spacingY: 0.42,       // 列距(對應圖面的 0.42 m)
    /** 單顆喇叭(圓柱體,朝 +Z 方向也就是房間內側) */
    speaker: {
      radius: 0.085,
      depth: 0.26,
      color: 0x24282e,
      coneColor: 0x15181c,
    },
    frame: {
      width: 0.72,
      thickness: 0.05,
      color: 0x3a4048,
    },
  },

  /** 地面滑軌 —— HATS 平台沿 Z 前後移動 */
  floorRail: {
    length: 4.61,         // 圖面標註 4.61 m
    gauge: 0.54,          // 兩條軌道的間距(圖面 0.54 m)
    barSize: 0.05,
    y: 0.05,
    color: 0xd8dde3,
    /** 平台可移動範圍(沿 Z) */
    travel: { min: -1.90, max: 1.90, default: -0.30 },
  },

  /** HATS 人形量測頭 + 可旋轉平台 */
  hats: {
    /** 旋轉平台(圖面 0.80 × 0.80) */
    platform: {
      size: 0.80,
      height: 0.12,
      color: 0xe4e8ec,
    },
    /** 轉盤 */
    turntable: {
      radius: 0.30,
      height: 0.06,
      color: 0xb9c0c8,
      defaultAngleDeg: 0,
    },
    /** 軀幹 */
    torso: {
      width: 0.42,
      height: 0.52,
      depth: 0.24,
      color: 0xe8e4de,
    },
    /** 頭部 */
    head: {
      radius: 0.105,
      color: 0xf0ece6,
    },
    /** 座柱高度(平台上方到軀幹底部) */
    pedestalHeight: 0.30,
  },

  /** 天花板吊掛麥克風(圖面上那兩支) */
  ceilingMics: [
    { x: -0.45, z: 0.55 },
    { x: 0.45, z: 0.15 },
  ],
  mic: {
    bodyRadiusTop: 0.055,
    bodyRadiusBottom: 0.085,
    bodyHeight: 0.46,
    capsuleRadius: 0.05,
    color: 0xdfe4e9,
    capsuleColor: 0x2a2f36,
  },

  /** 拖曳時的高亮顏色 */
  highlight: 0x4f8ef7,

  /** 相機 */
  camera: {
    fov: 50,
    near: 0.05,
    far: 100,
    position: [4.2, 3.0, 5.2],
    target: [0, 1.0, 0],
  },
};

/** 把數值夾在區間內 —— 拖曳與 slider 都會用到 */
export const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

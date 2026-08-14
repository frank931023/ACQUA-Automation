/**
 * ⭐ 聲學測試室 —— 規格數字
 * ══════════════════════════════════════════════════════════
 *
 *   **要改尺寸,只改這個檔案。** 這裡沒有任何顏色、材質、燈光、程式邏輯,
 *   純粹就是「你拿尺去量會得到的數字」。
 *
 *   單位一律「公尺」,角度一律「度」。
 *
 *   座標系(three.js 慣例,Y 朝上),原點在房間正中央的地板:
 *      X = 寬 3.41  ・  Y = 高 2.35  ・  Z = 深 5.20
 *      喇叭陣列在 -Z 端,大螢幕在 +Z 端(兩者相對)
 *
 *   每個數字後面的標記:
 *      [規格]  設備原廠規格書 / 測試規範明確寫的
 *      [圖面]  現場圖面標註的
 *      [推估]  ⚠️ 圖面沒標、依比例抓的,對照現場要調
 *      [構造]  模型結構件(底座、滑車、托座),照片目測
 *
 *   相對比例(例如「端塊是滑軌的 2.2 倍粗」)刻意留在 builders.js,
 *   因為那種數字會自己跟著這裡的尺寸縮放,拉出來反而變兩處要改。
 */

export const SPEC = {

  // ══ 房間 ═════════════════════════════════════════════════
  room: {
    width: 3.41,          // [規格]
    depth: 5.20,          // [規格]
    height: 2.35,         // [規格]
  },

  // ══ 天花板:喇叭主滑軌 ═══════════════════════════════════
  mainRail: {
    length: 2.00,         // [圖面]
    z: -1.75,             // [推估] 圖面只標長度,沒標在房間裡的位置
    y: 2.20,              // [推估]
    barSize: 0.055,       // [構造] 方管邊長
    travel: { min: -0.85, max: 0.85, default: 0.0 },   // [圖面] 由 length 推得
  },

  // 喇叭陣列往下垂的支架滑軌
  bracketRail: {
    length: 0.80,         // [圖面]
    min: 0.50,            // [圖面] 可調下降量
    max: 0.80,
    default: 0.65,
    barSize: 0.04,        // [構造]
  },

  // ══ 喇叭陣列 2 × 4 ═══════════════════════════════════════
  speakerArray: {
    cols: 2,              // [圖面]
    rows: 4,              // [圖面]
    spacingX: 0.30,       // [推估]
    spacingY: 0.42,       // [推估]
    carriage: {           // [構造] 掛在主滑軌上的滑車
      width: 0.26, height: 0.10, depth: 0.16,
    },
    speaker: {
      radius: 0.085,      // [推估] 單體半徑
      depth: 0.26,        // [推估]
      coneRatio: 0.72,    // 錐盆佔單體的比例
    },
    frame: {
      width: 0.72,        // [推估] 背板寬
      thickness: 0.05,    // [構造]
      margin: 0.36,       // [構造] 背板比單體陣列高出來的部分
      backOffset: 0.03,   // [構造] 背板退到單體後面多少
    },
  },

  // ══ 大螢幕(喇叭陣列的對面)═══════════════════════════════
  screen: {
    width: 1.22,          // [推估] 約 55 吋
    height: 0.71,         // [推估]
    thickness: 0.055,     // [推估]
    bezel: 0.022,         // [推估] 外框寬

    lift: { min: 0.70, max: 1.90, default: 1.25 },      // [推估] 螢幕中心離地
    travelZ: { min: 1.20, max: 2.35, default: 2.05 },   // [推估] 前後行程

    base: { width: 0.62, height: 0.04, depth: 0.42 },   // [構造] 底盤
    foot: { width: 0.07, height: 0.05, depth: 0.40,
            spacing: 0.24 },                            // [構造] 兩隻腳,spacing = 離中心
    column: { size: 0.10 },                             // [構造] 立柱方管邊長
    mount: { size: 0.22, thickness: 0.05, offset: 0.024 },  // [構造] 背面掛座
  },

  // ══ 地面:HATS 雙層滑軌 ══════════════════════════════════
  floorRailZ: {           // 下層,縱向
    length: 4.61,         // [圖面]
    gauge: 0.54,          // [圖面] 兩軌中心距
    barSize: 0.05,        // [構造]
    y: 0.05,              // [構造] 軌面離地
    ties: 9,              // [構造] 枕木數量
    travel: { min: -1.85, max: 1.85, default: -0.30 },
  },
  floorRailX: {           // 上層,橫向(跟著下層台車跑)
    length: 1.60,         // [推估] ⚠️ 圖面沒標
    barSize: 0.045,       // [構造]
    y: 0.115,             // [構造]
    travel: { min: -0.55, max: 0.55, default: 0.0 },
  },

  // ══ HATS:B&K 4128 + HMS II.3 立架 ═══════════════════════
  hats: {
    totalHeight: 0.695,   // [規格] 含頭總高

    torso: {
      width: 0.410,       // [規格] 410 mm
      height: 0.460,      // [規格] 460 mm
      depth: 0.183,       // [規格] 183 mm
      gap: 0.025,         // [構造] 軀幹底離托座
    },
    neck: {
      diameter: 0.112,    // [規格] Ø112 mm
      length: 0.07,       // [構造]
    },
    head: {
      radius: 0.098,      // [推估] 由總高反推
      scaleY: 1.14,       // 頭型比例(不是規格,是外型)
      scaleZ: 1.08,
    },
    ear: {                // [構造] 耳部量測麥克風位置
      radius: 0.024, thickness: 0.018,
    },
    mouth: {              // GRAS 44AA 人工嘴
      radius: 0.032,      // [推估]
      depth: 0.05,        // [推估]
    },
    mrpMarker: { radius: 0.012 },   // MRP 紅點,純標示用

    /** 頭部前傾角:規格標「垂直 或 17°」,這裡做成連續可調 */
    headAngle: { min: -15, max: 35, default: 0, presets: [0, 17] },

    stand: {              // HMS II.3 立架
      test: 1.20,         // [規格] 標稱測試高度
      min: 0.75,          // [規格]
      max: 1.50,          // [規格]
      columnRadius: 0.055,    // [構造]
      baseSize: 0.42,         // [構造] 底板邊長
      baseThickness: 0.03,    // [構造]
    },
    mrpOffset: 0.225,     // [規格] HMS II.3 托座 → MRP 22.5 cm
    holder: {             // [構造] 托座本體
      width: 0.20, height: 0.05, depth: 0.16,
    },

    bogie: {              // [構造] 下層縱向軌上的台車
      overhang: 0.14,     // 比軌距寬出來的部分
      height: 0.06,
      depth: 0.34,
    },
    platform: {
      size: 0.80,         // [推估] 旋轉平台邊長
      height: 0.10,       // [構造]
      lift: 0.03,         // [構造] 平台底離橫移軌
    },
    turntable: {
      radius: 0.30,       // [推估]
      height: 0.05,       // [構造]
      defaultAngleDeg: 0,
    },
  },

  // ══ 桌台(升降 + 前後可移動)═════════════════════════════
  tables: {
    size: 0.80,           // [規格] 桌面 0.80 × 0.80
    thickness: 0.05,      // [構造]
    column: { topRadius: 0.075, bottomRadius: 0.095 },  // [構造] 升降柱
    base: { size: 0.46, thickness: 0.035 },             // [構造] 底盤

    items: [
      {
        key: 'tableFront', label: '前方 DUT 升降台',
        lift: { test: 0.90, min: 0.40, max: 2.30 },     // [規格] 測試 0.9,最高 2.3
        travelZ: { min: 0.55, max: 2.00, default: 1.35 },   // [推估]
      },
      {
        key: 'tableBack', label: '後方 Dixie 升降台',
        lift: { test: 1.20, min: 0.40, max: 2.30 },     // [規格] 測試 1.2,最高 2.3
        travelZ: { min: -2.00, max: -0.55, default: -0.95 },  // [推估]
      },
    ],
  },

  // ══ 天花板麥克風吊架 × 2 組 ══════════════════════════════
  micRig: {
    bridge: {
      length: 2.60,       // [推估] 橫樑長
      barSize: 0.05,      // [構造]
      y: 2.28,            // [推估] 橫樑高度
    },
    /** 膜片離地高度。[規格] 測試 0.95 / 1.25 m,範圍 0.70 ~ 1.50 m */
    height: { min: 0.70, max: 1.50, presets: [0.95, 1.25] },

    trolley: {            // [構造] 沿橫樑跑的吊車
      width: 0.16, height: 0.08, depth: 0.13,
      drop: 0.055,        // 吊車本體掛在橫樑下方多少
    },
    rod: {
      radius: 0.014,      // [構造] 伸縮吊桿
      topOffset: 0.095,   // 吊桿頂端離橫樑中心
    },
    mic: {                // GRAS 40AC / 40AF 1/2" 量測麥
      bodyRadius: 0.0135,     // [規格] 1/2 吋
      bodyLength: 0.10,       // [推估]
      preampRadius: 0.0125,   // [推估]
      preampLength: 0.12,     // [推估]
    },

    items: [
      {
        key: 'micRig1', label: '麥克風吊架 1',
        travelX: { min: -1.10, max: 1.10, default: -0.35 },   // [推估]
        travelZ: { min: -1.30, max: 1.70, default: 0.55 },    // [推估]
        heightDefault: 0.95,      // [規格]
      },
      {
        key: 'micRig2', label: '麥克風吊架 2',
        travelX: { min: -1.10, max: 1.10, default: 0.40 },    // [推估]
        travelZ: { min: -1.30, max: 1.70, default: -0.35 },   // [推估]
        heightDefault: 1.25,      // [規格]
      },
    ],
  },

  // ══ KEF LS50 Meta 主喇叭(靜態擺放)═══════════════════════
  kef: {
    width: 0.200,         // [規格] 200 mm
    height: 0.302,        // [規格] 302 mm
    depth: 0.281,         // [規格] 281 mm
    coneRadius: 0.062,    // [推估] Uni-Q 同軸單體
    standHeight: 0.30,    // [推估]
    pole: { radius: 0.03 },                                   // [構造] 立架柱
    base: { topRadius: 0.16, bottomRadius: 0.18,
            thickness: 0.025 },                               // [構造] 立架底盤
    port: { radius: 0.022 },                                  // [推估] 低音反射孔
    x: 1.30,              // [推估] ⚠️ 圖面沒標位置
    z: 0.90,              // [推估]
  },
};

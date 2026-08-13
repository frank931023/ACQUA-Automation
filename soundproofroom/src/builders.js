/**
 * 場景建構 —— 每個 build* 回傳一個 THREE.Group,尺寸全部從 CONFIG 讀。
 *
 * 可拖曳的 Group 會掛 userData.draggable = '<key>',interaction.js 靠它辨識。
 * 可動的部位一律包成子 Group,調整時只改 position/rotation,不重建幾何。
 */
import * as THREE from 'three';
import { CONFIG as C } from './config.js';

const metal = (color, rough = 0.45, metalness = 0.6) =>
  new THREE.MeshStandardMaterial({ color, roughness: rough, metalness });

const matte = (color, rough = 0.85) =>
  new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: 0.05 });

/** 一根方管 */
function bar(len, size, color, axis = 'x') {
  const geo = axis === 'x' ? new THREE.BoxGeometry(len, size, size)
            : axis === 'y' ? new THREE.BoxGeometry(size, len, size)
            :                new THREE.BoxGeometry(size, size, len);
  return new THREE.Mesh(geo, metal(color));
}

// ════════════════════════════════════════════════
// 房間
// ════════════════════════════════════════════════
export function buildRoom() {
  const g = new THREE.Group();
  const { width: W, depth: D, height: H } = C.room;

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(W, D),
    new THREE.MeshStandardMaterial({
      color: C.room.floorColor, transparent: true,
      opacity: C.room.floorOpacity, roughness: 0.95,
    })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  g.add(floor);

  const wall = new THREE.MeshStandardMaterial({
    color: C.room.color, transparent: true, opacity: C.room.opacity,
    side: THREE.DoubleSide, roughness: 0.9, depthWrite: false,
  });
  const panels = [
    [W, H, [0, H / 2, -D / 2], 0],
    [W, H, [0, H / 2, D / 2], 0],
    [D, H, [-W / 2, H / 2, 0], Math.PI / 2],
    [D, H, [W / 2, H / 2, 0], Math.PI / 2],
  ];
  for (const [w, h, pos, ry] of panels) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), wall);
    m.position.set(...pos);
    m.rotation.y = ry;
    g.add(m);
  }
  const ceil = new THREE.Mesh(new THREE.PlaneGeometry(W, D), wall);
  ceil.rotation.x = Math.PI / 2;
  ceil.position.y = H;
  g.add(ceil);

  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(W, H, D)),
    new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.32 })
  );
  edges.position.y = H / 2;
  g.add(edges);

  return g;
}

// ════════════════════════════════════════════════
// 天花板主滑軌(靜態)
// ════════════════════════════════════════════════
export function buildMainRail() {
  const g = new THREE.Group();
  const { length, z, y, barSize, color } = C.mainRail;

  const rail = bar(length, barSize, color, 'x');
  rail.position.set(0, y, z);
  g.add(rail);

  for (const sx of [-1, 1]) {
    const end = new THREE.Mesh(
      new THREE.BoxGeometry(barSize * 1.6, barSize * 2.2, barSize * 2.2), metal(0xaeb5bd));
    end.position.set(sx * length / 2, y, z);
    g.add(end);

    // 接到左右牆的橫撐
    const span = (C.room.width - length) / 2;
    const sup = bar(span, barSize * 0.8, 0xc8ced5, 'x');
    sup.position.set(sx * (length / 2 + span / 2), y, z);
    g.add(sup);
  }
  return g;
}

// ════════════════════════════════════════════════
// 喇叭陣列(可拖曳:X)
// ════════════════════════════════════════════════
export function buildSpeakerArray() {
  const g = new THREE.Group();
  g.userData.draggable = 'speakers';

  const S = C.speakerArray;

  const carriage = new THREE.Mesh(
    new THREE.BoxGeometry(0.26, 0.10, 0.16), metal(0x8f979f, 0.4, 0.75));
  g.add(carriage);

  const drop = bar(C.bracketRail.length, C.bracketRail.barSize, C.bracketRail.color, 'y');
  drop.position.y = -C.bracketRail.length / 2;
  g.add(drop);

  const arrayGroup = new THREE.Group();
  arrayGroup.name = 'arrayGroup';
  g.add(arrayGroup);

  const totalH = (S.rows - 1) * S.spacingY;
  const totalW = (S.cols - 1) * S.spacingX;

  const back = new THREE.Mesh(
    new THREE.BoxGeometry(S.frame.width, totalH + 0.36, S.frame.thickness),
    metal(S.frame.color, 0.6, 0.35));
  back.position.set(0, -totalH / 2, -S.speaker.depth / 2 - 0.03);
  arrayGroup.add(back);

  const spkGeo = new THREE.CylinderGeometry(S.speaker.radius, S.speaker.radius, S.speaker.depth, 24);
  const spkMat = metal(S.speaker.color, 0.7, 0.2);
  const coneGeo = new THREE.CircleGeometry(S.speaker.radius * 0.72, 24);
  const coneMat = matte(S.speaker.coneColor, 0.95);

  for (let r = 0; r < S.rows; r++) {
    for (let c = 0; c < S.cols; c++) {
      const x = -totalW / 2 + c * S.spacingX;
      const y = -r * S.spacingY;
      const spk = new THREE.Mesh(spkGeo, spkMat);
      spk.rotation.x = Math.PI / 2;
      spk.position.set(x, y, 0);
      spk.castShadow = true;
      arrayGroup.add(spk);
      const cone = new THREE.Mesh(coneGeo, coneMat);
      cone.position.set(x, y, S.speaker.depth / 2 + 0.002);
      arrayGroup.add(cone);
    }
  }
  return g;
}

export function setBracketDrop(group, drop) {
  const arr = group.getObjectByName('arrayGroup');
  if (arr) arr.position.y = -drop;
}

// ════════════════════════════════════════════════
// KEF LS50 Meta 主喇叭(靜態)
// ════════════════════════════════════════════════
export function buildKefSpeaker() {
  const g = new THREE.Group();
  const K = C.kef;

  // 立架
  const pole = new THREE.Mesh(
    new THREE.CylinderGeometry(0.03, 0.03, K.standHeight, 16), metal(0x9aa1a9));
  pole.position.y = K.standHeight / 2;
  g.add(pole);
  const base = new THREE.Mesh(
    new THREE.CylinderGeometry(0.16, 0.18, 0.025, 24), metal(0x8a9199));
  base.position.y = 0.012;
  g.add(base);

  // 箱體
  const box = new THREE.Mesh(
    new THREE.BoxGeometry(K.width, K.height, K.depth), matte(K.color, 0.6));
  box.position.y = K.standHeight + K.height / 2;
  box.castShadow = true;
  g.add(box);

  // 同軸單體(Uni-Q)
  const cone = new THREE.Mesh(
    new THREE.CircleGeometry(K.coneRadius, 28),
    matte(0xb9a271, 0.7));            // LS50 Meta 的金色錐盆
  cone.position.set(0, box.position.y + 0.02, K.depth / 2 + 0.002);
  g.add(cone);

  const dome = new THREE.Mesh(
    new THREE.SphereGeometry(K.coneRadius * 0.32, 16, 12), matte(0x8d7c56, 0.5));
  dome.position.set(0, cone.position.y, K.depth / 2 + 0.012);
  g.add(dome);

  // 低音反射孔
  const port = new THREE.Mesh(
    new THREE.CircleGeometry(0.022, 16), matte(0x111417, 0.9));
  port.position.set(0, box.position.y - K.height * 0.34, K.depth / 2 + 0.002);
  g.add(port);

  g.position.set(K.x, 0, K.z);
  g.rotation.y = -Math.PI / 2;        // 面朝房間中央
  return g;
}

// ════════════════════════════════════════════════
// 地面雙層滑軌(靜態)—— 下層 Z、上層 X
// ════════════════════════════════════════════════
export function buildFloorRails() {
  const g = new THREE.Group();
  const Z = C.floorRailZ;
  const X = C.floorRailX;

  // 下層:兩條縱向軌
  for (const sx of [-1, 1]) {
    const r = bar(Z.length, Z.barSize, Z.color, 'z');
    r.position.set(sx * Z.gauge / 2, Z.y, 0);
    g.add(r);
  }
  const ties = 9;
  for (let i = 0; i < ties; i++) {
    const t = bar(Z.gauge + Z.barSize, Z.barSize * 0.7, 0xc8ced5, 'x');
    t.position.set(0, Z.y - Z.barSize * 0.35, -Z.length / 2 + (i + 0.5) * (Z.length / ties));
    g.add(t);
  }

  // 上層橫移軌是跟著 HATS 台車一起前後跑的,所以做在 buildHats() 裡面,
  // 這裡不重複畫。X 只是拿來對齊高度用。
  void X;

  return g;
}

// ════════════════════════════════════════════════
// HATS(可拖曳:X + Z 兩軸)
// ════════════════════════════════════════════════
export function buildHats() {
  const g = new THREE.Group();
  g.userData.draggable = 'hats';

  const H = C.hats;
  const X = C.floorRailX;

  // ── 下層台車(在縱向軌上跑)+ 上層橫移軌 ──
  const bogie = new THREE.Mesh(
    new THREE.BoxGeometry(C.floorRailZ.gauge + 0.14, 0.06, 0.34), metal(0x9aa1a9, 0.4, 0.7));
  bogie.position.y = C.floorRailZ.y + 0.05;
  g.add(bogie);

  // 橫移滑軌(上層)—— 這一段會跟著台車前後跑
  const xr = bar(X.length, X.barSize, X.color, 'x');
  xr.position.y = X.y;
  g.add(xr);
  for (const sx of [-1, 1]) {
    const cap = new THREE.Mesh(
      new THREE.BoxGeometry(X.barSize * 1.4, X.barSize * 1.8, X.barSize * 1.8), metal(0xaeb5bd));
    cap.position.set(sx * X.length / 2, X.y, 0);
    g.add(cap);
  }

  // ── 橫移滑塊以上的東西,全部包在 carriage 裡 ──
  // 拖曳 X 時只移動這一層,下層縱向軌不動
  const carriage = new THREE.Group();
  carriage.name = 'xCarriage';
  g.add(carriage);

  // 旋轉平台
  const plat = new THREE.Mesh(
    new THREE.BoxGeometry(H.platform.size, H.platform.height, H.platform.size),
    matte(H.platform.color, 0.75));
  plat.position.y = X.y + H.platform.height / 2 + 0.03;
  plat.castShadow = true;
  carriage.add(plat);

  const turn = new THREE.Group();
  turn.name = 'turntable';
  turn.position.y = plat.position.y + H.platform.height / 2;
  carriage.add(turn);

  const disc = new THREE.Mesh(
    new THREE.CylinderGeometry(H.turntable.radius, H.turntable.radius, H.turntable.height, 32),
    metal(H.turntable.color, 0.5, 0.5));
  disc.position.y = H.turntable.height / 2;
  turn.add(disc);

  // ── HMS II.3 立架(高度可調)──
  const stand = new THREE.Group();
  stand.name = 'stand';
  stand.position.y = H.turntable.height;
  turn.add(stand);

  const sbase = new THREE.Mesh(
    new THREE.BoxGeometry(H.stand.baseSize, 0.03, H.stand.baseSize), metal(H.stand.color, 0.6, 0.3));
  sbase.position.y = 0.015;
  stand.add(sbase);

  // 立柱 —— scale.y 會被 setHatsHeight() 調整
  const column = new THREE.Mesh(
    new THREE.CylinderGeometry(H.stand.columnRadius, H.stand.columnRadius * 1.15, 1, 20),
    metal(H.stand.color, 0.5, 0.35));
  column.name = 'standColumn';
  stand.add(column);

  // 托座 + 人形,整組隨高度上下
  const body = new THREE.Group();
  body.name = 'hatsBody';
  stand.add(body);

  const holder = new THREE.Mesh(
    new THREE.BoxGeometry(0.20, 0.05, 0.16), metal(0xb6bdc4, 0.5, 0.4));
  body.add(holder);

  const skin = matte(H.torso.color, 0.85);

  // 軀幹 460(H) × 410(W) × 183(D) mm
  const torso = new THREE.Mesh(
    new THREE.BoxGeometry(H.torso.width, H.torso.height, H.torso.depth), skin);
  torso.position.y = 0.025 + H.torso.height / 2;
  torso.castShadow = true;
  body.add(torso);

  // 肩線圓角
  const shoulder = new THREE.Mesh(new THREE.SphereGeometry(H.torso.width / 2, 20, 12), skin);
  shoulder.scale.set(1, 0.34, H.torso.depth / H.torso.width);
  shoulder.position.y = torso.position.y + H.torso.height / 2;
  body.add(shoulder);

  // 脖子 Ø112 mm
  const neck = new THREE.Mesh(
    new THREE.CylinderGeometry(H.neck.diameter / 2, H.neck.diameter / 2, 0.07, 18),
    matte(H.head.color, 0.85));
  neck.position.y = shoulder.position.y + 0.035;
  body.add(neck);

  // ── 頭部(可 0° / 17° 前傾)──
  // 樞紐放在脖子頂端,旋轉才會像真的點頭
  const headPivot = new THREE.Group();
  headPivot.name = 'headPivot';
  headPivot.position.y = neck.position.y + 0.035;
  body.add(headPivot);

  const head = new THREE.Mesh(
    new THREE.SphereGeometry(H.head.radius, 24, 18), matte(H.head.color, 0.8));
  head.scale.set(1, 1.14, 1.08);
  head.position.y = H.head.radius * 1.05;
  head.castShadow = true;
  headPivot.add(head);

  const dark = matte(0x3a3f46, 0.6);

  // 兩耳(量測麥克風位置)
  for (const sx of [-1, 1]) {
    const ear = new THREE.Mesh(new THREE.CylinderGeometry(0.024, 0.024, 0.018, 16), dark);
    ear.rotation.z = Math.PI / 2;
    ear.position.set(sx * H.head.radius * 1.0, head.position.y, 0);
    headPivot.add(ear);
  }

  // GRAS 44AA 人工嘴 —— MRP(嘴部參考點)就在這
  const mouth = new THREE.Mesh(
    new THREE.CylinderGeometry(H.mouth.radius, H.mouth.radius * 1.1, H.mouth.depth, 20),
    metal(H.mouth.color, 0.5, 0.4));
  mouth.rotation.x = Math.PI / 2;
  mouth.position.set(0, head.position.y - H.head.radius * 0.42,
                     H.head.radius * 1.02 + H.mouth.depth / 2);
  mouth.name = 'mouth';
  headPivot.add(mouth);

  // MRP 標記點(小紅點,方便對位)
  const mrp = new THREE.Mesh(
    new THREE.SphereGeometry(0.012, 12, 8),
    new THREE.MeshBasicMaterial({ color: 0xf85149 }));
  mrp.name = 'mrp';
  mrp.position.set(0, mouth.position.y, mouth.position.z + H.mouth.depth / 2);
  headPivot.add(mrp);

  return g;
}

/** 設定 HATS 立架高度(MRP 離地高度,規格 0.75 ~ 1.50 m) */
export function setHatsHeight(group, mrpHeight) {
  const H = C.hats;
  const stand = group.getObjectByName('stand');
  const column = group.getObjectByName('standColumn');
  const body = group.getObjectByName('hatsBody');
  if (!stand || !column || !body) return;

  // stand 的世界高度 = 平台頂面;托座高度 = MRP 高度 - 立架托座到 MRP 的差
  const standWorldY = stand.getWorldPosition(new THREE.Vector3()).y;
  const holderLocalY = Math.max(0.05, mrpHeight - C.hats.mrpOffset - standWorldY);

  column.scale.y = holderLocalY;
  column.position.y = holderLocalY / 2;
  body.position.y = holderLocalY;
}

/** 轉盤角度(度) */
export function setHatsAngle(group, deg) {
  const t = group.getObjectByName('turntable');
  if (t) t.rotation.y = THREE.MathUtils.degToRad(deg);
}

/** 頭部前傾角(連續可調) */
export function setHeadAngle(group, deg) {
  const p = group.getObjectByName('headPivot');
  if (p) p.rotation.x = THREE.MathUtils.degToRad(deg);
}

/** 橫移(上層滑軌)—— 由 interaction 的 X 軸驅動 */
export function setHatsCross(group, x) {
  const c = group.getObjectByName('xCarriage');
  if (c) c.position.x = x;
}

// ════════════════════════════════════════════════
// 前後兩張桌台(升降台)
// ════════════════════════════════════════════════
export function buildTable(spec) {
  const g = new THREE.Group();
  const T = C.tables;

  const col = new THREE.Mesh(
    new THREE.CylinderGeometry(0.075, 0.095, 1, 18), metal(T.columnColor, 0.5, 0.35));
  col.name = 'column';
  g.add(col);

  const base = new THREE.Mesh(
    new THREE.BoxGeometry(0.46, 0.035, 0.46), metal(0xb0b7be, 0.6, 0.3));
  base.position.y = 0.017;
  g.add(base);

  const top = new THREE.Mesh(
    new THREE.BoxGeometry(T.size, T.thickness, T.size), matte(T.color, 0.7));
  top.name = 'top';
  top.castShadow = true;
  top.receiveShadow = true;
  g.add(top);

  g.userData.draggable = spec.key;
  g.position.z = spec.travelZ.default;
  setTableHeight(g, spec.lift.test);
  return g;
}

/** 設定桌面高度 */
export function setTableHeight(group, h) {
  const col = group.getObjectByName('column');
  const top = group.getObjectByName('top');
  if (!col || !top) return;
  col.scale.y = h;
  col.position.y = h / 2;
  top.position.y = h + C.tables.thickness / 2;
}

// ════════════════════════════════════════════════
// 天花板麥克風吊架(可拖曳:X + Z,高度用 slider)
// ════════════════════════════════════════════════
export function buildMicRig(item) {
  const g = new THREE.Group();
  g.userData.draggable = item.key;

  const R = C.micRig;

  // ── 橋架:沿 X 的橫樑(整組會沿 Z 移動)──
  const beam = bar(R.bridge.length, R.bridge.barSize, R.bridge.color, 'x');
  beam.position.y = R.bridge.y;
  g.add(beam);
  for (const sx of [-1, 1]) {
    const cap = new THREE.Mesh(
      new THREE.BoxGeometry(R.bridge.barSize * 1.5, R.bridge.barSize * 2, R.bridge.barSize * 2),
      metal(0xaeb5bd));
    cap.position.set(sx * R.bridge.length / 2, R.bridge.y, 0);
    g.add(cap);
  }

  // ── 吊車:沿 X 移動的那一層 ──
  const trolley = new THREE.Group();
  trolley.name = 'trolley';
  g.add(trolley);

  const tBody = new THREE.Mesh(
    new THREE.BoxGeometry(0.16, 0.08, 0.13), metal(0x8f979f, 0.4, 0.75));
  tBody.position.y = R.bridge.y - 0.055;
  trolley.add(tBody);

  // 伸縮吊桿 —— scale.y 由 setMicHeight() 調
  const rod = new THREE.Mesh(
    new THREE.CylinderGeometry(R.rod.radius, R.rod.radius, 1, 12), metal(R.rod.color));
  rod.name = 'rod';
  trolley.add(rod);

  // 麥克風本體(GRAS 1/2" 量測麥 + 前置放大器)
  const mic = new THREE.Group();
  mic.name = 'mic';
  trolley.add(mic);

  const pre = new THREE.Mesh(
    new THREE.CylinderGeometry(R.mic.preampRadius, R.mic.preampRadius, R.mic.preampLength, 16),
    metal(R.mic.color, 0.5, 0.35));
  pre.position.y = -R.mic.preampLength / 2;
  mic.add(pre);

  const body = new THREE.Mesh(
    new THREE.CylinderGeometry(R.mic.bodyRadius, R.mic.bodyRadius, R.mic.bodyLength, 16),
    metal(R.mic.color, 0.45, 0.4));
  body.position.y = -R.mic.preampLength - R.mic.bodyLength / 2;
  mic.add(body);

  // 膜片端(朝下)
  const cap = new THREE.Mesh(
    new THREE.CylinderGeometry(R.mic.bodyRadius, R.mic.bodyRadius * 0.94, 0.008, 16),
    matte(R.mic.capsuleColor, 0.5));
  cap.position.y = -R.mic.preampLength - R.mic.bodyLength - 0.004;
  mic.add(cap);

  g.position.z = item.travelZ.default;
  setMicCross(g, item.travelX.default);
  setMicHeight(g, item.heightDefault);
  return g;
}

/**
 * 設定麥克風高度(膜片離地高度,規格 0.70 ~ 1.50 m)
 * 吊桿長度 = 橋架高度 - 目標高度
 */
export function setMicHeight(group, h) {
  const R = C.micRig;
  const trolley = group.getObjectByName('trolley');
  const rod = group.getObjectByName('rod');
  const mic = group.getObjectByName('mic');
  if (!trolley || !rod || !mic) return;

  const micLen = R.mic.preampLength + R.mic.bodyLength + 0.008;
  const rodTop = R.bridge.y - 0.095;
  const rodLen = Math.max(0.05, rodTop - h - micLen);

  rod.scale.y = rodLen;
  rod.position.y = rodTop - rodLen / 2;
  mic.position.y = rodTop - rodLen;
}

/** 吊車橫移 */
export function setMicCross(group, x) {
  const t = group.getObjectByName('trolley');
  if (t) t.position.x = x;
}

// ════════════════════════════════════════════════
// 大螢幕(可拖曳:Z;高度用 slider)
//
// 位置在喇叭陣列的正對面 —— 受測裝置面向它,喇叭在背後。
// ════════════════════════════════════════════════
export function buildScreen() {
  const g = new THREE.Group();
  g.userData.draggable = 'screen';

  const S = C.screen;

  // 底座 + 立柱(立柱高度由 setScreenLift 調整)
  const base = new THREE.Mesh(
    new THREE.BoxGeometry(0.62, 0.04, 0.42), metal(0x9aa1a9, 0.6, 0.35));
  base.position.y = 0.02;
  g.add(base);

  for (const sx of [-1, 1]) {
    const foot = new THREE.Mesh(
      new THREE.BoxGeometry(0.07, 0.05, 0.40), metal(0x8a9199, 0.6, 0.3));
    foot.position.set(sx * 0.24, 0.025, 0);
    g.add(foot);
  }

  const col = new THREE.Mesh(
    new THREE.BoxGeometry(0.10, 1, 0.10), metal(S.standColor, 0.5, 0.35));
  col.name = 'screenColumn';
  g.add(col);

  // 螢幕本體(整片隨立柱升降)
  const panelGroup = new THREE.Group();
  panelGroup.name = 'screenPanel';
  g.add(panelGroup);

  // 外框
  const frame = new THREE.Mesh(
    new THREE.BoxGeometry(S.width + S.bezel * 2, S.height + S.bezel * 2, S.thickness),
    matte(S.frameColor, 0.55));
  frame.castShadow = true;
  panelGroup.add(frame);

  // 顯示面(朝 -Z,也就是面向房間中央與喇叭陣列)
  const panel = new THREE.Mesh(
    new THREE.PlaneGeometry(S.width, S.height),
    new THREE.MeshStandardMaterial({
      color: S.panelColor, roughness: 0.28, metalness: 0.1,
      emissive: 0x0a1622, emissiveIntensity: 0.55,   // 一點自發光,看起來像開著
    }));
  panel.position.z = -S.thickness / 2 - 0.002;
  panel.rotation.y = Math.PI;
  panelGroup.add(panel);

  // 背面支架
  const mount = new THREE.Mesh(
    new THREE.BoxGeometry(0.22, 0.22, 0.05), metal(0x6f767e, 0.6, 0.4));
  mount.position.z = S.thickness / 2 + 0.024;
  panelGroup.add(mount);

  g.position.z = S.travelZ.default;
  setScreenLift(g, S.lift.default);
  return g;
}

/** 螢幕中心離地高度 */
export function setScreenLift(group, h) {
  const col = group.getObjectByName('screenColumn');
  const panel = group.getObjectByName('screenPanel');
  if (!col || !panel) return;
  const colH = Math.max(0.1, h - C.screen.height / 2 + 0.05);
  col.scale.y = colH;
  col.position.y = colH / 2;
  panel.position.y = h;
}

// ════════════════════════════════════════════════
// 燈光
// ════════════════════════════════════════════════
export function buildLights() {
  const g = new THREE.Group();
  g.add(new THREE.HemisphereLight(0xffffff, 0x60666e, 0.85));

  const key = new THREE.DirectionalLight(0xffffff, 1.1);
  key.position.set(3.5, 4.5, 3.0);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.near = 0.5;
  key.shadow.camera.far = 20;
  const s = 4;
  Object.assign(key.shadow.camera, { left: -s, right: s, top: s, bottom: -s });
  g.add(key);

  const fill = new THREE.DirectionalLight(0xffffff, 0.35);
  fill.position.set(-3, 2.5, -2.5);
  g.add(fill);
  return g;
}

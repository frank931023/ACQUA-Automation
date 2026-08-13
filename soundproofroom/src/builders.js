/**
 * 場景建構 —— 每個 build* 函式回傳一個 THREE.Group,尺寸全部從 CONFIG 讀。
 *
 * 設計原則:
 *   ・可移動的物件都包在自己的 Group 裡,移動時只動 Group 的 position,
 *     裡面的子物件用相對座標,改尺寸不用重算位置。
 *   ・可拖曳的 Group 會掛上 userData.draggable = 'speakers' | 'hats',
 *     interaction.js 靠這個判斷抓到的是哪一個。
 */
import * as THREE from 'three';
import { CONFIG as C } from './config.js';

/** 半透明材質(牆面用) */
function wallMaterial(color, opacity) {
  return new THREE.MeshStandardMaterial({
    color,
    transparent: true,
    opacity,
    side: THREE.DoubleSide,
    roughness: 0.9,
    metalness: 0.0,
    depthWrite: false,      // 半透明疊在一起時才不會互相蓋掉
  });
}

function metalMaterial(color, { rough = 0.45, metal = 0.6 } = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: metal });
}

/** 一根方管 —— 滑軌、支架都用它組 */
function bar(len, size, color, axis = 'x') {
  const geo = axis === 'x' ? new THREE.BoxGeometry(len, size, size)
            : axis === 'y' ? new THREE.BoxGeometry(size, len, size)
            :                new THREE.BoxGeometry(size, size, len);
  return new THREE.Mesh(geo, metalMaterial(color));
}

// ────────────────────────────────────────────────
// 房間
// ────────────────────────────────────────────────
export function buildRoom() {
  const g = new THREE.Group();
  g.name = 'room';
  const { width: W, depth: D, height: H } = C.room;

  // 地板
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(W, D),
    new THREE.MeshStandardMaterial({
      color: C.room.floorColor,
      transparent: true,
      opacity: C.room.floorOpacity,
      roughness: 0.95,
    })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  g.add(floor);

  // 四面牆 + 天花板(半透明,方便從外面看進來)
  const wall = wallMaterial(C.room.color, C.room.opacity);
  const panels = [
    // [寬, 高, 位置, 旋轉Y]
    [W, H, [0, H / 2, -D / 2], 0],            // 後牆
    [W, H, [0, H / 2, D / 2], 0],             // 前牆
    [D, H, [-W / 2, H / 2, 0], Math.PI / 2],  // 左牆
    [D, H, [W / 2, H / 2, 0], Math.PI / 2],   // 右牆
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

  // 邊框線 —— 半透明牆面單看不出立體感,加上輪廓線清楚很多
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(W, H, D)),
    new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.35 })
  );
  edges.position.y = H / 2;
  g.add(edges);

  return g;
}

// ────────────────────────────────────────────────
// 天花板主滑軌(靜態)
// ────────────────────────────────────────────────
export function buildMainRail() {
  const g = new THREE.Group();
  g.name = 'mainRail';
  const { length, z, y, barSize, color } = C.mainRail;

  const rail = bar(length, barSize, color, 'x');
  rail.position.set(0, y, z);
  g.add(rail);

  // 兩端固定座
  for (const sx of [-1, 1]) {
    const end = new THREE.Mesh(
      new THREE.BoxGeometry(barSize * 1.6, barSize * 2.2, barSize * 2.2),
      metalMaterial(0xaeb5bd)
    );
    end.position.set(sx * length / 2, y, z);
    g.add(end);
  }

  // 兩條橫向支撐(接到左右牆)
  for (const sx of [-1, 1]) {
    const span = (C.room.width - length) / 2;
    const sup = bar(span, barSize * 0.8, 0xc8ced5, 'x');
    sup.position.set(sx * (length / 2 + span / 2), y, z);
    g.add(sup);
  }

  return g;
}

// ────────────────────────────────────────────────
// 喇叭陣列(可拖曳:沿 X)
// ────────────────────────────────────────────────
export function buildSpeakerArray() {
  const g = new THREE.Group();
  g.name = 'speakerArray';
  g.userData.draggable = 'speakers';
  g.userData.axis = 'x';

  const S = C.speakerArray;
  const { barSize: bSize, color: bColor } = C.bracketRail;

  // 掛車(在主滑軌上滑動的滑塊)
  const carriage = new THREE.Mesh(
    new THREE.BoxGeometry(0.26, 0.10, 0.16),
    metalMaterial(0x8f979f, { metal: 0.75 })
  );
  carriage.position.y = 0;
  g.add(carriage);

  // 支架滑軌(垂直向下,長度 = bracketRail.length)
  const drop = bar(C.bracketRail.length, bSize, bColor, 'y');
  drop.position.y = -C.bracketRail.length / 2;
  drop.name = 'bracketRail';
  g.add(drop);

  // ── 喇叭框架 + 8 顆喇叭,整組掛在 bracket 底下 ──
  // 這一層的 y 會被 setBracketDrop() 調整
  const arrayGroup = new THREE.Group();
  arrayGroup.name = 'arrayGroup';
  g.add(arrayGroup);

  const totalH = (S.rows - 1) * S.spacingY;
  const totalW = (S.cols - 1) * S.spacingX;

  // 背板
  const back = new THREE.Mesh(
    new THREE.BoxGeometry(S.frame.width, totalH + 0.36, S.frame.thickness),
    metalMaterial(S.frame.color, { rough: 0.6, metal: 0.35 })
  );
  back.position.set(0, -totalH / 2, -S.speaker.depth / 2 - 0.03);
  arrayGroup.add(back);

  const spkGeo = new THREE.CylinderGeometry(
    S.speaker.radius, S.speaker.radius, S.speaker.depth, 24);
  const spkMat = metalMaterial(S.speaker.color, { rough: 0.7, metal: 0.2 });
  const coneGeo = new THREE.CircleGeometry(S.speaker.radius * 0.72, 24);
  const coneMat = new THREE.MeshStandardMaterial({
    color: S.speaker.coneColor, roughness: 0.95,
  });

  for (let r = 0; r < S.rows; r++) {
    for (let c = 0; c < S.cols; c++) {
      const x = -totalW / 2 + c * S.spacingX;
      const y = -r * S.spacingY;

      const spk = new THREE.Mesh(spkGeo, spkMat);
      spk.rotation.x = Math.PI / 2;          // 圓柱預設沿 Y,轉成朝 +Z
      spk.position.set(x, y, 0);
      spk.castShadow = true;
      arrayGroup.add(spk);

      // 振膜(朝房間內側 +Z)
      const cone = new THREE.Mesh(coneGeo, coneMat);
      cone.position.set(x, y, S.speaker.depth / 2 + 0.002);
      arrayGroup.add(cone);
    }
  }

  return g;
}

/**
 * 設定喇叭陣列的下降量(支架滑軌的可調節範圍 0.50~0.80)
 * @param {THREE.Group} speakerGroup buildSpeakerArray() 回傳的 Group
 * @param {number} drop 下降量(公尺)
 */
export function setBracketDrop(speakerGroup, drop) {
  const rail = speakerGroup.getObjectByName('bracketRail');
  const arr = speakerGroup.getObjectByName('arrayGroup');
  if (!rail || !arr) return;
  // 滑軌本身長度固定,只是喇叭組沿著它上下
  arr.position.y = -drop;
}

// ────────────────────────────────────────────────
// 地面滑軌(靜態)
// ────────────────────────────────────────────────
export function buildFloorRail() {
  const g = new THREE.Group();
  g.name = 'floorRail';
  const { length, gauge, barSize, y, color } = C.floorRail;

  for (const sx of [-1, 1]) {
    const r = bar(length, barSize, color, 'z');
    r.position.set(sx * gauge / 2, y, 0);
    g.add(r);
  }

  // 每隔一段加一根枕木,看起來像真的軌道
  const ties = 7;
  for (let i = 0; i < ties; i++) {
    const t = bar(gauge + barSize, barSize * 0.7, 0xc8ced5, 'x');
    t.position.set(0, y - barSize * 0.35, -length / 2 + (i + 0.5) * (length / ties));
    g.add(t);
  }

  return g;
}

// ────────────────────────────────────────────────
// HATS + 旋轉平台(可拖曳:沿 Z)
// ────────────────────────────────────────────────
export function buildHats() {
  const g = new THREE.Group();
  g.name = 'hatsPlatform';
  g.userData.draggable = 'hats';
  g.userData.axis = 'z';

  const H = C.hats;

  // 底座平台
  const plat = new THREE.Mesh(
    new THREE.BoxGeometry(H.platform.size, H.platform.height, H.platform.size),
    metalMaterial(H.platform.color, { rough: 0.75, metal: 0.15 })
  );
  plat.position.y = C.floorRail.y + H.platform.height / 2;
  plat.castShadow = true;
  g.add(plat);

  // 轉盤(可繞 Y 旋轉的那一層)
  const turn = new THREE.Group();
  turn.name = 'turntable';
  turn.position.y = plat.position.y + H.platform.height / 2;
  g.add(turn);

  const disc = new THREE.Mesh(
    new THREE.CylinderGeometry(H.turntable.radius, H.turntable.radius,
                               H.turntable.height, 32),
    metalMaterial(H.turntable.color, { metal: 0.5 })
  );
  disc.position.y = H.turntable.height / 2;
  turn.add(disc);

  // 座柱
  const ped = new THREE.Mesh(
    new THREE.CylinderGeometry(0.10, 0.13, H.pedestalHeight, 20),
    metalMaterial(0xd0d6dc, { metal: 0.3 })
  );
  ped.position.y = H.turntable.height + H.pedestalHeight / 2;
  turn.add(ped);

  const bodyMat = new THREE.MeshStandardMaterial({
    color: H.torso.color, roughness: 0.85, metalness: 0.05,
  });

  // 軀幹
  const torso = new THREE.Mesh(
    new THREE.BoxGeometry(H.torso.width, H.torso.height, H.torso.depth),
    bodyMat
  );
  torso.position.y = H.turntable.height + H.pedestalHeight + H.torso.height / 2;
  torso.castShadow = true;
  turn.add(torso);

  // 肩膀(用縮扁的球做圓角)
  const shoulder = new THREE.Mesh(new THREE.SphereGeometry(H.torso.width / 2, 20, 12), bodyMat);
  shoulder.scale.set(1, 0.42, H.torso.depth / H.torso.width);
  shoulder.position.y = torso.position.y + H.torso.height / 2;
  turn.add(shoulder);

  // 脖子
  const neck = new THREE.Mesh(
    new THREE.CylinderGeometry(0.055, 0.065, 0.09, 16),
    new THREE.MeshStandardMaterial({ color: H.head.color, roughness: 0.85 })
  );
  neck.position.y = shoulder.position.y + 0.05;
  turn.add(neck);

  // 頭
  const head = new THREE.Mesh(
    new THREE.SphereGeometry(H.head.radius, 24, 18),
    new THREE.MeshStandardMaterial({ color: H.head.color, roughness: 0.8 })
  );
  head.scale.set(1, 1.12, 1.06);
  head.position.y = neck.position.y + 0.05 + H.head.radius * 1.05;
  head.castShadow = true;
  turn.add(head);

  // 兩耳 —— HATS 的量測麥克風就在耳朵位置,標成深色比較好認
  const earMat = new THREE.MeshStandardMaterial({ color: 0x3a3f46, roughness: 0.6 });
  for (const sx of [-1, 1]) {
    const ear = new THREE.Mesh(new THREE.CylinderGeometry(0.026, 0.026, 0.02, 16), earMat);
    ear.rotation.z = Math.PI / 2;
    ear.position.set(sx * H.head.radius * 1.0, head.position.y, 0);
    turn.add(ear);
  }

  // 鼻子 —— 用來一眼看出人頭朝哪個方向
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.028, 0.06, 12), earMat);
  nose.rotation.x = Math.PI / 2;
  nose.position.set(0, head.position.y - 0.01, H.head.radius * 1.02);
  turn.add(nose);

  return g;
}

/** 設定 HATS 轉盤角度(度) */
export function setHatsAngle(hatsGroup, deg) {
  const turn = hatsGroup.getObjectByName('turntable');
  if (turn) turn.rotation.y = THREE.MathUtils.degToRad(deg);
}

// ────────────────────────────────────────────────
// 天花板吊掛麥克風(靜態裝飾)
// ────────────────────────────────────────────────
export function buildCeilingMics() {
  const g = new THREE.Group();
  g.name = 'ceilingMics';
  const M = C.mic;

  for (const p of C.ceilingMics) {
    const mic = new THREE.Group();

    const rod = new THREE.Mesh(
      new THREE.CylinderGeometry(0.012, 0.012, 0.22, 10),
      metalMaterial(0xbfc6cd)
    );
    rod.position.y = C.room.height - 0.11;
    mic.add(rod);

    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(M.bodyRadiusTop, M.bodyRadiusBottom, M.bodyHeight, 20),
      metalMaterial(M.color, { rough: 0.6, metal: 0.25 })
    );
    body.position.y = C.room.height - 0.22 - M.bodyHeight / 2;
    mic.add(body);

    const cap = new THREE.Mesh(
      new THREE.SphereGeometry(M.capsuleRadius, 16, 12),
      new THREE.MeshStandardMaterial({ color: M.capsuleColor, roughness: 0.5 })
    );
    cap.position.y = body.position.y - M.bodyHeight / 2;
    mic.add(cap);

    mic.position.set(p.x, 0, p.z);
    g.add(mic);
  }
  return g;
}

// ────────────────────────────────────────────────
// 燈光
// ────────────────────────────────────────────────
export function buildLights() {
  const g = new THREE.Group();
  g.add(new THREE.HemisphereLight(0xffffff, 0x60666e, 0.85));

  const key = new THREE.DirectionalLight(0xffffff, 1.15);
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

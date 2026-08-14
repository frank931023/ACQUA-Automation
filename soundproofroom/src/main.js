/**
 * 聲學測試室 3D 視覺化 —— 進入點
 *
 * 側邊欄是**依 config 動態生成**的:物件多了之後,再用靜態 HTML 維護
 * 二十幾個 slider 很容易漏。要加新物件只要在 PANEL 的定義裡多一筆。
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

import { CONFIG as C } from './config.js';
import {
  buildRoom, buildMainRail, buildSpeakerArray, setBracketDrop, buildKefSpeaker,
  buildFloorRails, buildHats, setHatsAngle, setHatsHeight, setHeadAngle, setHatsCross,
  buildTable, setTableHeight, buildMicRig, setMicHeight, setMicCross,
  buildScreen, setScreenLift, buildLights,
} from './builders.js';
import { createInteraction } from './interaction.js';

const $ = (s) => document.querySelector(s);

// ── 三件套 ──────────────────────────────────────
const container = $('#viewport');
const scene = new THREE.Scene();
scene.background = new THREE.Color(C.background);

const camera = new THREE.PerspectiveCamera(
  C.camera.fov, container.clientWidth / container.clientHeight, C.camera.near, C.camera.far);
camera.position.set(...C.camera.position);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(...C.camera.target);
controls.maxPolarAngle = Math.PI * 0.495;
controls.minDistance = C.camera.minDistance;
controls.maxDistance = C.camera.maxDistance;

// ── 場景 ────────────────────────────────────────
scene.add(buildLights(), buildRoom(), buildMainRail(), buildFloorRails(), buildKefSpeaker());

const speakers = buildSpeakerArray();
speakers.position.set(C.mainRail.travel.default, C.mainRail.y, C.mainRail.z);
scene.add(speakers);

const hats = buildHats();
scene.add(hats);

const screen = buildScreen();
scene.add(screen);

const tables = C.tables.items.map((item) => {
  const g = buildTable(item);
  scene.add(g);
  return { item, group: g };
});

const micRigs = C.micRig.items.map((item) => {
  const g = buildMicRig(item);
  scene.add(g);
  return { item, group: g };
});

const grid = new THREE.GridHelper(
  Math.max(C.room.width, C.room.depth), C.grid.divisions, C.grid.color1, C.grid.color2);
grid.position.y = 0.002;
grid.material.transparent = true;
grid.material.opacity = C.grid.opacity;
scene.add(grid);

// ── 互動:所有可拖曳目標 ────────────────────────
const dragTargets = [
  { key: 'speakers', group: speakers, planeY: C.mainRail.y,
    axes: { x: { ...C.mainRail.travel } } },

  // HATS:Z 走下層軌(整組),X 走上層橫移軌(只動子層)
  { key: 'hats', group: hats, planeY: C.floorRailX.y,
    axes: { x: { ...C.floorRailX.travel }, z: { ...C.floorRailZ.travel } },
    apply: { x: setHatsCross } },

  { key: 'screen', group: screen, planeY: 0.4,
    axes: { z: { ...C.screen.travelZ } } },

  ...tables.map(({ item, group }) => ({
    key: item.key, group, planeY: 0.4,
    axes: { z: { ...item.travelZ } },
  })),

  ...micRigs.map(({ item, group }) => ({
    key: item.key, group, planeY: C.micRig.bridge.y,
    axes: { x: { ...item.travelX }, z: { ...item.travelZ } },
    apply: { x: setMicCross },
  })),
];

const interaction = createInteraction({
  renderer, camera, controls, targets: dragTargets,
  onChange: (key, axis, value, source) => {
    const s = sliders[`${key}.${axis}`];
    if (!s) return;
    if (source !== 'slider') s.el.value = value;
    s.out.textContent = s.format(value);
  },
});

// ── 側邊欄:依定義動態生成 ──────────────────────
const fmtPos = (v) => `${v >= 0 ? '+' : ''}${v.toFixed(2)} m`;
const fmtLen = (v) => `${v.toFixed(2)} m`;
const fmtDeg = (v) => `${v.toFixed(0)}°`;

const sliders = {};    // 'key.axis' 或自訂 id → { el, out, format }

/**
 * 面板定義。每個 group 是一個區塊,items 是控制項。
 *   type 'drag'   → 綁到 interaction 的某個軸(拖曳會回寫)
 *   type 'value'  → 純 slider,直接呼叫 setter
 *   type 'preset' → 一排快捷按鈕,套用到指定的 slider
 */
const PANEL = [
  {
    title: '喇叭陣列(2 × 4)',
    items: [
      { type: 'drag', key: 'speakers', axis: 'x', label: '主滑軌位置 X',
        range: C.mainRail.travel, format: fmtPos,
        hint: '主滑軌長 2.00 m ・ 房間寬度中央' },
      { type: 'value', id: 'sp-drop', label: '支架下降量',
        range: { min: C.bracketRail.min, max: C.bracketRail.max, default: C.bracketRail.default },
        onInput: (v) => setBracketDrop(speakers, v),
        hint: '支架滑軌長 0.80 m ・ 可調 0.50 ~ 0.80 m' },
    ],
  },
  {
    title: '大螢幕(喇叭對面)',
    items: [
      { type: 'drag', key: 'screen', axis: 'z', label: '前後位置 Z',
        range: C.screen.travelZ, format: fmtPos },
      { type: 'value', id: 'screen-lift', label: '螢幕中心高度',
        range: C.screen.lift, onInput: (v) => setScreenLift(screen, v),
        hint: `面板 ${C.screen.width} × ${C.screen.height} m(推估)` },
    ],
  },
  {
    title: 'HATS(B&K 4128)',
    items: [
      { type: 'drag', key: 'hats', axis: 'z', label: '縱向位置 Z(下層軌)',
        range: C.floorRailZ.travel, format: fmtPos, hint: '縱向滑軌長 4.61 m' },
      { type: 'drag', key: 'hats', axis: 'x', label: '橫向位置 X(上層軌)',
        range: C.floorRailX.travel, format: fmtPos, hint: '橫移滑軌長 1.60 m(推估)' },
      { type: 'value', id: 'hats-h', label: 'MRP 高度',
        range: { ...C.hats.stand, default: C.hats.stand.test },
        onInput: (v) => setHatsHeight(hats, v),
        hint: 'HMS II.3 立架 ・ 標稱 1.20 m ・ 0.75 ~ 1.50 m' },
      { type: 'value', id: 'hats-rot', label: '轉盤角度', step: 1,
        range: { min: -180, max: 180, default: C.hats.turntable.defaultAngleDeg },
        format: fmtDeg, onInput: (v) => setHatsAngle(hats, v) },
      { type: 'value', id: 'head-ang', label: '頭部前傾角', step: 0.5,
        range: C.hats.headAngle, format: (v) => `${v.toFixed(1)}°`,
        onInput: (v) => setHeadAngle(hats, v),
        hint: '規格標「垂直 或 17°」,這裡做成連續可調' },
      { type: 'preset', target: 'head-ang', values: C.hats.headAngle.presets,
        format: (v) => `${v}°` },
    ],
  },
  {
    title: '桌台(升降 + 前後)',
    items: tables.flatMap(({ item }) => [
      { type: 'drag', key: item.key, axis: 'z', label: `${item.label} — 前後 Z`,
        range: item.travelZ, format: fmtPos },
      { type: 'value', id: `${item.key}-lift`, label: `${item.label} — 高度`,
        range: { ...item.lift, default: item.lift.test },
        onInput: (v) => setTableHeight(
          tables.find((t) => t.item.key === item.key).group, v),
        hint: `測試 ${item.lift.test} m ・ 最高 ${item.lift.max} m` },
    ]),
  },
  {
    title: '天花板麥克風吊架 × 2',
    items: micRigs.flatMap(({ item }) => [
      { type: 'drag', key: item.key, axis: 'z', label: `${item.label} — 縱向 Z`,
        range: item.travelZ, format: fmtPos },
      { type: 'drag', key: item.key, axis: 'x', label: `${item.label} — 橫向 X`,
        range: item.travelX, format: fmtPos },
      { type: 'value', id: `${item.key}-h`, label: `${item.label} — 高度 Y`,
        range: { ...C.micRig.height, default: item.heightDefault },
        onInput: (v) => setMicHeight(
          micRigs.find((m) => m.item.key === item.key).group, v),
        hint: 'GRAS 40AC / 40AF ・ 0.70 ~ 1.50 m' },
      { type: 'preset', target: `${item.key}-h`, values: C.micRig.height.presets,
        format: (v) => `${v} m` },
    ]),
  },
];

function buildPanel() {
  const panel = $('#panel');
  panel.innerHTML = `<h1>聲學測試室</h1>
    <div class="sub">房間 ${C.room.width} × ${C.room.depth} × ${C.room.height} m</div>`;

  for (const grp of PANEL) {
    const box = document.createElement('div');
    box.className = 'group';
    box.innerHTML = `<h2>${grp.title}</h2>`;

    for (const it of grp.items) {
      if (it.type === 'preset') {
        const row = document.createElement('div');
        row.className = 'views';
        row.style.marginTop = '-6px';
        row.style.marginBottom = '13px';
        for (const v of it.values) {
          const b = document.createElement('button');
          b.textContent = it.format ? it.format(v) : v;
          b.onclick = () => sliders[it.target]?.set(v);
          row.appendChild(b);
        }
        box.appendChild(row);
        continue;
      }

      const id = it.type === 'drag' ? `${it.key}.${it.axis}` : it.id;
      const wrap = document.createElement('div');
      wrap.className = 'ctl';
      wrap.innerHTML = `
        <div class="row"><span class="name">${it.label}</span><span class="val">—</span></div>
        <input type="range">
        ${it.hint ? `<div class="lim">${it.hint}</div>` : ''}`;
      box.appendChild(wrap);

      const el = wrap.querySelector('input');
      const out = wrap.querySelector('.val');
      const format = it.format || fmtLen;
      const r = it.range;

      el.min = r.min; el.max = r.max; el.step = it.step ?? 0.01;
      el.value = r.default ?? r.min;

      const apply = () => {
        const v = parseFloat(el.value);
        out.textContent = format(v);
        if (it.type === 'drag') interaction.set(it.key, it.axis, v);
        else it.onInput(v);
      };
      el.addEventListener('input', apply);

      sliders[id] = { el, out, format, set: (v) => { el.value = v; apply(); } };
      apply();
    }
    panel.appendChild(box);
  }

  // 視角 + 重設
  const v = document.createElement('div');
  v.className = 'group';
  v.innerHTML = `<h2>視角</h2>
    <div class="views">
      <button data-view="iso">等角</button>
      <button data-view="top">俯視</button>
      <button data-view="front">正視</button>
      <button data-view="side">側視</button>
    </div>
    <button id="reset" class="wide">重設全部</button>
    <div class="meta" style="margin-top:16px">
      尺寸常數集中在 <code>src/config.js</code><br>
      <a href="/" style="color:var(--accent)">← 回首頁</a>
    </div>`;
  panel.appendChild(v);

  const VIEWS = {
    iso: { pos: C.camera.position, target: C.camera.target },
    top: { pos: [0, 9.5, 0.01], target: [0, 0, 0] },
    front: { pos: [0, 1.3, 8.4], target: [0, 1.1, 0] },
    side: { pos: [8.4, 1.5, 0], target: [0, 1.1, 0] },
  };
  v.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => {
    const p = VIEWS[b.dataset.view];
    camera.position.set(...p.pos);
    controls.target.set(...p.target);
  }));
  v.querySelector('#reset').addEventListener('click', () => location.reload());
}

buildPanel();

// ── 迴圈 ────────────────────────────────────────
function onResize() {
  const w = container.clientWidth, h = container.clientHeight;
  if (!w || !h) return;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}
window.addEventListener('resize', onResize);
new ResizeObserver(onResize).observe(container);

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});

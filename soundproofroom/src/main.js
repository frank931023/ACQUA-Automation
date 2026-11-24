/**
 * 聲學測試室 3D 視覺化 —— 進入點
 *
 * 這一頁只做一件事:**設計擺位(setup)並存起來**。
 * 拉桿與拖曳直接改 3D,存成擺位;不會碰到任何機構,愛怎麼試都行。
 *
 * 看實機位置、手動推機構這類即時操作**不在這個專案** —— 那是天車控制中心
 * (MCC,pc-led-controller)的工作。這裡存好的擺位,由測試執行時的
 * SetupCoordinator(acqua/setupcoord.py)依 Setup 標籤自動套用。
 *
 * 側邊欄是依 PANEL 宣告動態生成的:物件多了之後,再用靜態 HTML 維護
 * 二十幾個拉桿很容易漏。要加新物件只要在 PANEL 裡多一筆。
 *
 * ⚠️ 每個控制項的 id 是**跨三處的契約**:
 *      soundproofroom/src/main.js   這裡的 PANEL
 *      acqua/crane.py               AXES(對應到哪台 Pi 的哪根軸)
 *      setups/*.json                存好的擺位的鍵
 *    改 id 會讓存好的擺位對不上。要改就得寫搬移。
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

import { CONFIG as C } from './config.js';
import {
  buildRoom, buildSpeakerRail, buildSpeakerArray, setArrayLift,
  buildFloorRails, buildHats, setHatsAngle, setHatsHeight, setHeadAngle, setHatsCross,
  buildTable, setTableHeight, buildMicRig, setMicHeight, setMicCross,
  buildScreen, setScreenLift, buildLights,
} from './builders.js';
import { createInteraction } from './interaction.js';
import { fmt, esc, toast, jsonFetch } from './ui.js';
import { listSetups, saveCurrent, applyToScene } from './setups.js';

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

const controls3d = new OrbitControls(camera, renderer.domElement);
controls3d.enableDamping = true;
controls3d.dampingFactor = 0.08;
controls3d.target.set(...C.camera.target);
controls3d.maxPolarAngle = Math.PI * 0.495;
controls3d.minDistance = C.camera.minDistance;
controls3d.maxDistance = C.camera.maxDistance;

// ── 場景 ────────────────────────────────────────
scene.add(buildLights(), buildRoom(), buildSpeakerRail(), buildFloorRails());

const speakers = buildSpeakerArray();
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

const tableGroup = (key) => tables.find((t) => t.item.key === key).group;
const micGroup = (key) => micRigs.find((m) => m.item.key === key).group;

// ── 互動:所有可拖曳目標 ────────────────────────
const dragTargets = [
  { key: 'speakers', group: speakers, planeY: C.speakerStand.lift.default,
    axes: { x: { ...C.speakerRail.travel } } },

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
  renderer, camera, controls: controls3d, targets: dragTargets,
  onChange: (key, axis, value, source) => {
    const c = controls[`${key}.${axis}`];
    if (!c) return;
    if (source !== 'slider') c.el.value = value;
    c.out.textContent = c.format(value);
  },
});

// ══════════════════════════════════════════════════
//  控制項宣告
// ══════════════════════════════════════════════════
//
//   drag  → 這根軸也能用滑鼠在 3D 裡拖(套用經過 interaction)
//   apply → 只有拉桿,直接呼叫 builders 的 setter
//
// id 一律 `<物件>.<軸>`,與 acqua/crane.py 的 AXES 同名(見檔頭的警告)。
const PANEL = [
  {
    title: 'Speaker array (2 x 4, floor standing)',
    items: [
      { id: 'speakers.x', label: 'Floor traverse X', unit: 'm',
        range: C.speakerRail.travel, format: fmt.pos,
        drag: { key: 'speakers', axis: 'x' },
        hint: 'Traverse rail 2.00 m - floor standing, not ceiling mounted' },
      { id: 'speakers.lift', label: 'Array centre height', unit: 'm',
        range: C.speakerStand.lift,
        apply: (v) => setArrayLift(speakers, v),
        hint: `Column travel ${C.speakerStand.lift.min} - ${C.speakerStand.lift.max} m` },
    ],
  },
  {
    title: 'Large screen (facing the speakers)',
    items: [
      { id: 'screen.z', label: 'Depth Z', unit: 'm',
        range: C.screen.travelZ, format: fmt.pos,
        drag: { key: 'screen', axis: 'z' } },
      { id: 'screen.lift', label: 'Screen centre height', unit: 'm',
        range: C.screen.lift, apply: (v) => setScreenLift(screen, v),
        hint: `Panel ${C.screen.width} x ${C.screen.height} m (estimated)` },
    ],
  },
  {
    title: 'HATS(B&K 4128)',
    items: [
      { id: 'hats.z', label: 'Depth Z (lower rail)', unit: 'm',
        range: C.floorRailZ.travel, format: fmt.pos,
        drag: { key: 'hats', axis: 'z' }, hint: 'Depth rail 4.61 m' },
      { id: 'hats.x', label: 'Lateral X (upper rail)', unit: 'm',
        range: C.floorRailX.travel, format: fmt.pos,
        drag: { key: 'hats', axis: 'x' }, hint: 'Lateral rail 1.60 m (estimated)' },
      { id: 'hats.mrp', label: 'MRP height', unit: 'm',
        range: { ...C.hats.stand, default: C.hats.stand.test },
        apply: (v) => setHatsHeight(hats, v),
        hint: 'HMS II.3 stand - nominal 1.20 m - range 0.75 to 1.50 m' },
      { id: 'hats.rot', label: 'Turntable angle', unit: 'deg', step: 1,
        range: { min: -180, max: 180, default: C.hats.turntable.defaultAngleDeg },
        apply: (v) => setHatsAngle(hats, v) },
      { id: 'hats.head', label: 'Head pitch', unit: 'deg', step: 0.5,
        range: C.hats.headAngle,
        apply: (v) => setHeadAngle(hats, v),
        hint: 'Spec says vertical or 17 deg - continuous here' },
      { type: 'preset', target: 'hats.head', values: C.hats.headAngle.presets,
        format: (v) => `${v}°` },
    ],
  },
  {
    title: 'Tables (lift + depth)',
    items: tables.flatMap(({ item }) => [
      { id: `${item.key}.z`, label: `${item.label} - depth Z`, unit: 'm',
        range: item.travelZ, format: fmt.pos,
        drag: { key: item.key, axis: 'z' } },
      { id: `${item.key}.lift`, label: `${item.label} - height`, unit: 'm',
        range: { ...item.lift, default: item.lift.test },
        apply: (v) => setTableHeight(tableGroup(item.key), v),
        hint: `Test ${item.lift.test} m - max ${item.lift.max} m` },
    ]),
  },
  {
    title: 'Ceiling mic rigs x 2',
    items: micRigs.flatMap(({ item }) => [
      { id: `${item.key}.z`, label: `${item.label} - depth Z`, unit: 'm',
        range: item.travelZ, format: fmt.pos,
        drag: { key: item.key, axis: 'z' } },
      { id: `${item.key}.x`, label: `${item.label} - lateral X`, unit: 'm',
        range: item.travelX, format: fmt.pos,
        drag: { key: item.key, axis: 'x' } },
      { id: `${item.key}.h`, label: `${item.label} - height Y`, unit: 'm',
        range: { ...C.micRig.height, default: item.heightDefault },
        apply: (v) => setMicHeight(micGroup(item.key), v),
        hint: 'GRAS 40AC / 40AF - 0.70 to 1.50 m' },
      { type: 'preset', target: `${item.key}.h`, values: C.micRig.height.presets,
        format: (v) => `${v} m` },
    ]),
  },
];

const HINT = '<b>Left-drag objects:</b> speaker array, screen, HATS, both tables, both mic rigs'
  + '<br><b>Left-drag empty space:</b> orbit - <b>Wheel:</b> zoom - <b>Right-drag:</b> pan'
  + '<br>This page <b>never moves the hardware</b> - it only designs and saves positions.';

const params = new URLSearchParams(location.search);

/** id → 控制項。setups.js 也吃這個登記表。 */
const controls = {};

// ══════════════════════════════════════════════════
//  側邊欄
// ══════════════════════════════════════════════════
function buildPanel() {
  const panel = $('#panel');
  panel.innerHTML = `
    <h1>Acoustic test room</h1>
    <div class="sub">Room ${C.room.width} x ${C.room.depth} x ${C.room.height} m</div>
    <div id="limitwarn"></div>
    <div id="setupbar"></div>`;

  for (const grp of PANEL) {
    const box = document.createElement('div');
    box.className = 'group';
    box.innerHTML = `<h2>${grp.title}</h2>`;

    for (const it of grp.items) {
      if (it.type === 'preset') {
        const row = document.createElement('div');
        row.className = 'views presets';
        for (const v of it.values) {
          const b = document.createElement('button');
          b.textContent = it.format ? it.format(v) : v;
          b.onclick = () => controls[it.target]?.set(v);
          row.appendChild(b);
        }
        box.appendChild(row);
        continue;
      }
      box.appendChild(makeControl(it));
    }
    panel.appendChild(box);
  }

  panel.appendChild(makeViewBox());
}

/** 一個控制項:讀數 + 拉桿 */
function makeControl(it) {
  const wrap = document.createElement('div');
  wrap.className = 'ctl';
  wrap.dataset.id = it.id;
  wrap.innerHTML = `
    <div class="row"><span class="name">${it.label}</span><span class="val">—</span></div>
    <input type="range">
    ${it.hint ? `<div class="lim">${it.hint}</div>` : ''}`;

  const el = wrap.querySelector('input');
  const out = wrap.querySelector('.val');
  const format = it.format || fmt.by(it.unit);
  const r = it.range;

  el.min = r.min; el.max = r.max; el.step = it.step ?? 0.01;
  el.value = r.default ?? r.min;

  /** 只套用到 3D */
  const apply = (v) => {
    if (it.drag) interaction.set(it.drag.key, it.drag.axis, v);
    else it.apply(v);
  };

  /** 拉桿 + 讀數 + 3D 一起設 —— 載入擺位與快捷鍵用 */
  const set = (v) => {
    el.value = v;
    out.textContent = format(parseFloat(el.value));
    apply(parseFloat(el.value));
  };

  el.addEventListener('input', () => {
    const v = parseFloat(el.value);
    out.textContent = format(v);
    apply(v);
  });

  controls[it.id] = {
    id: it.id, label: it.label, unit: it.unit, range: r, format,
    el, out, wrap, apply, set,
    get value() { return parseFloat(el.value); },
  };
  set(parseFloat(el.value));
  return wrap;
}

function makeViewBox() {
  const v = document.createElement('div');
  v.className = 'group';
  v.innerHTML = `<h2>View</h2>
    <div class="views">
      <button data-view="iso">Iso</button>
      <button data-view="top">Top</button>
      <button data-view="front">Front</button>
      <button data-view="side">Side</button>
    </div>`;

  const VIEWS = {
    iso: { pos: C.camera.position, target: C.camera.target },
    top: { pos: [0, 9.5, 0.01], target: [0, 0, 0] },
    front: { pos: [0, 1.3, 8.4], target: [0, 1.1, 0] },
    side: { pos: [8.4, 1.5, 0], target: [0, 1.1, 0] },
  };
  v.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => {
    const p = VIEWS[b.dataset.view];
    camera.position.set(...p.pos);
    controls3d.target.set(...p.target);
  }));
  return v;
}

// ══════════════════════════════════════════════════
//  行程對照
// ══════════════════════════════════════════════════
/**
 * 拿後端的軸清單,跟 spec.json 的行程對一次。
 *
 * 兩邊刻意各存一份(後端不能拿瀏覽器送來的範圍當行程上限)。存擺位時
 * 後端會把超出行程的值夾回範圍內(roomsetups.clean_axes),所以兩邊不一致
 * 時,畫面上擺的位置跟存進去的會不一樣 —— 一定要看得見。
 */
async function checkLimits() {
  const host = $('#limitwarn');
  let m;
  try { m = await jsonFetch('/api/room/axes'); } catch (e) {
    host.innerHTML = `<div class="lv bad"><b>Cannot read the backend axis list</b>
      <div class="sub">${esc(e.message || e)}</div></div>`;
    return;
  }
  const byId = Object.fromEntries((m.axes || []).map((a) => [a.id, a]));
  const near = (x, y) => Math.abs(x - y) < 1e-6;
  const bad = [];
  for (const [id, c] of Object.entries(controls)) {
    const a = byId[id];
    if (!a) { bad.push(`${id}: the backend has no such axis`); continue; }
    if (!near(a.min, c.range.min) || !near(a.max, c.range.max)) {
      bad.push(`${id}: 3D ${c.range.min} to ${c.range.max} / backend ${a.min} to ${a.max}`);
    }
  }
  for (const a of m.axes || []) {
    if (!controls[a.id]) bad.push(`${a.id}: the 3D view has no control for this axis`);
  }
  host.innerHTML = bad.length ? `<div class="lv bad"><b>Travel limits disagree</b><div class="sub">
    ${bad.map(esc).join('<br>')}<br>
    <code>spec.json</code> and <code>acqua/crane.py</code> disagree. Saved values are clamped
    to the backend limits.</div></div>` : '';
}

// ══════════════════════════════════════════════════
//  擺位
// ══════════════════════════════════════════════════
let setupCache = [];
let editing = null;         // 正在編輯哪個已存的擺位(從擺位清單開過來的)

async function refreshSetups() {
  try { setupCache = await listSetups(); } catch { setupCache = []; }
  renderSetupBar();
}

//: 「原始設計位置」在下拉選單裡的代號。不是一個存檔,是 spec.json 的預設值 ——
//  也就是這一頁第一次打開時的樣子。放在選單最上面,讓人隨時回得去看原本長怎樣。
const DEFAULT_ID = '__default__';

/** 名稱太長會把下拉的彈出框撐得很寬,選單裡截斷就好(詳細頁看得到全名) */
const shortName = (n) => (n.length > 42 ? n.slice(0, 41) + '…' : n);

function setupOptions(selected) {
  const opts = ['<option value="">Choose a position...</option>',
    '<optgroup label="Built in">',
    `<option value="${DEFAULT_ID}"${selected === DEFAULT_ID ? ' selected' : ''}>`
    + 'Original design position (spec.json defaults)</option>',
    '</optgroup>'];
  if (setupCache.length) {
    opts.push('<optgroup label="Saved positions">');
    for (const s of setupCache) {
      opts.push(`<option value="${esc(s.id)}"${s.id === selected ? ' selected' : ''}>`
        + `${esc(shortName(s.name))}</option>`);
    }
    opts.push('</optgroup>');
  }
  return opts.join('');
}

/** spec.json 的預設值長成一個「假擺位」,好讓載入的路徑只有一條 */
function defaultSetup() {
  return {
    id: DEFAULT_ID, name: 'Original design position',
    axes: Object.fromEntries(
      Object.values(controls).map((c) => [c.id, c.range.default ?? c.range.min])),
  };
}

function renderSetupBar() {
  const bar = $('#setupbar');
  bar.className = 'group modebar';
  bar.innerHTML = `<h2>Positions</h2>
    ${editing ? `<div class="editing">Editing
       <b>${esc(editing.name)}</b></div>` : ''}
    <button class="wide primary" id="mb-save">
      ${editing ? 'Update this position' : 'Save current position...'}</button>
    ${editing ? '<button class="wide" id="mb-saveas">Save as a new position...</button>' : ''}
    <label class="lbl">Load a position into the view</label>
    <select id="mb-pick">${setupOptions(editing?.id)}</select>
    <button class="wide" id="mb-load">Load into view</button>
    <div class="lim">"Original design position" is the <code>spec.json</code> default -
      what this page looks like the first time you open it.<br>
      Saved positions are applied to the hardware automatically during a test run,
      by the <code>Setup</code> tag on each test item.</div>`;

  $('#mb-save').onclick = async () => {
    const s = await saveCurrent(snapshotAxes(), { existing: editing });
    if (s) { editing = s; await refreshSetups(); }
  };
  const saveas = $('#mb-saveas');
  if (saveas) saveas.onclick = async () => {
    const s = await saveCurrent(snapshotAxes());
    if (s) { editing = s; await refreshSetups(); }
  };
  $('#mb-load').onclick = () => {
    const id = $('#mb-pick').value;
    if (!id) { toast('Choose a position first', 'warn'); return; }

    // 原始設計位置走同一條載入路徑,只是那組數字是 spec.json 給的。
    // editing 要清掉 —— 它不是存檔,下次按儲存該是「新增」而不是
    // 「更新」,不然會把某個存好的擺位覆蓋成預設值。
    const s = id === DEFAULT_ID ? defaultSetup()
      : setupCache.find((x) => x.id === id);
    if (!s) { toast('That position no longer exists', 'warn'); return; }

    const r = applyToScene(s, controls);
    editing = id === DEFAULT_ID ? null : s;
    renderSetupBar();
    if (id === DEFAULT_ID) $('#mb-pick').value = DEFAULT_ID;
    toast(`Loaded "${s.name}" (${r.applied.length} axes`
      + (r.absent.length ? `, ${r.absent.length} not stored` : '') + ')');
  };
}

/** 目前畫面上每一根軸的值 —— 存擺位用 */
function snapshotAxes() {
  return Object.fromEntries(
    Object.values(controls).map((c) => [c.id, Math.round(c.value * 10000) / 10000]));
}

// ══════════════════════════════════════════════════
//  啟動
// ══════════════════════════════════════════════════
buildPanel();
const hint = $('#hint');
if (hint) hint.innerHTML = HINT;

await refreshSetups();
checkLimits();

// ?setup=<id> —— 從擺位清單的「在 3D 裡開啟」進來的
const wantSetup = params.get('setup');
if (wantSetup) {
  const s = setupCache.find((x) => x.id === wantSetup);
  if (s) {
    applyToScene(s, controls);
    editing = s;
    renderSetupBar();
    toast(`Loaded "${s.name}"`);
  } else {
    toast('That position no longer exists', 'bad');
  }
}

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
  controls3d.update();
  renderer.render(scene, camera);
});

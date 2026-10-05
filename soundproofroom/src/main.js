/**
 * 聲學測試室 3D 視覺化 —— 進入點
 *
 * 兩個模式,同一個場景
 * ────────────────────
 *   設定模式  離線畫圖。拉桿與拖曳直接改 3D,存成「擺位(setup)」。
 *             不會碰到任何機構,愛怎麼試都行。
 *   即時模式  3D 反映**實機報回來的位置**。拉桿變成「提出一個目標」,
 *             放手後跳確認框,按確定才真的下指令。拖曳整個關掉。
 *
 * 為什麼即時模式不能沿用設定模式那套「拉了就動」:機構有物理限制,
 * 而且一動就是真的在動。手滑碰到拉桿就讓天車跑起來太隨便了 ——
 * 所以在即時模式,**在按下確定之前畫面上不會有任何東西動**,不會給人
 * 「已經移過去了」的錯覺。
 *
 * 側邊欄是依 PANEL 宣告動態生成的:物件多了之後,再用靜態 HTML 維護
 * 二十幾個拉桿很容易漏。要加新物件只要在 PANEL 裡多一筆。
 *
 * ⚠️ 每個控制項的 id 是**跨三處的契約**:
 *      soundproofroom/src/main.js   這裡的 PANEL
 *      acqua/crane.py               AXES(對應到哪台 Pi 的哪根軸)
 *      setups/*.json                存好的擺位的鍵
 *    改 id 會讓存好的擺位對不上,也會讓即時模式找不到軸。要改就得寫搬移。
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
import { createLive } from './live.js';
import { fmt, esc, toast, confirmBox } from './ui.js';
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
    // 即時模式的讀數是「實機報回來的位置」,由 live.js 負責寫(它還要標
    // estimated)。這裡再寫一次會把它蓋成補間出來的中間值 —— 數字看起來
    // 一樣在動,但已經不是實機回報的那個值了。
    if (mode === 'live') return;
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

// ══════════════════════════════════════════════════
//  模式
// ══════════════════════════════════════════════════
//
// 預設是**設定模式**,不是即時模式 —— 一開頁面就去跟硬體講話、而且
// 3D 立刻跳到實機位置,對不預期的人太突然。要看實機就自己切,或帶
// ?mode=live 進來。切過之後記在 localStorage,下次照上次的。
const MODES = {
  live: {
    label: 'Live mode',
    hint: '<b>The 3D view shows where the hardware actually is.</b> A slider proposes a target; you are asked before anything moves.'
        + '<br><b>Dragging objects is off.</b> Left-drag: orbit - Wheel: zoom - Right-drag: pan',
  },
  setup: {
    label: 'Layout mode',
    hint: '<b>Left-drag objects:</b> speaker array, screen, HATS, both tables, both mic rigs'
        + '<br><b>Left-drag empty space:</b> orbit - <b>Wheel:</b> zoom - <b>Right-drag:</b> pan'
        + '<br>This mode <b>never moves the hardware</b>. Save a position first, then apply it from Live mode.',
  },
};

const params = new URLSearchParams(location.search);
let mode = params.get('mode') === 'live' ? 'live'
  : params.get('mode') === 'setup' ? 'setup'
    : (localStorage.getItem('sprMode') === 'live' ? 'live' : 'setup');

/** id → 控制項。live.js 與 setups.js 都吃這個登記表。 */
const controls = {};

/** 即時模式的控制器。buildPanel() 之後才建 —— 它要 #livestatus 這個容器。 */
let live = null;

// ══════════════════════════════════════════════════
//  側邊欄
// ══════════════════════════════════════════════════
function buildPanel() {
  const panel = $('#panel');
  panel.innerHTML = `
    <h1>Acoustic test room</h1>
    <div class="sub">Room ${C.room.width} x ${C.room.depth} x ${C.room.height} m</div>
    <div class="modesw" id="modesw">
      <button data-mode="live">Live</button>
      <button data-mode="setup">Layout</button>
    </div>
    <div id="livestatus"></div>
    <div id="modebar"></div>`;

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
          // 快捷鍵在即時模式也要走確認流程 —— 它就是一個「把拉桿撥到這裡」
          b.onclick = () => {
            const c = controls[it.target];
            if (!c) return;
            if (mode === 'live') { c.el.value = v; c.el.dispatchEvent(new Event('change')); }
            else c.set(v);
          };
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

/** 一個控制項:讀數 + 拉桿 + (即時模式)目標提示 */
function makeControl(it) {
  const wrap = document.createElement('div');
  wrap.className = 'ctl';
  wrap.dataset.id = it.id;
  wrap.innerHTML = `
    <div class="row"><span class="name">${it.label}</span><span class="val">—</span></div>
    <input type="range">
    <div class="tgt" hidden></div>
    ${it.hint ? `<div class="lim">${it.hint}</div>` : ''}`;

  const el = wrap.querySelector('input');
  const out = wrap.querySelector('.val');
  const tgt = wrap.querySelector('.tgt');
  const format = it.format || fmt.by(it.unit);
  const r = it.range;

  el.min = r.min; el.max = r.max; el.step = it.step ?? 0.01;
  el.value = r.default ?? r.min;

  /** 只套用到 3D,不動拉桿(即時模式由回報的位置驅動) */
  const apply = (v) => {
    if (it.drag) interaction.set(it.drag.key, it.drag.axis, v);
    else it.apply(v);
  };

  /** 拉桿 + 讀數 + 3D 一起設 —— 設定模式與載入擺位用 */
  const set = (v) => {
    el.value = v;
    out.textContent = format(parseFloat(el.value));
    apply(parseFloat(el.value));
  };

  el.addEventListener('input', () => {
    const v = parseFloat(el.value);
    if (mode === 'setup') {
      out.textContent = format(v);
      apply(v);
      return;
    }
    // 即時模式:拉桿只是在挑目標,3D 一動也不動
    tgt.hidden = false;
    tgt.innerHTML = `Target <b>${format(v)}</b> - you will be asked before it moves`;
  });

  // change(放手)才問 —— input 每動一格就跳框會變成連環轟炸
  el.addEventListener('change', async () => {
    if (mode !== 'live') return;
    await live.requestMove(it.id, parseFloat(el.value));
    tgt.hidden = true;
  });

  controls[it.id] = {
    id: it.id, label: it.label, unit: it.unit, range: r, format,
    el, out, wrap, tgt, apply, set,
    get value() { return parseFloat(el.value); },
  };
  set(parseFloat(el.value));
  return wrap;
}

function makeViewBox() {
  const v = document.createElement('div');
  v.className = 'group';
  // 只有視角按鈕。原本底下那排連結(回首頁 / 擺位清單)拿掉了 ——
  // 左邊那條側邊欄已經有同樣的入口,重複放只是把面板拉長。
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
//  每個模式自己的動作列
// ══════════════════════════════════════════════════
let setupCache = [];
let editing = null;         // 正在編輯哪個已存的擺位(從擺位清單開過來的)

async function refreshSetups() {
  try { setupCache = await listSetups(); } catch { setupCache = []; }
  renderModeBar();
}

//: 「原始設計位置」在下拉選單裡的代號。不是一個存檔,是 spec.js 的預設值 ——
//  也就是這一頁第一次打開時的樣子。放在選單最上面,讓人隨時回得去看原本長怎樣。
const DEFAULT_ID = '__default__';

/** 名稱太長會把下拉的彈出框撐得很寬,選單裡截斷就好(詳細頁看得到全名) */
const shortName = (n) => (n.length > 42 ? n.slice(0, 41) + '…' : n);

function setupOptions(selected) {
  const opts = ['<option value="">Choose a position...</option>',
    '<optgroup label="Built in">',
    `<option value="${DEFAULT_ID}"${selected === DEFAULT_ID ? ' selected' : ''}>`
    + 'Original design position (spec.js defaults)</option>',
    '</optgroup>'];
  if (setupCache.length) {
    opts.push('<optgroup label="Saved positions">');
    for (const s of setupCache) {
      opts.push(`<option value="${esc(s.id)}"${s.id === selected ? ' selected' : ''}>`
        + `${esc(shortName(s.name))}${s.source === 'live' ? ' (from hardware)' : ''}</option>`);
    }
    opts.push('</optgroup>');
  }
  return opts.join('');
}

/** spec.js 的預設值長成一個「假擺位」,好讓載入的路徑只有一條 */
function defaultSetup() {
  return {
    id: DEFAULT_ID, name: 'Original design position',
    axes: Object.fromEntries(
      Object.values(controls).map((c) => [c.id, c.range.default ?? c.range.min])),
  };
}

function renderModeBar() {
  const bar = $('#modebar');
  if (mode === 'setup') {
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
      <div class="lim">"Original design position" is the <code>spec.js</code> default -
        what this page looks like the first time you open it.<br>
        This mode only changes the view. To move the hardware, switch to Live mode and apply.</div>`;

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

      // 原始設計位置走同一條載入路徑,只是那組數字是 spec.js 給的。
      // editing 要清掉 —— 它不是存檔,下次按儲存該是「新增」而不是
      // 「更新」,不然會把某個存好的擺位覆蓋成預設值。
      const s = id === DEFAULT_ID ? defaultSetup()
        : setupCache.find((x) => x.id === id);
      if (!s) { toast('That position no longer exists', 'warn'); return; }

      const r = applyToScene(s, controls);
      editing = id === DEFAULT_ID ? null : s;
      renderModeBar();
      if (id === DEFAULT_ID) $('#mb-pick').value = DEFAULT_ID;
      toast(`Loaded "${s.name}" (${r.applied.length} axes`
        + (r.absent.length ? `, ${r.absent.length} not stored` : '') + ')');
    };
    return;
  }

  // ── 即時模式 ──
  //
  // 刻意留空。即時模式的側欄只放「現在什麼狀況」跟「每一根軸在哪」——
  // 那才是這個模式存在的理由。把擺位的下拉、按鈕也塞進來,等於在一個
  // 「按下去機構就會動」的畫面裡多放兩個入口,而且擺位一筆都沒有的時候
  // 就是一個灰掉的按鈕配一句「(還沒有存過擺位)」,佔位置又沒有用。
  //
  // 「把擺位套用到實機」的入口在擺位詳細頁(/setups/<id>),從那裡按會帶
  // ?mode=live&apply=<id> 進來,一樣走這一頁的確認框。
  bar.className = '';
  bar.innerHTML = '';
}

function paintModeButtons() {
  $('#modesw')?.querySelectorAll('[data-mode]').forEach((b) => {
    b.classList.toggle('on', b.dataset.mode === mode);
  });
}

/** 目前畫面上每一根軸的值 —— 存擺位用 */
function snapshotAxes() {
  return Object.fromEntries(
    Object.values(controls).map((c) => [c.id, Math.round(c.value * 10000) / 10000]));
}

// ══════════════════════════════════════════════════
//  切模式
// ══════════════════════════════════════════════════
/**
 * 切模式前的確認框。
 *
 * 為什麼連「切到設定模式」都要問:兩個模式底下,**同一根拉桿的意思完全
 * 不一樣** —— 一邊是畫圖,一邊是對真的機構下指令。不知道自己在哪個模式
 * 就去拉拉桿,是這一頁最容易出事的地方。所以切換不做成無聲的 toggle。
 *
 * 切到即時模式時會**先探一次**再問,把「現在到底抓不抓得到實機位置」寫在
 * 框上。切過去才發現讀不到,那個資訊來得太晚。
 */
async function askSwitch(next) {
  if (next === 'setup') {
    return confirmBox({
      title: 'Switch to Layout mode?',
      html: `
        <div class="mdsw setup">
          <div class="r"><i>✏️</i><span>Sliders and dragging <b>change the 3D view only</b></span></div>
          <div class="r"><i>🔒</i><span>This mode <b>never touches the hardware</b> - experiment freely</span></div>
          <div class="r"><i>💾</i><span>Save the arrangement as a position when you are happy</span></div>
        </div>
        <div class="bxnote">Sliders start from the <b>last position the hardware reported</b>,
          so you can adjust from where things actually are.</div>`,
      ok: 'Switch to Layout', cancel: 'Stay in Live',
    });
  }

  // ── 切到即時模式:先探一次 ──
  const p = await live.probe();
  const status = {
    live: `<div class="mdst ok"><b>Connected to the hardware</b>
             <div>Read ${p.total} axes${
               p.estimated ? ` - ${p.estimated} estimated` : ''}${
               p.offline ? ` - ${p.offline} of ${p.devices} devices offline` : ''}</div></div>`,
    mock: `<div class="mdst warn"><b>No hardware - showing simulated positions</b>
             <div>Not connected to the crane controller, so these numbers are computed, not measured.
             Set <code>ACQUA_SETUP_CONTROLLER</code> in <code>.env</code> to use real hardware.</div></div>`,
    error: `<div class="mdst bad"><b>Cannot read positions</b>
             <div>${esc(p.error || '')}</div></div>`,
  }[p.state];

  return confirmBox({
    title: 'Switch to Live mode?',
    html: `
      ${status}
      <div class="mdsw live">
        <div class="r"><i>📡</i><span>The 3D view switches to <b>what the hardware reports</b></span></div>
        <div class="r"><i>🎚️</i><span>Sliders <b>propose a target</b> - you are asked again before it moves</span></div>
        <div class="r"><i>🚫</i><span>Dragging objects is <b>turned off</b> (you can still orbit)</span></div>
      </div>
      ${p.busy ? '<div class="bxnote warn">The hardware is <b>moving right now</b>.</div>' : ''}
      ${p.state === 'error'
        ? '<div class="bxnote warn">You can still switch, but nothing updates until a position is read.</div>'
        : ''}`,
    ok: 'Switch to Live', cancel: 'Cancel',
  });
}

async function setMode(next, { remember = true, ask = false } = {}) {
  if (!MODES[next]) return;
  if (next === mode && ask) return;         // 點目前這一顆不算切換
  // 機構正在動的時候不准切走 —— 切到設定模式會讓拉桿又變成「直接改 3D」,
  // 畫面就跟實際位置脫節了,而機構還在跑。
  if (mode === 'live' && next !== 'live' && live.busy) {
    toast('The hardware is still moving - wait for it to finish', 'warn');
    return;
  }
  if (ask && !(await askSwitch(next))) {
    // 取消了 —— 把切換鈕的亮起狀態撥回目前這個模式
    paintModeButtons();
    return;
  }
  mode = next;
  if (remember) localStorage.setItem('sprMode', mode);

  document.body.dataset.mode = mode;
  paintModeButtons();
  const hint = $('#hint');
  if (hint) hint.innerHTML = MODES[mode].hint;

  interaction.setEnabled(mode === 'setup');

  if (mode === 'live') {
    await live.enable();
  } else {
    live.disable();
    // 從即時模式切回來:把拉桿與 3D 對回實機最後的位置,而不是
    // 跳回預設值 —— 通常下一步就是「照現在的位置微調一下再存起來」。
    const pos = live.positions;
    for (const [id, v] of Object.entries(pos)) controls[id]?.set(v);
    Object.values(controls).forEach((c) => { c.el.disabled = false; c.tgt.hidden = true; });
  }
  renderModeBar();
}

// ══════════════════════════════════════════════════
//  啟動
// ══════════════════════════════════════════════════
buildPanel();

live = createLive({
  controls,
  applyToScene: (id, v) => controls[id]?.apply(v),
  statusHost: $('#livestatus'),
});

$('#modesw').querySelectorAll('[data-mode]').forEach((b) => {
  b.onclick = () => setMode(b.dataset.mode, { ask: true });
});

await refreshSetups();

// ?setup=<id> —— 從擺位清單的「在 3D 裡開啟」進來的
const wantSetup = params.get('setup');
if (wantSetup) {
  const s = setupCache.find((x) => x.id === wantSetup);
  if (s) {
    mode = 'setup';
    applyToScene(s, controls);
    editing = s;
    toast(`Loaded "${s.name}"`);
  } else {
    toast('That position no longer exists', 'bad');
  }
}

// ?apply=<id> —— 從擺位詳細頁的「套用到實機」進來的。刻意**不自動送出**:
// 一定要走 live.applySetup 的確認框,讓人在機構動之前看到會動哪幾根軸。
const wantApply = params.get('apply');
if (wantApply) mode = 'live';

await setMode(mode, { remember: false });

if (wantApply) {
  const s = setupCache.find((x) => x.id === wantApply);
  if (!s) toast('That position no longer exists', 'bad');
  else live.applySetup(s.axes || {}, s.name);
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

let last = performance.now();
renderer.setAnimationLoop(() => {
  const now = performance.now();
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  live.tick(dt);            // 即時模式:往回報的位置補間
  controls3d.update();
  renderer.render(scene, camera);
});

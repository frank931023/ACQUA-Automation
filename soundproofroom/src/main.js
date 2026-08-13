/**
 * 聲學測試室 3D 視覺化 —— 進入點
 *
 * 這個檔案只負責「組裝」:場景 / 相機 / 控制 / UI 綁定。
 * 尺寸都在 config.js,幾何都在 builders.js,拖曳在 interaction.js。
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

import { CONFIG as C } from './config.js';
import {
  buildRoom, buildMainRail, buildSpeakerArray, setBracketDrop,
  buildFloorRail, buildHats, setHatsAngle, buildCeilingMics, buildLights,
} from './builders.js';
import { createInteraction } from './interaction.js';

const $ = (s) => document.querySelector(s);

// ── 基本三件套 ──────────────────────────────────
const container = $('#viewport');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x11151a);

const camera = new THREE.PerspectiveCamera(
  C.camera.fov, container.clientWidth / container.clientHeight,
  C.camera.near, C.camera.far
);
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
controls.maxPolarAngle = Math.PI * 0.495;   // 不要轉到地板below
controls.minDistance = 1.2;
controls.maxDistance = 22;

// ── 場景內容 ────────────────────────────────────
scene.add(buildLights());
scene.add(buildRoom());
scene.add(buildMainRail());
scene.add(buildFloorRail());
scene.add(buildCeilingMics());

const speakers = buildSpeakerArray();
speakers.position.set(C.mainRail.travel.default, C.mainRail.y, C.mainRail.z);
scene.add(speakers);

const hats = buildHats();
hats.position.set(0, 0, C.floorRail.travel.default);
scene.add(hats);

// 座標軸與格線 —— 對尺寸的時候很有用
const grid = new THREE.GridHelper(
  Math.max(C.room.width, C.room.depth), 20, 0x3a424c, 0x252b32);
grid.position.y = 0.002;
grid.material.transparent = true;
grid.material.opacity = 0.5;
scene.add(grid);

// ── 互動 ────────────────────────────────────────
const interaction = createInteraction({
  renderer, camera, controls,
  targets: [
    { key: 'speakers', group: speakers, axis: 'x', range: C.mainRail.travel },
    { key: 'hats', group: hats, axis: 'z', range: C.floorRail.travel },
  ],
  // 不管是拖曳還是 slider 造成的變動,都走同一條回呼 → UI 永遠一致
  onChange: (key, value, source) => syncUI(key, value, source),
});

// ── 側邊欄 ──────────────────────────────────────
function fmt(v) { return `${v >= 0 ? '+' : ''}${v.toFixed(2)} m`; }

function syncUI(key, value, source) {
  if (key === 'speakers') {
    if (source !== 'slider') $('#sp-x').value = value;
    $('#sp-x-val').textContent = fmt(value);
  } else if (key === 'hats') {
    if (source !== 'slider') $('#hats-z').value = value;
    $('#hats-z-val').textContent = fmt(value);
  }
}

// 喇叭:沿主滑軌左右
const spX = $('#sp-x');
spX.min = C.mainRail.travel.min;
spX.max = C.mainRail.travel.max;
spX.step = 0.01;
spX.value = C.mainRail.travel.default;
spX.addEventListener('input', () =>
  interaction.setPosition('speakers', parseFloat(spX.value)));

// HATS:沿地面滑軌前後
const hZ = $('#hats-z');
hZ.min = C.floorRail.travel.min;
hZ.max = C.floorRail.travel.max;
hZ.step = 0.01;
hZ.value = C.floorRail.travel.default;
hZ.addEventListener('input', () =>
  interaction.setPosition('hats', parseFloat(hZ.value)));

// 支架滑軌下降量(0.50 ~ 0.80)
const drop = $('#sp-drop');
drop.min = C.bracketRail.min;
drop.max = C.bracketRail.max;
drop.step = 0.01;
drop.value = C.bracketRail.default;
function applyDrop() {
  const v = parseFloat(drop.value);
  setBracketDrop(speakers, v);
  $('#sp-drop-val').textContent = `${v.toFixed(2)} m`;
}
drop.addEventListener('input', applyDrop);

// 轉盤角度
const ang = $('#hats-rot');
ang.min = -180; ang.max = 180; ang.step = 1;
ang.value = C.hats.turntable.defaultAngleDeg;
function applyAngle() {
  const v = parseFloat(ang.value);
  setHatsAngle(hats, v);
  $('#hats-rot-val').textContent = `${v.toFixed(0)}°`;
}
ang.addEventListener('input', applyAngle);

// 重設
$('#reset').addEventListener('click', () => {
  interaction.setPosition('speakers', C.mainRail.travel.default);
  spX.value = C.mainRail.travel.default;
  interaction.setPosition('hats', C.floorRail.travel.default);
  hZ.value = C.floorRail.travel.default;
  drop.value = C.bracketRail.default; applyDrop();
  ang.value = C.hats.turntable.defaultAngleDeg; applyAngle();
  camera.position.set(...C.camera.position);
  controls.target.set(...C.camera.target);
});

// 預設視角
const VIEWS = {
  iso: { pos: C.camera.position, target: C.camera.target },
  top: { pos: [0, 9.5, 0.01], target: [0, 0, 0] },
  front: { pos: [0, 1.4, 8.2], target: [0, 1.2, 0] },
  side: { pos: [8.2, 1.6, 0], target: [0, 1.2, 0] },
};
document.querySelectorAll('[data-view]').forEach((b) => {
  b.addEventListener('click', () => {
    const v = VIEWS[b.dataset.view];
    camera.position.set(...v.pos);
    controls.target.set(...v.target);
  });
});

// 尺寸資訊
$('#dims').textContent =
  `${C.room.width} × ${C.room.depth} × ${C.room.height} m`;

// 初始化 UI
syncUI('speakers', C.mainRail.travel.default, 'init');
syncUI('hats', C.floorRail.travel.default, 'init');
applyDrop();
applyAngle();

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

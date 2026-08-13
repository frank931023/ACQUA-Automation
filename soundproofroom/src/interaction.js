/**
 * 互動 —— 滑鼠拖曳 + 側邊欄 slider,兩邊雙向同步。
 *
 * 拖曳的作法:
 *   1. mousedown 時用 raycaster 找出點到哪個可拖曳的 Group
 *   2. 建立一個**通過該物件、面向相機**的虛擬平面
 *   3. mousemove 時把射線打到平面上,取交點
 *   4. 只取該物件被允許的那一軸(X 或 Z),並夾在滑軌範圍內
 *
 * 為什麼要用虛擬平面:直接拿滑鼠 delta 換算會因為透視而失真,
 * 打到平面上再取交點,不管相機怎麼轉都會跟著滑鼠走。
 */
import * as THREE from 'three';
import { CONFIG as C, clamp } from './config.js';

export function createInteraction({ renderer, camera, controls, targets, onChange }) {
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const dragPlane = new THREE.Plane();
  const hitPoint = new THREE.Vector3();
  const grabOffset = new THREE.Vector3();

  let dragging = null;      // 目前被拖的 target
  let hovered = null;

  /** targets: [{ key, group, axis, range }] */
  const byKey = Object.fromEntries(targets.map((t) => [t.key, t]));

  // 滑鼠位置換算成 NDC(-1..1)
  function updatePointer(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    pointer.x = ((ev.clientX - r.left) / r.width) * 2 - 1;
    pointer.y = -((ev.clientY - r.top) / r.height) * 2 + 1;
  }

  function pick() {
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(targets.map((t) => t.group), true);
    if (!hits.length) return null;
    // 往上找到掛著 draggable 標記的那一層 Group
    let o = hits[0].object;
    while (o && !o.userData?.draggable) o = o.parent;
    return o ? byKey[o.userData.draggable] : null;
  }

  function setHighlight(target, on) {
    if (!target) return;
    target.group.traverse((o) => {
      if (!o.isMesh) return;
      if (on) {
        if (!o.userData._origEmissive) {
          o.userData._origEmissive = o.material.emissive?.getHex() ?? 0x000000;
        }
        o.material.emissive?.setHex(C.highlight);
        if (o.material.emissiveIntensity !== undefined) o.material.emissiveIntensity = 0.28;
      } else if (o.userData._origEmissive !== undefined) {
        o.material.emissive?.setHex(o.userData._origEmissive);
        if (o.material.emissiveIntensity !== undefined) o.material.emissiveIntensity = 1;
      }
    });
  }

  function onPointerDown(ev) {
    if (ev.button !== 0) return;
    updatePointer(ev);
    const t = pick();
    if (!t) return;

    dragging = t;
    controls.enabled = false;              // 拖物件時停用 OrbitControls,不然會同時轉鏡頭
    renderer.domElement.style.cursor = 'grabbing';

    // 建立一個通過物件、法線朝向相機的平面
    const camDir = new THREE.Vector3();
    camera.getWorldDirection(camDir);
    dragPlane.setFromNormalAndCoplanarPoint(camDir, t.group.position);

    // 記住「滑鼠打到的點」跟「物件原點」的差,拖曳才不會跳一下
    raycaster.setFromCamera(pointer, camera);
    if (raycaster.ray.intersectPlane(dragPlane, hitPoint)) {
      grabOffset.copy(t.group.position).sub(hitPoint);
    } else {
      grabOffset.set(0, 0, 0);
    }
    ev.preventDefault();
  }

  function onPointerMove(ev) {
    updatePointer(ev);

    if (!dragging) {
      // 只做 hover 游標提示
      const t = pick();
      if (t !== hovered) {
        setHighlight(hovered, false);
        hovered = t;
        setHighlight(hovered, true);
        renderer.domElement.style.cursor = t ? 'grab' : 'default';
      }
      return;
    }

    raycaster.setFromCamera(pointer, camera);
    if (!raycaster.ray.intersectPlane(dragPlane, hitPoint)) return;

    const want = hitPoint.add(grabOffset);
    const axis = dragging.axis;                     // 'x' | 'z'
    const v = clamp(want[axis], dragging.range.min, dragging.range.max);
    dragging.group.position[axis] = v;
    onChange?.(dragging.key, v, 'drag');
  }

  function onPointerUp() {
    if (dragging) {
      controls.enabled = true;
      renderer.domElement.style.cursor = hovered ? 'grab' : 'default';
      dragging = null;
    }
  }

  const el = renderer.domElement;
  el.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);
  // 滑出視窗也要收尾,不然放開後還黏著
  window.addEventListener('pointercancel', onPointerUp);

  return {
    /** 從外部(slider)設定位置 */
    setPosition(key, value) {
      const t = byKey[key];
      if (!t) return;
      const v = clamp(value, t.range.min, t.range.max);
      t.group.position[t.axis] = v;
      onChange?.(key, v, 'slider');
    },
    dispose() {
      el.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
    },
  };
}

/**
 * 擺位(setup)—— 存下「這一次量測,房間裡每個東西站在哪裡」。
 *
 * 只存數字,不存 3D 的任何東西:一個擺位就是 {軸代號: 值},19 個浮點數。
 * 這組代號跟 acqua/crane.py 的 AXES、後端存檔的鍵完全同名 —— 所以
 * **存好的擺位可以原封不動送去驅動機構,中間不需要任何對應表**。
 * 這是整個設計裡最關鍵的一個決定;代號改名就會讓舊檔對不上。
 */
import { confirmBox, formBox, toast, esc, jsonFetch } from './ui.js';

const API = '/api/room/setups';

export const listSetups = () => jsonFetch(API).then((d) => d.setups || []);
export const getSetup = (id) => jsonFetch(`${API}/${encodeURIComponent(id)}`);

function send(url, method, body) {
  return jsonFetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/**
 * 儲存目前畫面。按下按鈕先跳框問名稱與說明 ——
 * 沒有名字的擺位一週後就認不出來了,所以名稱是必填。
 *
 * @param axes   {id: value}
 * @param n      軸數量,顯示用
 * @returns 存好的擺位,或取消時 null
 */
export async function saveCurrent(axes, { existing = null } = {}) {
  const n = Object.keys(axes).length;
  const v = await formBox({
    title: existing ? 'Update this position' : 'Save current position',
    note: `Stores the position of <b>${n}</b> axes.`
      + (existing ? '' : ' You can load it later, or apply it to the hardware.'),
    fields: [
      { key: 'name', label: 'Name', required: true, value: existing?.name || '',
        placeholder: 'e.g. near field 0.5 m - HATS pitched 17 deg' },
      { key: 'description', label: 'Description', textarea: true,
        value: existing?.description || '',
        placeholder: 'Which test is this for, and why this arrangement' },
    ],
    ok: existing ? 'Update' : 'Save',
  });
  if (!v) return null;

  const d = await send(existing ? `${API}/${encodeURIComponent(existing.id)}` : API,
    'POST', { name: v.name, description: v.description, axes, source: 'setup' });
  if (!d.ok) { toast(d.error || 'Could not save', 'bad'); return null; }
  toast(`Saved "${d.setup.name}"`);
  return d.setup;
}

/** 把實機當下的位置存成擺位。source 標成 live,清單上會標出來。 */
export async function saveFromLive(axes) {
  const v = await formBox({
    title: 'Save the hardware position',
    note: 'Stores <b>what the hardware reports right now</b>, not the slider values.',
    fields: [
      { key: 'name', label: 'Name', required: true,
        placeholder: 'e.g. 2026-09-15 shipping validation' },
      { key: 'description', label: 'Description', textarea: true,
        placeholder: 'Why this position is worth keeping' },
    ],
  });
  if (!v) return null;
  const d = await send(API, 'POST',
    { name: v.name, description: v.description, axes, source: 'live' });
  if (!d.ok) { toast(d.error || 'Could not save', 'bad'); return null; }
  toast(`Saved "${d.setup.name}"`);
  return d.setup;
}

export async function removeSetup(s) {
  const yes = await confirmBox({
    title: 'Delete this position?',
    html: `<div class="bxnote"><b>${esc(s.name)}</b><br>
      ${esc(s.description || '(no description)')}</div>
      <div class="bxnote warn">This cannot be undone. The hardware does not move.</div>`,
    ok: 'Delete', danger: true,
  });
  if (!yes) return false;
  const d = await send(`${API}/${encodeURIComponent(s.id)}`, 'DELETE');
  toast(d.ok ? 'Deleted' : 'Could not delete', d.ok ? 'ok' : 'bad');
  return !!d.ok;
}

/**
 * 把一個擺位套進 3D 畫面(**只動畫面,不動機構**)。
 *
 * 缺的軸刻意不補預設值 —— 舊擺位可能是在還沒有某根軸的時候存的,
 * 硬塞一個預設值會讓人以為那個位置是當初量的。
 */
export function applyToScene(setup, controls) {
  const applied = [];
  const missing = [];
  for (const [id, v] of Object.entries(setup.axes || {})) {
    const c = controls[id];
    if (!c) { missing.push(id); continue; }
    c.set(v);
    applied.push(id);
  }
  const absent = Object.keys(controls).filter((id) => !(id in (setup.axes || {})));
  return { applied, missing, absent };
}

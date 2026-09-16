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
    title: existing ? '更新這個擺位' : '儲存目前擺位',
    note: `會存下 <b>${n}</b> 根軸的位置。`
      + (existing ? '' : '之後可以從擺位清單叫出來,或直接套用到實機。'),
    fields: [
      { key: 'name', label: '名稱', required: true, value: existing?.name || '',
        placeholder: '例如:近場 0.5 m ・ HATS 前傾 17°' },
      { key: 'description', label: '說明', textarea: true,
        value: existing?.description || '',
        placeholder: '這個擺位是給哪個測試用的、為什麼這樣擺' },
    ],
    ok: existing ? '更新' : '儲存',
  });
  if (!v) return null;

  const d = await send(existing ? `${API}/${encodeURIComponent(existing.id)}` : API,
    'POST', { name: v.name, description: v.description, axes, source: 'setup' });
  if (!d.ok) { toast(d.error || '存不起來', 'bad'); return null; }
  toast(`已儲存「${d.setup.name}」`);
  return d.setup;
}

/** 把實機當下的位置存成擺位。source 標成 live,清單上會標出來。 */
export async function saveFromLive(axes) {
  const v = await formBox({
    title: '把實機目前位置存成擺位',
    note: '存的是<b>現在讀到的實機位置</b>,不是畫面上拉桿的值。',
    fields: [
      { key: 'name', label: '名稱', required: true,
        placeholder: '例如:2026-09-15 出貨驗證擺位' },
      { key: 'description', label: '說明', textarea: true,
        placeholder: '為什麼要把這個位置留下來' },
    ],
  });
  if (!v) return null;
  const d = await send(API, 'POST',
    { name: v.name, description: v.description, axes, source: 'live' });
  if (!d.ok) { toast(d.error || '存不起來', 'bad'); return null; }
  toast(`已儲存「${d.setup.name}」`);
  return d.setup;
}

export async function removeSetup(s) {
  const yes = await confirmBox({
    title: '刪掉這個擺位?',
    html: `<div class="bxnote"><b>${esc(s.name)}</b><br>
      ${esc(s.description || '(沒有說明)')}</div>
      <div class="bxnote warn">刪掉就沒了,而且不會影響機構目前的位置。</div>`,
    ok: '刪除', danger: true,
  });
  if (!yes) return false;
  const d = await send(`${API}/${encodeURIComponent(s.id)}`, 'DELETE');
  toast(d.ok ? '已刪除' : '刪不掉', d.ok ? 'ok' : 'bad');
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

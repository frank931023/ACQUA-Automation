/**
 * 即時模式 —— 3D 畫面跟著實機的位置跑,拉桿變成「目標」而不是「開關」。
 *
 * 跟設定模式最重要的差別
 * ──────────────────────
 *   設定模式  拉桿 = 直接改 3D。那是畫圖,愛怎麼拉都行。
 *   即時模式  拉桿 = 提出一個目標。3D 只反映**實機報回來的位置**,
 *             絕對不會因為誰碰了拉桿就自己動。
 *
 * 所以拉桿放手後會跳確認框(從哪到哪、走多遠、幾秒、送出去的是哪一條
 * 韌體指令),按確定才真的下指令;按取消拉桿跳回實機當下的位置。
 * 這不只是「多問一次」——**在按下確定之前,畫面上不會有任何東西動**,
 * 不會給人「東西已經移過去了」的錯覺。
 *
 * 3D 的平滑
 * ─────────
 * 後端每 80 ms 更新一次估計位置,但前端不可能每 80 ms 打一次 HTTP。
 * 所以前端存「最新收到的位置」,每一幀往它靠近一點(見 tick)。
 * 移動看起來是連續的,但那個連續性只是補間 —— 面板上的數字一律顯示
 * 收到的原始值,不顯示補間值。數字要是真的,畫面可以差 100 ms。
 */
import { confirmBox, fmt, esc, toast, jsonFetch } from './ui.js';

const GET = (u) => jsonFetch(u);
const POST = (u, body) => jsonFetch(u, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

/** 裝置三態 → 給人看的字(跟天車控制中心的徽章一致) */
const DEV_TEXT = {
  online: ['ok', '連接中'],
  'no-arduino': ['warn', 'Arduino 未接'],
  offline: ['bad', '離線'],
  missing: ['bad', '控制中心沒這台'],
  unknown: ['warn', '未知'],
};

/** 指數趨近的速率(1/秒)。時間常數 ≈ 1/9 s,也就是每 110 ms 追掉約 2/3 的
 *  落差,完全收斂大約 330 ms。移動中輪詢是 350 ms 一次,所以下一個樣本進來
 *  之前畫面早就追上了 —— 看起來是連續的,而不是每 350 ms 跳一格。 */
const EASE = 9;

/** 收斂到這個距離內就直接就位。1 mm 比韌體本身的解析度還細,
 *  所以「省下來的那段」在實機上根本不存在 —— 留著只會讓物件在終點
 *  拖一條看得出來的尾巴。角度軸用 0.1°,同理。 */
const SNAP = { m: 0.001, deg: 0.1 };

export function createLive({ controls, applyToScene, statusHost }) {
  let on = false;
  let timer = null;
  let snap = null;                 // 最後一次 /api/room/live
  let manifest = null;             // /api/room/axes,拿來跟 spec.js 對行程
  //: 輪詢的世代。手動踢一次(例如剛下完 move,想讓進度條立刻出現)會 +1,
  //  舊世代那一次回來之後就不再排下一次 —— 不然 clearTimeout 停不掉正在
  //  飛的請求,它回來還是會接上,變成兩條鏈並行、請求速率翻倍。
  let gen = 0;
  const wanted = {};               // id → 實機報回來的位置
  const shown = {};                // id → 3D 現在畫在哪(補間用)
  let pendingId = null;            // 正在跳確認框的那根軸

  // ── 輪詢 ────────────────────────────────────────
  //
  // 用 setTimeout 自己排下一次,不用 setInterval:上一次還沒回來就再發
  // 一次的話,慢的時候請求會越積越多(天車控制中心的 README 記過同一個坑)。
  // 有作業在跑時 350 ms,閒著時 1.8 秒 —— 閒著的時候位置不會變,
  // 沒必要一直吵它。
  async function poll() {
    if (!on) return;
    const mine = ++gen;
    try {
      const s = await GET('/api/room/live');
      if (!on || mine !== gen) return;
      snap = s;
      for (const [id, a] of Object.entries(s.axes || {})) {
        if (!controls[id]) continue;
        wanted[id] = a.value;
        if (shown[id] === undefined) shown[id] = a.value;   // 第一次直接就位
      }
      paint();
    } catch (e) {
      if (!on || mine !== gen) return;
      snap = { error: String(e.message || e) };
      paint();
    }
    if (!on || mine !== gen) return;            // 已經有更新的一輪接手了
    const busy = snap?.job && ['running', 'aborting'].includes(snap.job.state);
    clearTimeout(timer);
    timer = setTimeout(poll, busy ? 350 : 1800);
  }

  /** 每一幀往收到的位置靠近一點。dt 是秒。 */
  function tick(dt) {
    if (!on) return;
    const k = Math.min(1, dt * EASE);
    for (const id of Object.keys(wanted)) {
      const w = wanted[id];
      const s = shown[id] ?? w;
      const tol = SNAP[controls[id]?.unit] ?? SNAP.m;
      const next = Math.abs(w - s) < tol ? w : s + (w - s) * k;
      if (next !== s) {
        shown[id] = next;
        applyToScene(id, next);
      }
    }
  }

  // ── 面板繪製 ────────────────────────────────────
  function paint() {
    if (!on) return;
    paintStatus();
    const busy = !!(snap?.job && ['running', 'aborting'].includes(snap.job.state));
    const movingAxis = busy ? snap.job.steps[snap.job.index]?.axis : null;

    for (const [id, c] of Object.entries(controls)) {
      const a = snap?.axes?.[id];
      if (!a) continue;
      // 讀數 = 實機的值。estimated 的前面加「~」並標色 —— 使用者要分得出
      // 「量到的」跟「算出來的」,不然會拿推估值去對現場。
      c.out.textContent = (a.estimated ? '~' : '') + c.format(a.value);
      c.out.classList.toggle('est', !!a.estimated);
      c.wrap.classList.toggle('moving', id === movingAxis);
      // 移動中不准再碰拉桿:一次只動一根軸是刻意的(行程互相重疊)
      c.el.disabled = busy || pendingId !== null;
      // 拉桿平常要貼著實機的位置,但**手還壓在上面的時候不能撥走它** ——
      // 輪詢每 1.8 秒一次,正好會在使用者慢慢拉的時候把拉桿搶回去。
      // 判斷「正在碰」用兩個訊號:焦點在這根拉桿上,或目標提示還開著。
      const touching = document.activeElement === c.el || !c.tgt.hidden;
      if (id !== pendingId && !touching
          && (busy || Math.abs(+c.el.value - a.value) > 1e-4)) {
        c.el.value = a.value;
      }
    }
  }

  function paintStatus() {
    if (!statusHost) return;
    if (snap?.error) {
      statusHost.innerHTML = `<div class="lv bad">
        <b>讀不到位置</b><div class="sub">${esc(snap.error)}</div></div>`;
      return;
    }
    const parts = [];

    // 後端種類 —— 「我以為在看實機,其實是模擬的」是這頁最貴的誤會,
    // 所以模擬模式一定要在最上面講出來,而且不能是灰字小字。
    parts.push(snap?.kind === 'mock'
      ? `<div class="lv warn"><b>模擬位置</b><div class="sub">
           沒有連到天車控制中心,這些數字是算出來的。要接實機請在
           <code>.env</code> 設 <code>ACQUA_SETUP_CONTROLLER</code>。</div></div>`
      : `<div class="lv ok"><b>實機連線</b><div class="sub">位置由天車控制中心回報</div></div>`);

    // 裝置狀態
    const devs = Object.entries(snap?.devices || {});
    if (devs.length) {
      const bad = devs.filter(([, d]) => d.status !== 'online');
      parts.push(`<div class="devs">${devs.map(([pi, d]) => {
        const [cls, text] = DEV_TEXT[d.status] || DEV_TEXT.unknown;
        return `<span class="dev ${cls}" title="${esc(pi)} — ${esc(text)}${
          d.note ? ' ・ ' + esc(d.note) : ''}">${esc(pi.replace(/^pi-/, ''))}</span>`;
      }).join('')}</div>`);
      if (bad.length) {
        parts.push(`<div class="lvnote">${bad.length} 台裝置不在線上 ——
          那些軸移不動。連不上的原因請看天車控制中心那一頁。</div>`);
      }
    }

    // 移動作業
    const job = snap?.job;
    if (job && ['running', 'aborting'].includes(job.state)) {
      const step = job.steps[job.index] || job.steps[job.steps.length - 1];
      const pct = Math.round((job.index / job.steps.length) * 100);
      parts.push(`<div class="lv job">
        <b>${job.state === 'aborting' ? '正在收尾' : '移動中'}</b>
        <div class="sub">${esc(step?.label || '')}
          ${step ? `${fmt.by(step.unit)(step.from)} → ${fmt.by(step.unit)(step.to)}` : ''}</div>
        <div class="pb"><i style="width:${pct}%"></i></div>
        <div class="sub">${job.steps.length > 1
          ? `第 ${job.index + 1} / ${job.steps.length} 根軸 ・ ` : ''}
          預估共 ${fmt.secs(job.eta)}</div>
        <button class="wide danger" id="lv-stop">停止後續動作</button>
        <div class="sub">停止只會取消還沒送出去的軸。<b>正在走的那一段機構會走完</b> ——
          韌體沒有中止指令。</div>
      </div>`);
    } else if (job && job.state === 'error') {
      parts.push(`<div class="lv bad"><b>移動失敗</b>
        <div class="sub">${esc(job.error || '')}</div></div>`);
    } else if (job && job.state === 'aborted') {
      parts.push(`<div class="lv warn"><b>已中止</b>
        <div class="sub">${job.steps.filter((s) => s.state === 'skipped').length}
          根軸沒有移動</div></div>`);
    }

    // 行程對不對得上 —— 後端與 spec.js 各存一份,不一致要看得見
    if (manifest?.mismatch?.length) {
      parts.push(`<div class="lv bad"><b>行程設定不一致</b><div class="sub">
        ${manifest.mismatch.map(esc).join('<br>')}<br>
        3D 的 <code>spec.js</code> 與後端 <code>acqua/crane.py</code> 對不上。
        實際會以後端為準(機構安全)。</div></div>`);
    }

    statusHost.innerHTML = parts.join('');
    const stop = statusHost.querySelector('#lv-stop');
    if (stop) stop.onclick = doStop;
  }

  // ── 使用者拉了拉桿 ──────────────────────────────
  /**
   * 拉桿放手後叫這個。**這裡不會動任何 3D 物件** —— 只問要不要移動。
   * 取消就把拉桿撥回實機的位置。
   */
  async function requestMove(id, target) {
    const c = controls[id];
    const cur = wanted[id];
    if (cur === undefined) { toast('還沒讀到這根軸的位置', 'bad'); return; }
    if (Math.abs(target - cur) < 1e-4) return;

    if (snap?.job && ['running', 'aborting'].includes(snap.job.state)) {
      toast('已經有軸在移動,等它走完', 'warn');
      c.el.value = cur; paint(); return;
    }

    const ax = manifest?.byId?.[id];
    const dist = Math.abs(target - cur);
    const secs = ax ? dist / ax.speed : null;
    const f = c.format;

    pendingId = id;
    paint();
    const yes = await confirmBox({
      title: '確定要移動這個裝置嗎?',
      html: `
        <div class="mv">
          <div class="mvname">${esc(c.label)}</div>
          <div class="mvrow">
            <span class="from">${f(cur)}</span>
            <span class="arrow">→</span>
            <span class="to">${f(target)}</span>
          </div>
          <div class="mvmeta">
            移動距離 <b>${c.unit === 'deg' ? dist.toFixed(1) + '°'
              : (dist * 1000).toFixed(0) + ' mm'}</b>
            ${secs !== null ? ` ・ 預估 <b>${fmt.secs(secs)}</b>` : ''}
            ${ax ? ` ・ 裝置 <b>${esc(ax.pi)}</b>` : ''}
          </div>
          ${ax ? `<div class="mvcmd">送出的指令:<code>${esc(ax.ch)}M,${
            ax.unit === 'deg' ? Math.round(target)
              : Math.round((target - ax.min) * 1000)}</code></div>` : ''}
        </div>
        <div class="bxnote warn">機構會真的動起來。按下確定之後<b>沒有辦法中途叫停</b> ——
          韌體沒有中止指令,只能等它走完。先確認行程上沒有人、沒有線材。</div>`,
      ok: '確定,開始移動',
      cancel: '不要動',
    });
    pendingId = null;

    if (!yes) { c.el.value = cur; paint(); return; }

    const r = await POST('/api/room/move', { axis: id, target });
    if (!r.ok) {
      toast(r.error || '移動指令送不出去', 'bad');
      c.el.value = cur;
    }
    poll();     // 馬上刷一次,讓進度條立刻出現而不是等到下一輪
  }

  async function doStop() {
    const yes = await confirmBox({
      title: '停止後續動作?',
      html: `<div class="bxnote warn">只會取消<b>還沒送出去</b>的那幾根軸。
        <b>正在走的那一段機構會走完</b> —— 韌體沒有中止指令。
        真的要立刻停下來只能斷電。</div>`,
      ok: '停止後續動作', danger: true, cancel: '繼續移動',
    });
    if (!yes) return;
    const r = await POST('/api/room/stop');
    toast(r.ok ? '已取消後續軸(正在走的那一段仍會走完)' : '停止失敗',
      r.ok ? 'warn' : 'bad');
    poll();
  }

  /** 把一整組擺位送去實機。moves = {id: value} */
  async function applySetup(axes, label) {
    const rows = Object.entries(axes)
      .filter(([id]) => controls[id])
      .map(([id, v]) => ({ id, v, c: controls[id], cur: wanted[id] }))
      .filter((r) => r.cur === undefined || Math.abs(r.v - r.cur) > 1e-3);

    if (!rows.length) { toast('每一根軸都已經在位置上了'); return; }

    const total = rows.reduce((acc, r) => {
      const ax = manifest?.byId?.[r.id];
      return acc + (ax ? Math.abs(r.v - (r.cur ?? r.v)) / ax.speed : 0);
    }, 0);

    const yes = await confirmBox({
      title: `要把「${label}」套用到實機嗎?`,
      html: `
        <div class="bxnote">會<b>依序</b>移動下面 ${rows.length} 根軸,一次一根。
          預估共 ${fmt.secs(total)}。</div>
        <div class="mvlist">${rows.map((r) => `<div>
          <span>${esc(r.c.label)}</span>
          <span>${r.cur === undefined ? '?' : r.c.format(r.cur)} → <b>${r.c.format(r.v)}</b></span>
        </div>`).join('')}</div>
        <div class="bxnote warn">機構會真的動起來,而且沒辦法中途叫停個別軸。
          先確認房間裡沒有人。</div>`,
      ok: `開始移動 ${rows.length} 根軸`, cancel: '不要動',
    });
    if (!yes) return;

    const r = await POST('/api/room/apply',
      { axes: Object.fromEntries(rows.map((x) => [x.id, x.v])), label });
    if (!r.ok) { toast(r.error || '送不出去', 'bad'); return; }
    if (!r.job) { toast(r.note || '不需要移動'); return; }
    poll();
  }

  /**
   * 探一次實機,**不啟動輪詢**。切到即時模式之前用它,好在確認框上先講
   * 清楚「現在到底抓不抓得到位置」—— 切過去才發現讀不到,那個資訊來得太晚。
   *
   * 回 { state, kind, total, estimated, offline, error }
   *   state: 'live'(真的連上) | 'mock'(模擬) | 'error'(讀不到)
   */
  async function probe() {
    try {
      const s = await GET('/api/room/live');
      const axes = Object.entries(s.axes || {}).filter(([id]) => controls[id]);
      const devs = Object.values(s.devices || {});
      return {
        state: s.kind === 'mock' ? 'mock' : 'live',
        kind: s.kind,
        total: axes.length,
        estimated: axes.filter(([, a]) => a.estimated).length,
        offline: devs.filter((d) => d.status !== 'online').length,
        devices: devs.length,
        busy: !!(s.job && ['running', 'aborting'].includes(s.job.state)),
      };
    } catch (e) {
      return { state: 'error', error: String(e.message || e) };
    }
  }

  // ── 開關 ────────────────────────────────────────
  async function enable() {
    if (on) return;
    on = true;
    if (!manifest) await loadManifest();
    await poll();
  }

  function disable() {
    on = false;
    gen++;                       // 讓還在飛的那一次回來之後不要再排下一輪
    clearTimeout(timer);
    timer = null;
    pendingId = null;
    if (statusHost) statusHost.innerHTML = '';
    // 即時模式專屬的樣式要清掉:est 是「這個值是推估的」、moving 是
    // 「這根軸正在動」。回到設定模式兩者都不再成立,留著會誤導。
    for (const c of Object.values(controls)) {
      c.out.classList.remove('est');
      c.wrap.classList.remove('moving');
      c.tgt.hidden = true;
      c.el.disabled = false;
    }
  }

  /**
   * 拿後端的軸清單,順便跟 spec.js 的行程對一次。
   *
   * 兩邊刻意各存一份(後端不能拿瀏覽器送來的範圍當行程上限),所以一定要
   * 有個地方會在不一致時吵 —— 不然就變成兩份寫死的數字,沒人知道它們
   * 已經不一樣了。
   */
  async function loadManifest() {
    try {
      const m = await GET('/api/room/axes');
      const byId = Object.fromEntries((m.axes || []).map((a) => [a.id, a]));
      const mismatch = [];
      for (const [id, c] of Object.entries(controls)) {
        const a = byId[id];
        if (!a) { mismatch.push(`${id}:後端沒有這根軸`); continue; }
        const near = (x, y) => Math.abs(x - y) < 1e-6;
        if (!near(a.min, c.range.min) || !near(a.max, c.range.max)) {
          mismatch.push(`${id}:3D ${c.range.min}~${c.range.max} / `
            + `後端 ${a.min}~${a.max}`);
        }
      }
      for (const a of m.axes || []) {
        if (!controls[a.id]) mismatch.push(`${a.id}:3D 沒有這根軸的控制項`);
      }
      manifest = { byId, mismatch, backend: m.backend };
    } catch (e) {
      manifest = { byId: {}, mismatch: [`讀不到後端軸清單:${e.message || e}`] };
    }
  }

  return { enable, disable, tick, requestMove, applySetup, poll, probe,
           get snapshot() { return snap; },
           get positions() { return { ...wanted }; },
           get busy() {
             return !!(snap?.job && ['running', 'aborting'].includes(snap.job.state));
           } };
}

/**
 * 小工具:對話框、格式化、提示條。
 *
 * 為什麼不用 window.confirm():即時模式的確認框要講的東西比一行字多 ——
 * 哪一根軸、從哪到哪、走多遠、大概幾秒、送給韌體的是哪一條指令。
 * 這些全塞進 confirm() 的純文字裡沒人會讀;而且 confirm() 會凍住整個
 * 頁面,3D 的 render loop 也跟著停,按下去之前畫面是死的。
 */

// ── 格式化 ──────────────────────────────────────
export const fmt = {
  /** 位置:帶正負號,對齊用固定兩位 */
  pos: (v) => `${v >= 0 ? '+' : ''}${v.toFixed(2)} m`,
  len: (v) => `${v.toFixed(2)} m`,
  deg: (v) => `${v.toFixed(1)}°`,
  /** 依單位挑一個 */
  by: (unit) => (unit === 'deg' ? fmt.deg : fmt.len),
  /** 秒數講成人看得懂的 */
  secs: (s) => (s < 60 ? `${Math.round(s)} 秒`
    : `${Math.floor(s / 60)} 分 ${Math.round(s % 60)} 秒`),
};

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ── 取 JSON ─────────────────────────────────────
/**
 * fetch + JSON,但**認得出後端回的不是 JSON**。
 *
 * 為什麼要特別處理:這一頁的 JS 是 Flask 直接從磁碟送的靜態檔,改完重整
 * 就生效;但 API 路由是在 Flask 行程裡註冊的,**要重啟才有**。所以很容易
 * 出現「前端已經是新的、後端還是舊的」——新前端打新 API,舊後端回一頁
 * 404 的 HTML,`r.json()` 就丟出 `Unexpected token '<'`。
 *
 * 那個訊息完全看不出發生什麼事。這裡把它翻成「重開 app.py」。
 */
export async function jsonFetch(url, opts) {
  let r;
  try {
    r = await fetch(url, opts);
  } catch (e) {
    throw new Error(`連不到 ${url}(伺服器沒在跑?)`);
  }
  const text = await r.text();
  try {
    return JSON.parse(text);
  } catch {
    if (/^\s*<(!doctype|html)/i.test(text)) {
      throw new Error(r.status === 404
        ? `後端沒有 ${url} 這支 API —— 伺服器還是舊的,重開 app.py 就會有了。`
        : `後端回了一頁 HTML 而不是 JSON(HTTP ${r.status})`);
    }
    throw new Error(`後端回的不是 JSON(HTTP ${r.status})`);
  }
}

// ── 對話框 ──────────────────────────────────────
let openOv = null;

function shell(inner) {
  const ov = document.createElement('div');
  ov.className = 'ov on';
  ov.innerHTML = `<div class="bx">${inner}</div>`;
  document.body.appendChild(ov);
  openOv = ov;
  return ov;
}

function teardown(ov, onKey) {
  document.removeEventListener('keydown', onKey);
  ov.remove();
  if (openOv === ov) openOv = null;
}

/**
 * 確認框。回傳 Promise<boolean>。
 *
 * @param title    標題
 * @param html     內容(已轉義的 HTML)
 * @param ok       確認鈕文字
 * @param danger   確認鈕要不要用警示色
 */
export function confirmBox({ title, html = '', ok = '確定', cancel = '取消',
                             danger = false } = {}) {
  return new Promise((resolve) => {
    const ov = shell(`
      <h3>${esc(title)}</h3>
      <div class="bxbody">${html}</div>
      <div class="acts">
        <button class="ghost" data-a="no">${esc(cancel)}</button>
        <button class="${danger ? 'danger' : 'primary'}" data-a="yes">${esc(ok)}</button>
      </div>`);

    const done = (v) => { teardown(ov, onKey); resolve(v); };
    const onKey = (e) => {
      if (e.key === 'Escape') done(false);
      // Enter 送出 —— 但這個框可能是「要不要移動機構」,所以焦點先給取消,
      // 按 Enter 才是明確的確認動作(見下面的 focus())
      if (e.key === 'Enter') done(true);
    };
    document.addEventListener('keydown', onKey);
    ov.querySelector('[data-a="no"]').onclick = () => done(false);
    ov.querySelector('[data-a="yes"]').onclick = () => done(true);
    ov.onclick = (e) => { if (e.target === ov) done(false); };
    ov.querySelector('[data-a="yes"]').focus();
  });
}

/**
 * 表單框。fields = [{key, label, placeholder, value, textarea, required}]
 * 回傳 Promise<{key: value} | null>(取消是 null)。
 */
export function formBox({ title, note = '', fields = [], ok = '儲存' } = {}) {
  return new Promise((resolve) => {
    const rows = fields.map((f) => `
      <label>${esc(f.label)}${f.required ? ' <span class="req">*</span>' : ''}</label>
      ${f.textarea
        ? `<textarea rows="3" data-k="${esc(f.key)}"
             placeholder="${esc(f.placeholder || '')}">${esc(f.value || '')}</textarea>`
        : `<input type="text" data-k="${esc(f.key)}"
             placeholder="${esc(f.placeholder || '')}" value="${esc(f.value || '')}">`}`).join('');

    const ov = shell(`
      <h3>${esc(title)}</h3>
      ${note ? `<div class="bxnote">${note}</div>` : ''}
      ${rows}
      <div class="err" style="display:none"></div>
      <div class="acts">
        <button class="ghost" data-a="no">取消</button>
        <button class="primary" data-a="yes">${esc(ok)}</button>
      </div>`);

    const done = (v) => { teardown(ov, onKey); resolve(v); };
    const collect = () => {
      const out = {};
      ov.querySelectorAll('[data-k]').forEach((el) => { out[el.dataset.k] = el.value.trim(); });
      const missing = fields.filter((f) => f.required && !out[f.key]);
      if (missing.length) {
        const err = ov.querySelector('.err');
        err.textContent = `請填「${missing[0].label}」`;
        err.style.display = '';
        ov.querySelector(`[data-k="${missing[0].key}"]`).focus();
        return null;
      }
      return out;
    };
    const submit = () => { const v = collect(); if (v) done(v); };

    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      // textarea 裡的 Enter 是換行,不能當送出
      if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') submit();
    };
    document.addEventListener('keydown', onKey);
    ov.querySelector('[data-a="no"]').onclick = () => done(null);
    ov.querySelector('[data-a="yes"]').onclick = submit;
    ov.onclick = (e) => { if (e.target === ov) done(null); };
    ov.querySelector('[data-k]')?.focus();
  });
}

/** 一閃即逝的提示。成功/失敗都用這個,不要用 alert() 打斷 3D。 */
export function toast(msg, kind = 'ok', ms = 3200) {
  let host = document.querySelector('#toasts');
  if (!host) {
    host = document.createElement('div');
    host.id = 'toasts';
    document.body.appendChild(host);
  }
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 260); }, ms);
}

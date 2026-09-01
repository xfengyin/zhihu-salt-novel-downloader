'use strict';
/* 盐选书房 v5 · 原生单页应用（ES2019，无构建、无外部依赖）
 *
 * 对接 docs/ARCHITECTURE_SPEC.md §2.14 的 API 契约：
 *   GET    /api/health                 -> {ok, version}
 *   GET    /api/cookies                -> {has_cookie, z_c0, zse_ck, d_c0}
 *   POST   /api/qrcode                 -> {token, image_url}
 *   GET    /api/qrcode/{t}/status      -> {status, user_id, error}
 *   POST   /api/cookies/import         -> {raw}
 *   DELETE /api/cookies
 *   POST   /api/download               -> {url, format, resume, rate_limit} -> {task_id, status}
 *                                        （rate_limit 是 §2.14 之外的增强字段；服务端 422 时自动退回最小集重试）
 *   GET    /api/tasks                  -> 摘要列表（Task.snapshot() 数组）
 *   GET    /api/tasks/{id}             -> 详情（含 progress {current,total,title} 与 files）
 *   GET    /api/tasks/{id}/events      -> SSE，匿名 data 帧 = ProgressEvent.to_dict()，终态后 data: [DONE]
 *   GET    /api/files/{task_id}/{filename}
 *                                        （filename 只认 basename：服务端按白名单精确查表）
 *   GET    /api/shelf                  -> ShelfBook 列表
 *   POST   /api/shelf/{id}/update      -> 追更任务
 *   DELETE /api/shelf/{id}
 */
(function () {
  /* ================= 通用工具 ================= */

  function $(sel) { return document.querySelector(sel); }
  function $all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }

  /** 所有用户内容（书名/章节名/文件名/错误消息）必须经此函数再进 innerHTML。 */
  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function clamp(n, lo, hi) {
    n = Number(n);
    if (!isFinite(n)) { return lo; }
    return Math.min(hi, Math.max(lo, n));
  }

  function percent(current, total) {
    if (!total || total <= 0) { return 0; }
    return clamp(Math.floor((current / total) * 100), 0, 100);
  }

  /** 取路径最后一段：后端 files 可能回传绝对路径，展示与下载都只要文件名。 */
  function baseName(p) {
    var s = String(p === null || p === undefined ? '' : p);
    var parts = s.split(/[\\/]/);
    return parts[parts.length - 1] || s;
  }

  function fileHref(taskId, filename) {
    return '/api/files/' + encodeURIComponent(taskId) + '/' + encodeURIComponent(baseName(filename));
  }

  function fmtTime(iso) {
    var s = String(iso || '');
    if (!s) { return '—'; }
    var d = new Date(s);
    if (isNaN(d.getTime())) { return s; }
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  /** 统一的 JSON 请求：非 2xx 时把 {detail|message|error} 转成中文可读错误。 */
  async function api(path, options) {
    var opts = options || {};
    var headers = opts.headers || {};
    if (opts.body !== undefined && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }
    var resp;
    try {
      resp = await fetch(path, {
        method: opts.method || 'GET',
        headers: headers,
        body: opts.body
      });
    } catch (err) {
      throw new Error('连不上本机服务，请确认下载器窗口还开着。');
    }
    var text = await resp.text();
    var data = null;
    if (text) {
      try { data = JSON.parse(text); } catch (e) { data = null; }
    }
    if (!resp.ok) {
      var detail = null;
      if (data) {
        if (typeof data.detail === 'string') { detail = data.detail; }
        else if (Array.isArray(data.detail) && data.detail.length) {
          detail = data.detail.map(function (d) { return (d && (d.msg || d.message)) || ''; }).filter(Boolean).join('；');
        } else if (data.message) { detail = data.message; }
        else if (data.error) { detail = data.error; }
      }
      if (!detail) { detail = '服务返回错误（HTTP ' + resp.status + '），请重试。'; }
      var e = new Error(detail);
      e.status = resp.status;
      throw e;
    }
    return data;
  }

  /* ================= 轻提示 toast ================= */

  var toastTimer = 3600;

  function toast(kind, text) {
    var region = $('#toast-region');
    if (!region) { return; }
    var el = document.createElement('div');
    el.className = 'toast toast-' + kind;
    el.setAttribute('role', 'status');
    el.textContent = text;
    region.appendChild(el);
    window.setTimeout(function () {
      el.classList.add('toast-out');
      window.setTimeout(function () { if (el.parentNode) { el.parentNode.removeChild(el); } }, 400);
    }, toastTimer);
  }

  /* retry 文案是否已自带「第 N 次重试」前缀 */
  var RETRY_HEAD = /^第\s*\d+\s*次重试/;
  /* 重试提示的存活时间：E1 的退避最长 4s，15s 还等不到后续事件就说明通道断了，
     提示必须自己收掉——挂着不走会让用户以为一直卡着或已经失败。 */
  var RETRY_TTL = 15000;

  /* ================= 主题 ================= */

  var THEME_KEY = 'zhihu-v5-theme';

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    var btn = $('#theme-toggle');
    if (btn) {
      btn.textContent = theme === 'dark' ? '☀' : '☾';
      btn.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
      btn.setAttribute('title', theme === 'dark' ? '切换到浅色' : '切换到深色');
    }
  }

  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem(THEME_KEY); } catch (e) { saved = null; }
    var preferred = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    applyTheme(saved || preferred);
  }

  function toggleTheme() {
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* 隐私模式忽略 */ }
    applyTheme(next);
  }

  /* ================= 焦点陷阱（模态/抽屉共用） ================= */

  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]),' +
    'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function trapFocus(container, event) {
    var items = $all(FOCUSABLE).filter(function (el) {
      return container.contains(el) && el.offsetParent !== null;
    });
    if (!items.length) { return; }
    var first = items[0];
    var last = items[items.length - 1];
    var active = document.activeElement;
    if (event.shiftKey && (active === first || !container.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  /* ================= 登录态胶囊 ================= */

  var cookieState = { has_cookie: false, z_c0: false, zse_ck: false, d_c0: false, loaded: false };

  async function refreshCookieStatus() {
    var pill = $('#cookie-pill');
    var text = $('#cookie-pill-text');
    try {
      var data = await api('/api/cookies');
      cookieState = {
        has_cookie: !!(data && data.has_cookie),
        z_c0: !!(data && data.z_c0),
        zse_ck: !!(data && data.zse_ck),
        d_c0: !!(data && data.d_c0),
        loaded: true
      };
    } catch (err) {
      cookieState = { has_cookie: false, z_c0: false, zse_ck: false, d_c0: false, loaded: false };
      if (pill) { pill.className = 'status-pill status-unknown'; }
      if (text) { text.textContent = '状态未知'; }
      renderCookieDetail();
      return;
    }
    if (pill) {
      if (!cookieState.has_cookie) { pill.className = 'status-pill status-off'; }
      else if (!cookieState.d_c0) { pill.className = 'status-pill status-warn'; }
      else { pill.className = 'status-pill status-on'; }
    }
    if (text) {
      if (!cookieState.has_cookie) { text.textContent = '未登录'; }
      else if (!cookieState.d_c0) { text.textContent = '签名 Cookie 缺失'; }
      else { text.textContent = '已登录'; }
    }
    var hint = $('#login-hint');
    if (hint) { hint.hidden = cookieState.has_cookie && cookieState.d_c0; }
    if (pill) {
      // 悬浮说明三个关键 Cookie 的实际状态（值不回传，只有布尔）
      pill.setAttribute('title', '登录凭证 z_c0：' + (cookieState.z_c0 ? '已导入' : '缺失') +
        ' ｜ 安全字段 zse_ck：' + (cookieState.zse_ck ? '已导入' : '缺失') +
        ' ｜ 签名 Cookie d_c0：' + (cookieState.d_c0 ? '已导入' : '缺失') + '（点开设定可手动导入）');
      pill.setAttribute('aria-label', (text ? text.textContent : '登录状态') + '，点开设定查看登录详情');
    }
    renderCookieDetail();
  }

  function renderCookieDetail() {
    var list = $('#cookie-detail');
    if (!list) { return; }
    var rows = [
      { key: 'z_c0', name: '登录凭证 z_c0', ok: cookieState.z_c0, need: '必需' },
      { key: 'zse_ck', name: '安全字段 zse_ck', ok: cookieState.zse_ck, need: '建议' },
      { key: 'd_c0', name: '签名 Cookie d_c0', ok: cookieState.d_c0, need: '必需' }
    ];
    list.innerHTML = rows.map(function (r) {
      return '<li class="cookie-row">' +
        '<span class="cookie-name">' + escapeHtml(r.name) + '</span>' +
        '<span class="cookie-need">' + escapeHtml(r.need) + '</span>' +
        '<span class="cookie-flag ' + (r.ok ? 'ok' : 'bad') + '">' + (r.ok ? '已导入' : '缺失') + '</span>' +
        '</li>';
    }).join('');
  }

  /* ================= 扫码登录模态 ================= */

  var qr = { token: null, imageUrl: '', timer: null, open: false, lastFocus: null };

  var QR_TEXT = {
    loading: ['正在获取二维码…', '稍等，马上就好。'],
    waiting: ['等待扫码', '打开知乎 App 扫描左侧二维码。'],
    scanned: ['已扫码', '请在手机上点「确认登录」。'],
    confirmed: ['登录成功', 'Cookie 已保存到本机，可以开始下载了。'],
    error: ['登录失败', '请重试，或改用设置里的「手动导入 Cookie」。'],
    expired: ['二维码已过期', '点下方「重新获取二维码」再来一次。']
  };

  function qrIcon(state) {
    if (state === 'loading') { return '<span class="spinner" aria-hidden="true"></span>'; }
    if (state === 'confirmed') { return '<span class="qr-mark ok" aria-hidden="true">✓</span>'; }
    if (state === 'error') { return '<span class="qr-mark bad" aria-hidden="true">!</span>'; }
    if (state === 'expired') { return '<span class="qr-mark warn" aria-hidden="true">↻</span>'; }
    return '';
  }

  function renderQr(state, extra) {
    var body = $('#qr-body');
    if (!body) { return; }
    var pair = QR_TEXT[state] || QR_TEXT.waiting;
    var kind = (state === 'waiting' || state === 'scanned') ? 'img' : state;
    var old = body.querySelector('.qr-frame');
    // 同一帧（waiting → scanned）只换文字，不重建 <img>，否则二维码每 2 秒被重载一次
    if (old && old.getAttribute('data-kind') === kind) {
      var t = body.querySelector('.qr-state-text');
      var h = body.querySelector('.qr-state-hint');
      if (t) { t.textContent = pair[0]; }
      if (h) { h.textContent = extra || pair[1]; }
      return;
    }
    var html = '<div class="qr-inner">';
    if (kind === 'img') {
      html += '<div class="qr-frame" data-kind="img"><img id="qr-img" alt="知乎登录二维码" src="' +
        escapeHtml(qr.imageUrl) + '" /></div>';
    } else {
      html += '<div class="qr-frame qr-frame-state" data-kind="' + escapeHtml(kind) + '">' + qrIcon(state) + '</div>';
    }
    html += '<div class="qr-status">' +
      '<p class="qr-state-text">' + escapeHtml(pair[0]) + '</p>' +
      '<p class="qr-state-hint">' + escapeHtml(extra || pair[1]) + '</p>' +
      '</div></div>';
    body.innerHTML = html;
    var img = $('#qr-img');
    if (img) {
      img.onerror = function () {
        // 知乎直连图片失败时退回本机代理端点 GET /api/qrcode/{token}/image
        if (img.dataset.fallback !== '1' && qr.token) {
          img.dataset.fallback = '1';
          img.src = '/api/qrcode/' + encodeURIComponent(qr.token) + '/image';
        } else {
          stopQrPolling();
          showQrState('expired');
        }
      };
    }
  }

  function showQrState(state, extra) {
    renderQr(state, extra);
    var retry = $('#qr-retry');
    if (retry) { retry.hidden = !(state === 'expired' || state === 'error'); }
  }

  function stopQrPolling() {
    if (qr.timer !== null) { window.clearInterval(qr.timer); qr.timer = null; }
  }

  function startQrPolling() {
    stopQrPolling();
    qr.timer = window.setInterval(pollQr, 2000);
  }

  async function pollQr() {
    if (!qr.token || !qr.open) { return; }
    if (document.hidden) { return; }   // 页签隐藏时不打扰知乎接口
    try {
      var data = await api('/api/qrcode/' + encodeURIComponent(qr.token) + '/status');
      handleQrStatus(data);
    } catch (err) {
      stopQrPolling();
      showQrState('expired', err.message);
    }
  }

  function handleQrStatus(data) {
    var status = (data && data.status) || 'waiting';
    if (status === 'waiting') { showQrState('waiting'); }
    else if (status === 'scanned') { showQrState('scanned'); }
    else if (status === 'confirmed') {
      stopQrPolling();
      showQrState('confirmed');
      refreshCookieStatus();
      toast('ok', '登录成功');
      window.setTimeout(closeQr, 1400);
    } else if (status === 'error') {
      stopQrPolling();
      showQrState('error', (data && data.error) || '知乎返回登录失败，请重试。');
    } else if (status === 'expired') {
      stopQrPolling();
      showQrState('expired');
    } else {
      showQrState('waiting');
    }
  }

  async function createQr() {
    stopQrPolling();
    qr.token = null;
    qr.imageUrl = '';
    showQrState('loading');
    try {
      var data = await api('/api/qrcode', { method: 'POST', body: '{}' });
      if (!data || !data.token) { throw new Error('服务没有返回二维码，请重试。'); }
      qr.token = data.token;
      qr.imageUrl = data.image_url || ('/api/qrcode/' + encodeURIComponent(data.token) + '/image');
      showQrState('waiting');
      startQrPolling();
    } catch (err) {
      showQrState('error', err.message);
    }
  }

  function openQr() {
    var modal = $('#qr-modal');
    if (!modal || qr.open) { return; }
    if (settings.open) { closeSettings(); }
    qr.open = true;
    qr.lastFocus = document.activeElement;
    modal.hidden = false;
    document.body.classList.add('overlay-open');
    var closeBtn = modal.querySelector('.modal-close');
    if (closeBtn) { closeBtn.focus(); }
    createQr();
  }

  function closeQr() {
    var modal = $('#qr-modal');
    if (!modal) { return; }
    stopQrPolling();
    qr.open = false;
    qr.token = null;
    modal.hidden = true;
    var body = $('#qr-body');
    if (body) { body.innerHTML = ''; }
    if (!anyOverlayOpen()) { document.body.classList.remove('overlay-open'); }
    if (qr.lastFocus && qr.lastFocus.focus) { qr.lastFocus.focus(); }
  }

  function anyOverlayOpen() {
    var m = $('#qr-modal');
    var s = $('#settings-drawer');
    return Boolean((m && !m.hidden) || (s && !s.hidden));
  }

  /* ================= 下载表单 ================= */

  /** 前端先拦一道：主机名必须是 zhihu.com 或其子域（服务端为准，仍会再校验）。 */
  function zhihuUrlError(raw) {
    var url = String(raw || '').trim();
    if (!url) { return '请先粘贴知乎链接。'; }
    if (!/^https?:/i.test(url)) { return '链接要以 http:// 或 https:// 开头，请从知乎页面重新复制。'; }
    // 取主机名：去掉协议、路径、query、锚点、端口（不用含转义斜杠的正则，便于静态检查）
    var host = url.toLowerCase().split('//')[1] || '';
    host = host.split('/')[0].split('?')[0].split('#')[0].split(':')[0];
    if (host !== 'zhihu.com' && !/\.zhihu\.com$/.test(host)) {
      return '只支持知乎（zhihu.com）的链接，请检查是否复制错了网址。';
    }
    return '';
  }

  function showUrlError(msg) {
    var el = $('#url-error');
    var input = $('#url-input');
    if (!el) { return; }
    el.hidden = !msg;
    el.textContent = msg;
    if (input) { input.setAttribute('aria-invalid', msg ? 'true' : 'false'); }
  }

  function showFormMsg(kind, text) {
    var el = $('#download-msg');
    if (!el) { return; }
    el.hidden = !text;
    el.className = 'form-msg form-msg-' + kind;
    el.textContent = text || '';
  }

  async function submitDownload(event) {
    event.preventDefault();
    var raw = ($('#url-input') && $('#url-input').value) || '';
    var bad = zhihuUrlError(raw);
    showUrlError(bad);
    if (bad) {
      showFormMsg('bad', '链接不对，没法开始。');
      if ($('#url-input')) { $('#url-input').focus(); }
      return;
    }
    var rawRate = $('#rate-input') ? String($('#rate-input').value).trim() : '';
    // 空着或填了非法值时回落到默认 2，避免把 0（不限速）当成用户意图发给服务端
    var rate = (rawRate === '' || isNaN(Number(rawRate))) ? 2 : clamp(Number(rawRate), 0, 20);
    var payload = {
      url: String(raw).trim(),
      format: ($('#format-select') && $('#format-select').value) || 'epub',
      resume: !!($('#resume-input') && $('#resume-input').checked),
      rate_limit: rate
    };
    var btn = $('#download-btn');
    if (btn) { btn.disabled = true; btn.textContent = '正在提交…'; }
    try {
      var data = null;
      try {
        data = await api('/api/download', { method: 'POST', body: JSON.stringify(payload) });
      } catch (err) {
        // §2.14 的 /api/download 只声明了 {url, format, resume}。限速是本地增强字段，
        // 若服务端因未知字段报 422，就退回契约最小集重试一次（不阻塞用户下载）。
        if (err.status !== 422) { throw err; }
        data = await api('/api/download', {
          method: 'POST',
          body: JSON.stringify({ url: payload.url, format: payload.format, resume: payload.resume })
        });
        toast('info', '这个版本不支持自定义限速，已按默认节奏（每秒 2 次）下载。');
      }
      var taskId = (data && (data.task_id || data.id)) || '';
      if (!taskId) { throw new Error('服务没有返回任务编号，请重试。'); }
      showFormMsg('ok', '任务已创建，正在下载…');
      toast('ok', '开始下载');
      trackTask(taskId);
      focusProgress(taskId);
      await refreshTasks();
    } catch (err) {
      showFormMsg('bad', err.message);
      toast('bad', err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '开始下载'; }
    }
  }

  /* ================= 任务数据归一化 ================= */

  var STATUS_TEXT = {
    pending: '排队中', running: '下载中', done: '已完成', error: '失败', cancelled: '已取消'
  };

  function normStatus(raw) {
    var s = String((raw && (raw.status || raw.state)) || 'pending').toLowerCase();
    if (s === 'success' || s === 'succeeded' || s === 'completed' || s === 'finished' || s === 'done') { return 'done'; }
    if (s === 'cancelled' || s === 'canceled') { return 'cancelled'; }
    if (s === 'failed' || s === 'error') { return 'error'; }
    if (s === 'running' || s === 'downloading' || s === 'in_progress') { return 'running'; }
    return 'pending';
  }

  /** 终态统一判定：done / error / cancelled 之后不再轮询、不再改标题。 */
  function isFinal(status) {
    return status === 'done' || status === 'error' || status === 'cancelled';
  }

  function normTask(raw) {
    var data = raw || {};
    var prog = data.progress || {};
    return {
      id: String(data.task_id || data.id || ''),
      status: normStatus(data),
      title: String(data.title || ''),
      url: String(data.url || ''),
      fmt: String(data.format || data.fmt || ''),
      current: Number(prog.current || data.current || 0) || 0,
      total: Number(prog.total || data.total || 0) || 0,
      chapter: String(prog.title || data.chapter || ''),
      error: String(data.error || data.message || ''),
      files: Array.isArray(data.files) ? data.files : []
    };
  }

  /* ================= 进度卡片（SSE + 轮询降级） ================= */

  var trackers = {};      // taskId -> {es, timer, pollOnly, snapshot}
  var focusedTask = '';

  function snapshotOf(taskId) {
    var t = trackers[taskId];
    return (t && t.snapshot) || null;
  }

  function ensureTracker(taskId) {
    if (!trackers[taskId]) {
      trackers[taskId] = {
        es: null, timer: null, watchdog: null, busy: false, lastRaw: '', gotEvent: false,
        pollOnly: false, stopped: false, finalSeen: false, snapshot: null
      };
    }
    return trackers[taskId];
  }

  function trackTask(taskId) {
    var t = ensureTracker(taskId);
    if (!t.snapshot) {
      t.snapshot = { id: taskId, status: 'running', title: '', url: '', current: 0, total: 0, chapter: '', error: '', files: [] };
    }
    t.stopped = false;   // 允许重新挂流（例如服务端把该任务又跑起来了）
    t.finalSeen = false;
    if (!t.es && !t.timer) { openStream(taskId, t); }
    return t;
  }

  function openStream(taskId, t) {
    var url = '/api/tasks/' + encodeURIComponent(taskId) + '/events';
    var es = null;
    try {
      es = new EventSource(url);
    } catch (err) {
      startPolling(taskId, t, true);
      return;
    }
    t.es = es;
    var handle = function (raw) {
      var text = String(raw === null || raw === undefined ? '' : raw).trim();
      if (text === '[DONE]') {
        // 服务端终态后的收尾哨兵：关流并向详情对账（拿到 files / 最终状态）
        t.gotEvent = true;
        t.finalSeen = true;
        closeStream(t);
        fetchTaskFiles(taskId);
        refreshTasks();
        refreshShelf();
        return;
      }
      var data = null;
      try { data = JSON.parse(text); } catch (e) { data = null; }
      if (!data || typeof data !== 'object') { return; }
      // 匿名事件会被 onmessage 与 addEventListener('message') 各投一次 → 按原文去重
      if (raw === t.lastRaw) { return; }
      t.lastRaw = raw;
      t.gotEvent = true;
      applyProgressEvent(taskId, data);
    };
    es.onmessage = function (ev) { handle(ev.data); };
    // 服务端若用命名事件（event: chapter 等）也一并接住；未知名字统一按 message 处理
    ['message', 'toc', 'chapter', 'retry', 'export', 'done', 'error',
     'progress', 'update', 'log', 'start', 'heartbeat'].forEach(function (kind) {
      es.addEventListener(kind, function (ev) { handle(ev.data); });
    });
    // 看门狗：连上了却迟迟收不到可解析的事件（事件名不合预期）→ 主动降级轮询
    t.watchdog = window.setTimeout(function () {
      t.watchdog = null;
      if (t.gotEvent || t.stopped || t.finalSeen) { return; }
      closeStream(t);
      startPolling(taskId, t, true);
    }, 12000);
    es.onerror = function () {
      if (t.stopped || t.finalSeen) {
        closeStream(t);   // 服务端在 done/error 后主动关流，属正常收尾，不要误降级
        return;
      }
      // 连接断开：关流，降级为 2s 轮询 GET /api/tasks/{id}
      closeStream(t);
      startPolling(taskId, t, true);
    };
  }

  function closeStream(t) {
    if (t.watchdog !== null) { window.clearTimeout(t.watchdog); t.watchdog = null; }
    if (t.es) {
      try { t.es.close(); } catch (e) { /* 忽略 */ }
      t.es = null;
    }
  }

  /** 只清定时器，保留 pollOnly 标记（页签隐藏时用，回来能恢复）。 */
  function stopPollingKeepFlag(t) {
    if (t.timer !== null) { window.clearInterval(t.timer); t.timer = null; }
  }

  function stopPolling(t) {
    stopPollingKeepFlag(t);
    t.pollOnly = false;
  }

  function startPolling(taskId, t, announce) {
    if (t.timer !== null) { return; }
    t.pollOnly = true;
    if (announce && focusedTask === taskId) { setConnBadge('poll'); }
    var tick = async function () {
      if (document.hidden || t.busy) { return; }   // 页签隐藏时暂停；一次只跑一个请求
      t.busy = true;
      try {
        var data = await api('/api/tasks/' + encodeURIComponent(taskId));
        applyTaskDetail(taskId, data);
        var st = normStatus(data);
        if (isFinal(st)) {
          stopTracker(taskId);
          refreshTasks();
          refreshShelf();
        }
      } catch (err) {
        if (err.status === 404) {
          stopTracker(taskId);
          dropTask(taskId);
          if (focusedTask === taskId) { hideProgress(); }
        }
      } finally {
        t.busy = false;
      }
    };
    tick();
    t.timer = window.setInterval(tick, 2000);
  }

  function stopTracker(taskId) {
    var t = trackers[taskId];
    if (!t) { return; }
    closeStream(t);
    stopPolling(t);
    t.stopped = true;
    t.finalSeen = true;
  }

  function applyTaskDetail(taskId, raw) {
    var task = normTask(raw);
    var t = ensureTracker(taskId);
    var snap = t.snapshot || { id: taskId, current: 0, total: 0, chapter: '', files: [], error: '', title: '', url: '', status: 'pending' };
    var wasFinal = snap.status === 'done' || snap.status === 'error';
    // 服务端详情可能滞后于 SSE：终态不被降级，进度不被拉回
    if (!wasFinal || task.status === 'done' || task.status === 'error') { snap.status = task.status; }
    snap.current = Math.max(snap.current || 0, task.current || 0);
    snap.total = Math.max(snap.total || 0, task.total || 0);
    snap.chapter = task.chapter || snap.chapter;
    snap.title = task.title || snap.title;
    snap.url = task.url || snap.url;
    snap.error = task.error || snap.error;
    if (task.files.length) { snap.files = task.files; }
    t.snapshot = snap;
    renderProgress(taskId);
    mergeTaskIntoList(snap);
  }

  /**
   * retry 事件的行内提示文案。E1 发来的 message 已是「第 N 次重试（Xs 后）：原因」，
   * 原样沿用（次数以服务端为准，不自己数）；万一前缀缺失就按本地计数补齐。
   */
  function retryHint(n, message) {
    var text = String(message || '').trim();
    if (RETRY_HEAD.test(text)) { return text; }
    return '第 ' + n + ' 次重试：' + (text || '这一章没成功，稍等，正在自动再试一次。');
  }

  /** ProgressEvent：{kind,current,total,title,message} —— SSE 事件体。 */
  function applyProgressEvent(taskId, ev) {
    var t = ensureTracker(taskId);
    var snap = t.snapshot || { id: taskId, status: 'running', title: '', url: '', current: 0, total: 0, chapter: '', error: '', files: [] };
    var kind = String(ev.kind || '');
    if (typeof ev.current === 'number') { snap.current = ev.current; }
    if (typeof ev.total === 'number' && ev.total > 0) { snap.total = ev.total; }
    if (ev.title) { snap.chapter = String(ev.title); }
    var message = String(ev.message || '');
    if (kind !== 'retry') { snap.retryText = ''; }

    if (kind === 'toc') {
      snap.status = 'running';
      pushLog(taskId, 'info', '共 ' + snap.total + ' 章，开始下载');
    } else if (kind === 'chapter') {
      snap.status = 'running';
    } else if (kind === 'retry') {
      // retry 不算失败：状态保持 running，只在进度卡挂一条黄色行内提示
      snap.status = 'running';
      snap.retries = (snap.retries || 0) + 1;
      snap.retryText = retryHint(snap.retries, message);
      snap.retryAt = Date.now();
      pushLog(taskId, 'warn', snap.retryText);
      // 兜底：之后一个事件都没有时（降级轮询拿不到 retry），到点自己消失
      window.setTimeout(function () { renderProgress(taskId); }, RETRY_TTL + 400);
    } else if (kind === 'export') {
      snap.status = 'running';
      pushLog(taskId, 'info', message || '正在生成文件…');
    } else if (kind === 'done') {
      snap.status = 'done';
      if (snap.total > 0) { snap.current = snap.total; }
      pushLog(taskId, 'ok', message || '下载完成');
      stopTracker(taskId);
      fetchTaskFiles(taskId);
      refreshShelf();
    } else if (kind === 'error') {
      snap.status = 'error';
      snap.error = message || '下载失败，请重试或检查登录状态。';
      pushLog(taskId, 'bad', snap.error);
      stopTracker(taskId);
    }
    t.snapshot = snap;
    renderProgress(taskId);
    mergeTaskIntoList(snap);
    if (kind === 'done' || kind === 'error') { refreshTasks(); }
  }

  /** done 事件体里没有文件列表（契约如此），完成后补拉一次详情拿 files。 */
  async function fetchTaskFiles(taskId) {
    try {
      var data = await api('/api/tasks/' + encodeURIComponent(taskId));
      applyTaskDetail(taskId, data);
    } catch (err) { /* 列表刷新时会再拿到 */ }
  }

  /* ================= 进度卡片渲染 ================= */

  var logs = {};   // taskId -> [{level,text}]

  function pushLog(taskId, level, text) {
    var arr = logs[taskId] || (logs[taskId] = []);
    if (arr.length && arr[arr.length - 1].text === text) { return; }
    arr.push({ level: level, text: text });
    if (arr.length > 6) { arr.shift(); }
  }

  function setConnBadge(mode) {
    var el = $('#prog-conn');
    if (!el) { return; }
    if (mode === 'poll') {
      el.className = 'conn-badge conn-poll';
      el.textContent = '实时连接中断，已改为每 2 秒查询';
      el.title = '进度通道断开，已自动降级为轮询。';
    } else {
      el.className = 'conn-badge conn-live';
      el.textContent = '实时更新中';
      el.title = '正在通过实时通道接收进度。';
    }
  }

  var BASE_TITLE = document.title;

  /** 切到别的浏览器标签页时也能从标题看到进度百分比。 */
  function updateTitle(snap) {
    if (!snap || isFinal(snap.status)) {
      document.title = BASE_TITLE;
      return;
    }
    var pct = percent(snap.current, snap.total);
    document.title = (pct > 0 ? '[' + pct + '%] ' : '[准备中] ') + BASE_TITLE;
  }

  function focusProgress(taskId) {
    focusedTask = taskId;
    var card = $('#progress-card');
    if (card) { card.hidden = false; }
    setConnBadge(trackers[taskId] && trackers[taskId].pollOnly ? 'poll' : 'live');
    renderProgress(taskId);
  }

  function hideProgress() {
    focusedTask = '';
    var card = $('#progress-card');
    if (card) { card.hidden = true; }
    document.title = BASE_TITLE;   // 收起后不要把百分比留在标签页标题上
  }

  function renderProgress(taskId) {
    if (!focusedTask || focusedTask !== taskId) { return; }
    var snap = snapshotOf(taskId);
    if (!snap) { return; }
    // 重试提示超时：必须在渲染其它元素之前收掉，否则章节行的黄色会晚一帧
    if (snap.retryText && snap.retryAt && (Date.now() - snap.retryAt) > RETRY_TTL) {
      snap.retryText = '';
    }
    var pct = percent(snap.current, snap.total);
    var fill = $('#prog-fill');
    var bar = $('#prog-bar');
    if (fill) { fill.style.width = pct + '%'; }
    if (bar) {
      bar.setAttribute('aria-valuenow', String(pct));
      bar.setAttribute('aria-valuetext', snap.current + ' / ' + (snap.total || '?') + ' 章');
      bar.className = 'bar' + (snap.status === 'done' ? ' bar-done'
        : snap.status === 'error' ? ' bar-error' : snap.status === 'cancelled' ? ' bar-cancelled' : '');
    }
    var count = $('#prog-count');
    if (count) { count.textContent = snap.current + ' / ' + (snap.total || '—'); }
    var pctEl = $('#prog-pct');
    if (pctEl) { pctEl.textContent = pct + '%'; }
    var book = $('#prog-book');
    if (book) { book.textContent = snap.title || snap.url || '正在解析目录…'; }
    var task = $('#prog-task');
    if (task) { task.textContent = '任务 ' + snap.id; }

    var chapter = $('#prog-chapter');
    if (chapter) {
      if (snap.status === 'done') { chapter.textContent = '全部完成，文件已生成。'; }
      else if (snap.status === 'cancelled') { chapter.textContent = '这个任务已停止。'; }
      else if (snap.status === 'error') { chapter.textContent = snap.error || '下载失败。'; }
      else if (snap.chapter) { chapter.textContent = '正在下载：' + snap.chapter; }
      else { chapter.textContent = '正在解析目录…'; }
      chapter.className = 'prog-chapter' +
        (snap.status === 'done' ? ' is-ok' : snap.status === 'error' ? ' is-bad'
          : snap.status === 'cancelled' ? ' is-warn' : snap.retryText ? ' is-warn' : '');
    }

    // 黄色行内提示：只在正在重试时出现，重试成功或超时后自动消失
    var hint = $('#prog-retry-hint');
    if (hint) {
      hint.hidden = !snap.retryText;
      if (snap.retryText) { hint.textContent = snap.retryText; }
    }

    var logEl = $('#prog-log');
    if (logEl) {
      var arr = logs[taskId] || [];
      logEl.innerHTML = arr.map(function (item) {
        return '<li class="log log-' + escapeHtml(item.level) + '">' + escapeHtml(item.text) + '</li>';
      }).join('');
    }

    var files = $('#prog-files');
    if (files) {
      if (snap.status === 'done' && snap.files && snap.files.length) {
        files.innerHTML = '<p class="file-title">下载好了，点文件即可保存：</p>' + snap.files.map(function (f) {
          return '<a class="file-link" href="' + escapeHtml(fileHref(taskId, f)) + '" download>⤓ ' + escapeHtml(baseName(f)) + '</a>';
        }).join('');
      } else {
        files.innerHTML = '';
      }
    }

    updateTitle(snap);

    var retryBtn = $('#prog-retry');
    if (retryBtn) {
      retryBtn.hidden = !(snap.status === 'error' || snap.status === 'cancelled');
      retryBtn.dataset.url = snap.url || '';
    }
  }

  /* ================= 任务列表 ================= */

  var taskList = [];      // 归一化后的摘要
  var refreshQueued = false;

  function mergeTaskIntoList(snap) {
    var found = false;
    for (var i = 0; i < taskList.length; i++) {
      if (taskList[i].id === snap.id) {
        taskList[i] = {
          id: snap.id, status: snap.status, title: snap.title || taskList[i].title,
          url: snap.url || taskList[i].url, fmt: taskList[i].fmt,
          current: snap.current, total: snap.total, chapter: snap.chapter,
          error: snap.error, retries: snap.retries || taskList[i].retries || 0,
          retryText: snap.retryText || '',
          files: snap.files && snap.files.length ? snap.files : taskList[i].files
        };
        found = true;
        break;
      }
    }
    if (!found && snap.id) {
      taskList.unshift({
        id: snap.id, status: snap.status, title: snap.title, url: snap.url, fmt: '',
        current: snap.current, total: snap.total, chapter: snap.chapter, error: snap.error, files: snap.files
      });
    }
    scheduleTaskRender();
    scheduleListRefresh();
  }

  /** SSE 驱动的列表刷新：合并本地快照，避免把刚收到的进度又覆盖回旧值。 */
  async function refreshTasks() {
    try {
      var data = await api('/api/tasks');
      var list = Array.isArray(data) ? data : (data && (data.tasks || data.items)) || [];
      var incoming = list.map(normTask).filter(function (t) { return t.id; });
      var merged = incoming.map(function (t) {
        var local = null;
        for (var i = 0; i < taskList.length; i++) { if (taskList[i].id === t.id) { local = taskList[i]; break; } }
        if (!local) { return t; }
        var snap = snapshotOf(t.id);
        if (snap) {
          t.current = Math.max(t.current, snap.current);
          t.total = t.total || snap.total;
          t.chapter = t.chapter || snap.chapter;
          t.files = (t.files && t.files.length) ? t.files : snap.files;
          t.retries = t.retries || snap.retries || 0;
          t.retryText = t.retryText || snap.retryText || '';
          if (isFinal(snap.status)) { t.status = snap.status; }
        }
        t.title = t.title || local.title;
        t.url = t.url || local.url;
        return t;
      });
      // 本地已有但服务端还没回的任务（刚创建）保留在最前
      var keep = taskList.filter(function (t) {
        return !merged.some(function (m) { return m.id === t.id; });
      });
      taskList = keep.concat(merged);
      renderTasks();
      // 有进行中的任务且没有跟踪器时补挂上
      taskList.forEach(function (t) {
        if (t.status === 'running' || t.status === 'pending') {
          var tr = trackers[t.id];
          if (!tr || (!tr.es && !tr.timer)) { trackTask(t.id); }
        }
      });
      fetchMissingTaskFiles();
    } catch (err) {
      var empty = $('#tasks-empty');
      if (empty && !taskList.length) {
        empty.hidden = false;
        empty.textContent = '任务列表加载失败：' + err.message;
      }
    }
  }

  var filesTried = {};   // taskId -> true，避免反复拉同一个任务的 files

  /** §2.14 只保证详情里有 progress；摘要可能不带 files，完成后补拉一次详情。 */
  function fetchMissingTaskFiles() {
    taskList.forEach(function (t) {
      if (t.status !== 'done' || (t.files && t.files.length) || filesTried[t.id]) { return; }
      filesTried[t.id] = true;
      api('/api/tasks/' + encodeURIComponent(t.id)).then(function (data) {
        var files = data && Array.isArray(data.files) ? data.files : [];
        if (!files.length) { return; }
        var tr = trackers[t.id];
        if (tr && tr.snapshot) { tr.snapshot.files = files; }
        for (var i = 0; i < taskList.length; i++) {
          if (taskList[i].id === t.id) { taskList[i].files = files; break; }
        }
        scheduleTaskRender();
      }).catch(function () { /* 拉不到就不显示文件按钮，不打扰用户 */ });
    });
  }

  function scheduleListRefresh() {
    if (refreshQueued) { return; }
    refreshQueued = true;
    window.setTimeout(function () {
      refreshQueued = false;
      refreshTasks();
    }, 800);
  }

  function dropTask(taskId) {
    taskList = taskList.filter(function (t) { return t.id !== taskId; });
    delete trackers[taskId];
    delete logs[taskId];
    delete filesTried[taskId];
    renderTasks();
  }

  function taskRow(task) {
    var pct = percent(task.current, task.total);
    var label = STATUS_TEXT[task.status] || task.status;
    var name = task.title ? escapeHtml(task.title) : '<span class="muted">' + escapeHtml(task.url || '未命名任务') + '</span>';
    var html = '<li class="task task-' + escapeHtml(task.status) + (task.id === focusedTask ? ' is-focused' : '') +
      '" data-task="' + escapeHtml(task.id) + '">';
    html += '<div class="task-head">';
    html += '<button class="task-main" type="button" data-action="focus" title="在上方查看进度">';
    html += '<span class="task-title">' + name + '</span>';
    html += '<span class="task-sub">' + escapeHtml(task.chapter || task.url || '—') + '</span>';
    html += '</button>';
    html += '<span class="badge badge-' + escapeHtml(task.status) + '">' + escapeHtml(label) + '</span>';
    html += '</div>';

    // CSP style-src 'self' 拦内联 style=，宽度经 data-w + CSSOM 赋值（S1 CSP 适配）
    html += '<div class="bar bar-mini"><div class="bar-fill" data-w="' + pct + '"></div></div>';
    html += '<div class="task-foot">';
    html += '<span class="mono small muted">' + task.current + ' / ' + (task.total || '—') + '（' + pct + '%）</span>';
    if (task.status === 'error' && task.error) {
      html += '<span class="task-error">' + escapeHtml(task.error) + '</span>';
    } else if (task.retries && !isFinal(task.status)) {
      // 重试不是失败：徽章仍是「下载中」，只补一条黄色小字
      html += '<span class="task-retry">已自动重试 ' + task.retries + ' 次</span>';
    }
    html += '</div>';

    if (task.status === 'done' && task.files && task.files.length) {
      html += '<div class="file-links">' + task.files.map(function (f) {
        return '<a class="file-link" href="' + escapeHtml(fileHref(task.id, f)) + '" download>⤓ ' + escapeHtml(baseName(f)) + '</a>';
      }).join('') + '</div>';
    }

    html += '<div class="task-actions">';
    html += '<button class="btn btn-ghost btn-sm" type="button" data-action="focus">看进度</button>';
    html += '<button class="btn btn-ghost btn-sm" type="button" data-action="task-remove">删除</button>';
    html += '</div>';
    html += '</li>';
    return html;
  }

  var renderQueued = false;

  /** SSE 每来一章就整表重建会抢焦点，这里做个小节流。 */
  function scheduleTaskRender() {
    if (renderQueued) { return; }
    renderQueued = true;
    window.setTimeout(function () {
      renderQueued = false;
      renderTasks();
    }, 300);
  }

  function renderTasks() {
    var list = $('#tasks-list');
    var empty = $('#tasks-empty');
    var count = $('#tasks-count');
    if (!list) { return; }
    // 用户正在列表里操作（键盘焦点）时先不重绘，稍后再补
    if (list.contains(document.activeElement)) {
      window.setTimeout(function () { if (!renderQueued) { renderTasks(); } }, 1200);
      return;
    }
    if (count) { count.textContent = taskList.length ? taskList.length + ' 条' : ''; }
    if (!taskList.length) {
      list.innerHTML = '';
      if (empty) {
        empty.hidden = false;
        if (!empty.dataset.forced) { empty.textContent = '还没有任务。在左边粘贴一个知乎链接，点「开始下载」，这里会实时显示进度。'; }
      }
      return;
    }
    if (empty) { empty.hidden = true; }
    list.innerHTML = taskList.map(taskRow).join('');
    // CSSOM 赋宽：不受 style-src 限制，效果等同内联 style
    Array.prototype.forEach.call(list.querySelectorAll('.bar-fill[data-w]'), function (el) {
      el.style.width = (el.getAttribute('data-w') || '0') + '%';
    });
  }

  /* ================= 书架 ================= */

  var shelfBooks = [];

  async function refreshShelf() {
    try {
      var data = await api('/api/shelf');
      var list = Array.isArray(data) ? data : (data && (data.books || data.items)) || [];
      shelfBooks = list.map(function (raw) {
        var b = raw || {};
        return {
          id: String(b.id || ''),
          title: String(b.title || '未命名'),
          url: String(b.url || ''),
          fmt: String(b.fmt || ''),
          files: Array.isArray(b.files) ? b.files : [],
          chapters: Array.isArray(b.chapter_urls) ? b.chapter_urls.length : (Number(b.chapters || 0) || 0),
          updated_at: String(b.updated_at || b.downloaded_at || '')
        };
      }).filter(function (b) { return b.id; });
      renderShelf();
    } catch (err) {
      var empty = $('#shelf-empty');
      if (empty && !shelfBooks.length) {
        empty.hidden = false;
        empty.dataset.forced = '1';
        empty.textContent = '书架加载失败：' + err.message;
      }
    }
  }

  function shelfRow(book) {
    var html = '<li class="shelf-item" data-book="' + escapeHtml(book.id) + '">';
    html += '<div class="shelf-head"><span class="shelf-title">' + escapeHtml(book.title) + '</span>';
    if (book.fmt) { html += '<span class="badge badge-fmt">' + escapeHtml(book.fmt) + '</span>'; }
    html += '</div>';
    html += '<dl class="shelf-meta">';
    html += '<div><dt>章节</dt><dd>' + book.chapters + ' 章</dd></div>';
    html += '<div><dt>上次更新</dt><dd>' + escapeHtml(fmtTime(book.updated_at)) + '</dd></div>';
    html += '</dl>';
    if (book.files.length) {
      html += '<div class="file-links">' + book.files.map(function (f) {
        return '<span class="file-chip">📄 ' + escapeHtml(baseName(f)) + '</span>';
      }).join('') + '</div>';
    }
    html += '<div class="task-actions">';
    html += '<button class="btn btn-outline btn-sm" type="button" data-action="shelf-update">检查更新</button>';
    html += '<button class="btn btn-ghost btn-sm" type="button" data-action="shelf-remove">移除</button>';
    html += '</div>';
    html += '</li>';
    return html;
  }

  function renderShelf() {
    var list = $('#shelf-list');
    var empty = $('#shelf-empty');
    var count = $('#shelf-count');
    if (!list) { return; }
    if (count) { count.textContent = shelfBooks.length ? shelfBooks.length + ' 本' : ''; }
    if (!shelfBooks.length) {
      list.innerHTML = '';
      if (empty) {
        empty.hidden = false;
        if (!empty.dataset.forced) { empty.textContent = '书架还空着。下载成功后这本书会自动放进来，以后点「检查更新」就能追更新章节。'; }
      }
      return;
    }
    if (empty) { empty.hidden = true; }
    list.innerHTML = shelfBooks.map(shelfRow).join('');
  }

  async function shelfUpdate(bookId) {
    var book = null;
    shelfBooks.forEach(function (b) { if (b.id === bookId) { book = b; } });
    toast('info', '正在检查《' + (book ? book.title : '') + '》的新章节…');
    try {
      var data = await api('/api/shelf/' + encodeURIComponent(bookId) + '/update', { method: 'POST', body: '{}' });
      var taskId = (data && (data.task_id || data.id)) || '';
      if (taskId && data.new_chapters) {
        toast('ok', '发现 ' + data.new_chapters + ' 章新内容，正在下载…');
      }
      if (taskId) {
        trackTask(taskId);
        focusProgress(taskId);
        await refreshTasks();
      } else {
        var msg = (data && (data.message || data.detail)) || '没有新章节，已是最新。';
        toast('ok', msg);
        await refreshShelf();
      }
    } catch (err) {
      toast('bad', err.message);
    }
  }

  async function shelfRemove(bookId) {
    try {
      await api('/api/shelf/' + encodeURIComponent(bookId), { method: 'DELETE' });
      shelfBooks = shelfBooks.filter(function (b) { return b.id !== bookId; });
      renderShelf();
      toast('ok', '已从书架移除（本机文件仍保留）。');
    } catch (err) {
      toast('bad', err.message);
    }
  }

  /* ================= 设置抽屉 ================= */

  var settings = { open: false, lastFocus: null };

  function openSettings() {
    var el = $('#settings-drawer');
    if (!el || settings.open) { return; }
    if (qr.open) { closeQr(); }
    settings.open = true;
    settings.lastFocus = document.activeElement;
    el.hidden = false;
    document.body.classList.add('overlay-open');
    var btn = $('#settings-btn');
    if (btn) { btn.setAttribute('aria-expanded', 'true'); }
    var first = el.querySelector('.drawer-close, .modal-close');
    if (first) { first.focus(); }
    refreshCookieStatus();
  }

  function closeSettings() {
    var el = $('#settings-drawer');
    if (!el) { return; }
    settings.open = false;
    el.hidden = true;
    var btn = $('#settings-btn');
    if (btn) { btn.setAttribute('aria-expanded', 'false'); }
    hideLogoutConfirm();
    if (!anyOverlayOpen()) { document.body.classList.remove('overlay-open'); }
    if (settings.lastFocus && settings.lastFocus.focus) { settings.lastFocus.focus(); }
  }

  function showCookieMsg(kind, text) {
    var el = $('#cookie-msg');
    if (!el) { return; }
    el.hidden = !text;
    el.className = 'form-msg form-msg-' + kind;
    el.textContent = text || '';
  }

  async function importCookies() {
    var box = $('#cookie-input');
    var raw = box ? String(box.value).trim() : '';
    if (!raw) { showCookieMsg('bad', '先粘贴 Cookie 内容再点导入。'); return; }
    var btn = $('#cookie-import-btn');
    if (btn) { btn.disabled = true; btn.textContent = '正在导入…'; }
    try {
      await api('/api/cookies/import', { method: 'POST', body: JSON.stringify({ raw: raw }) });
      showCookieMsg('ok', 'Cookie 已保存。');
      if (box) { box.value = ''; }
      await refreshCookieStatus();
      toast('ok', '登录信息已更新');
    } catch (err) {
      showCookieMsg('bad', err.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '导入并保存'; }
    }
  }

  function hideLogoutConfirm() {
    var box = $('#logout-confirm');
    if (box) { box.hidden = true; }
    var btn = $('#logout-btn');
    if (btn) { btn.hidden = false; }
  }

  async function doLogout() {
    try {
      await api('/api/cookies', { method: 'DELETE' });
      hideLogoutConfirm();
      await refreshCookieStatus();
      toast('ok', '已退出登录。');
    } catch (err) {
      toast('bad', err.message);
    }
  }

  async function loadHealth() {
    try {
      var data = await api('/api/health');
      var el = $('#app-version');
      if (el) { el.textContent = (data && data.version) ? String(data.version) : '未知'; }
    } catch (err) {
      var el2 = $('#app-version');
      if (el2) { el2.textContent = '读取失败'; }
    }
  }

  /* ================= 事件绑定 ================= */

  function onTaskListClick(event) {
    var row = event.target.closest ? event.target.closest('.task') : null;
    if (!row) { return; }
    var actionEl = event.target.closest('[data-action]');
    if (!actionEl) { return; }
    var id = row.getAttribute('data-task') || '';
    var action = actionEl.getAttribute('data-action');
    if (action === 'focus') {
      trackTask(id);
      focusProgress(id);
      if ($('#progress-card')) { $('#progress-card').scrollIntoView({ block: 'nearest' }); }
    } else if (action === 'task-remove') {
      stopTracker(id);
      dropTask(id);
      if (focusedTask === id) { hideProgress(); }
      toast('info', '已从列表移除（不影响本机文件）。');
    }
  }

  function onShelfClick(event) {
    var row = event.target.closest ? event.target.closest('.shelf-item') : null;
    if (!row) { return; }
    var actionEl = event.target.closest('[data-action]');
    if (!actionEl) { return; }
    var id = row.getAttribute('data-book') || '';
    var action = actionEl.getAttribute('data-action');
    if (action === 'shelf-update') {
      actionEl.disabled = true;
      shelfUpdate(id).then(function () { actionEl.disabled = false; });
    } else if (action === 'shelf-remove') {
      shelfRemove(id);
    }
  }

  function onKeydown(event) {
    if (event.key === 'Escape') {
      if (settings.open) { closeSettings(); return; }
      if (qr.open) { closeQr(); return; }
      if (!document.body.classList.contains('nav-open')) { return; }
      toggleNav(false);
      return;
    }
    if (event.key === 'Tab') {
      var modal = $('#qr-modal');
      if (qr.open && modal) { trapFocus(modal.querySelector('.modal'), event); return; }
      var drawer = $('#settings-drawer');
      if (settings.open && drawer) { trapFocus(drawer.querySelector('.drawer'), event); }
    }
  }

  function toggleNav(force) {
    var btn = $('#nav-toggle');
    var open = force === undefined ? !document.body.classList.contains('nav-open') : force;
    if (open) { document.body.classList.add('nav-open'); } else { document.body.classList.remove('nav-open'); }
    if (btn) { btn.setAttribute('aria-expanded', open ? 'true' : 'false'); }
  }

  function isLive(snap) {
    return !!snap && !isFinal(snap.status);
  }

  function onVisibility() {
    if (document.hidden) {
      // 页签隐藏：停掉所有降级轮询（SSE 由浏览器自行节流），省电也少打接口
      Object.keys(trackers).forEach(function (id) {
        var t = trackers[id];
        if (t.pollOnly && isLive(t.snapshot)) { stopPollingKeepFlag(t); }
      });
      return;
    }
    // 回到前台：补一次状态，并恢复仍在进行的轮询
    Object.keys(trackers).forEach(function (id) {
      var t = trackers[id];
      if (t.pollOnly && t.timer === null && isLive(t.snapshot)) { startPolling(id, t, false); }
    });
    refreshCookieStatus();
    refreshTasks();
    refreshShelf();
  }

  /** 绑定前先确认元素在（HTML 被别的模块改动时也不会整页崩）。 */
  function on(sel, type, handler) {
    var el = $(sel);
    if (el) { el.addEventListener(type, handler); }
  }

  function bind() {
    on('#theme-toggle', 'click', toggleTheme);
    on('#qr-btn', 'click', openQr);
    on('#qr-retry', 'click', createQr);
    on('#cookie-pill', 'click', openSettings);
    on('#settings-btn', 'click', function () {
      if (settings.open) { closeSettings(); } else { openSettings(); }
    });
    on('#nav-toggle', 'click', function () { toggleNav(); });
    on('#cookie-import-btn', 'click', importCookies);
    on('#logout-btn', 'click', function () {
      var box = $('#logout-confirm');
      var btn = $('#logout-btn');
      if (box) { box.hidden = false; }
      if (btn) { btn.hidden = true; }
      var yes = $('#logout-yes');
      if (yes) { yes.focus(); }
    });
    on('#logout-yes', 'click', doLogout);
    on('#logout-no', 'click', hideLogoutConfirm);
    on('#download-form', 'submit', submitDownload);
    on('#url-input', 'input', function () { showUrlError(''); });
    on('#tasks-list', 'click', onTaskListClick);
    on('#shelf-list', 'click', onShelfClick);
    on('#prog-close', 'click', hideProgress);
    on('#prog-retry', 'click', function () {
      // 失败后一键重试：把原链接回填表单再提交，用户不用重新复制
      var url = this.dataset.url || '';
      hideProgress();
      var input = $('#url-input');
      if (input) { input.value = url; }
      showUrlError('');
      submitDownload({ preventDefault: function () {} });
      if (input) { input.focus(); }
    });
    $all('[data-close-qr]').forEach(function (el) { el.addEventListener('click', closeQr); });
    $all('[data-close-settings]').forEach(function (el) { el.addEventListener('click', closeSettings); });
    document.addEventListener('keydown', onKeydown);
    document.addEventListener('visibilitychange', onVisibility);
    if (window.matchMedia) {
      var mq = window.matchMedia('(prefers-color-scheme: dark)');
      var onChange = function () {
        var saved = null;
        try { saved = localStorage.getItem(THEME_KEY); } catch (e) { saved = null; }
        if (!saved) { applyTheme(mq.matches ? 'dark' : 'light'); }
      };
      if (mq.addEventListener) { mq.addEventListener('change', onChange); }
      else if (mq.addListener) { mq.addListener(onChange); }
    }
  }

  function init() {
    initTheme();
    bind();
    refreshCookieStatus();
    refreshTasks();
    refreshShelf();
    loadHealth();
    // 兜底：服务端重启或列表外变化时，30s 温和同步一次（页签隐藏时跳过）
    window.setInterval(function () {
      if (document.hidden) { return; }
      refreshTasks();
    }, 30000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

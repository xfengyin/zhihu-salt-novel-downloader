/* 知乎盐选下载器 v4 — 极简单页交互 */
(function () {
  'use strict'

  // ---------- 工具函数 ----------

  var $ = function (selector) {
    return document.querySelector(selector)
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
  }

  /**
   * 请求后端 JSON API。非 2xx 时解析 {detail} 并抛出可读错误。
   */
  async function api(path, options) {
    var opts = options || {}
    var headers = opts.headers || {}
    if (opts.body && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json'
    }
    var resp
    try {
      resp = await fetch(path, {
        method: opts.method || 'GET',
        headers: headers,
        body: opts.body,
      })
    } catch (err) {
      throw new Error('网络请求失败，请确认服务已启动（' + (err && err.message ? err.message : '连接失败') + '）')
    }

    var text = await resp.text()
    var data = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch (err) {
        data = null
      }
    }

    if (!resp.ok) {
      var detail = data && (data.detail || data.message)
      if (!detail) detail = 'HTTP ' + resp.status + ' ' + resp.statusText
      throw new Error(detail)
    }
    return data
  }

  // ---------- 主题 ----------

  var THEME_KEY = 'zhihu-v4-theme'

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme)
    var icon = $('#theme-toggle')
    if (icon) icon.textContent = theme === 'dark' ? '☀️' : '🌙'
  }

  function initTheme() {
    var saved = localStorage.getItem(THEME_KEY)
    var preferred = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light'
    applyTheme(saved || preferred)
  }

  function toggleTheme() {
    var current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
    var next = current === 'dark' ? 'light' : 'dark'
    localStorage.setItem(THEME_KEY, next)
    applyTheme(next)
  }

  // ---------- Cookie 状态 ----------

  async function refreshCookieStatus() {
    var pill = $('#cookie-status')
    try {
      var data = await api('/api/cookies')
      if (data && data.has_cookie) {
        pill.textContent = '已登录'
        pill.className = 'status-pill status-on'
      } else {
        pill.textContent = '未登录'
        pill.className = 'status-pill status-off'
      }
    } catch (err) {
      pill.textContent = '状态未知'
      pill.className = 'status-pill status-off'
    }
  }

  // ---------- 扫码登录 ----------

  var qrToken = null
  var qrTimer = null

  function stopQrPolling() {
    if (qrTimer !== null) {
      clearInterval(qrTimer)
      qrTimer = null
    }
  }

  function openQrModal() {
    var modal = $('#qr-modal')
    modal.hidden = false
    $('#qr-retry').hidden = true
    createQrCode()
  }

  function closeQrModal() {
    stopQrPolling()
    qrToken = null
    $('#qr-modal').hidden = true
    $('#qr-body').innerHTML = ''
  }

  function qrIconHtml(state) {
    if (state === 'loading') return '<span class="spinner"></span>'
    if (state === 'success') return '✓'
    if (state === 'error') return '!'
    if (state === 'expired') return '↻'
    return ''
  }

  // 渲染带二维码图片的帧（下方带状态文字）
  function renderQrFrame(imageUrl, text, hint) {
    var body = $('#qr-body')
    body.innerHTML =
      '<div class="qr-frame"><img src="' + escapeHtml(imageUrl) + '" alt="知乎登录二维码" /></div>' +
      '<div class="qr-status">' +
      '<div class="qr-state-text">' + escapeHtml(text) + '</div>' +
      '<div class="qr-state-hint">' + escapeHtml(hint) + '</div>' +
      '</div>'
    body.querySelector('img').onerror = markQrExpired
  }

  // 更新二维码帧下方的状态文字（保持图片不变）
  function updateQrStatus(text, hint) {
    var textEl = $('#qr-body .qr-state-text')
    var hintEl = $('#qr-body .qr-state-hint')
    if (textEl) textEl.textContent = text
    if (hintEl && hint) hintEl.textContent = hint
  }

  // 渲染无二维码帧的纯状态（loading / confirmed / error / expired）
  function renderQrState(state, text, hint, errorText) {
    var body = $('#qr-body')
    var icon = qrIconHtml(state)
    var html = ''
    if (icon) html += '<div class="qr-state-icon ' + escapeHtml(state) + '">' + icon + '</div>'
    if (text) html += '<div class="qr-state-text">' + escapeHtml(text) + '</div>'
    if (hint) html += '<div class="qr-state-hint">' + escapeHtml(hint) + '</div>'
    if (errorText) html += '<div class="qr-error-text">' + escapeHtml(errorText) + '</div>'
    body.innerHTML = html
  }

  function markQrExpired() {
    stopQrPolling()
    qrToken = null
    $('#qr-retry').hidden = false
    renderQrState('expired', '二维码已失效', '二维码已过期或加载失败，请重新获取')
  }

  async function createQrCode() {
    stopQrPolling()
    qrToken = null
    $('#qr-retry').hidden = true
    renderQrState('loading', '正在获取二维码…')

    try {
      var data = await api('/api/qrcode', { method: 'POST', body: '{}' })
      qrToken = data.token
      renderQrFrame(
        data.image_url || '/api/qrcode/' + encodeURIComponent(data.token) + '/image',
        '等待扫码',
        '请使用知乎 App 扫描二维码'
      )
      startQrPolling()
    } catch (err) {
      renderQrState('error', '获取二维码失败', err.message)
      $('#qr-retry').hidden = false
    }
  }

  function startQrPolling() {
    stopQrPolling()
    qrTimer = setInterval(pollQrStatus, 2000)
  }

  async function pollQrStatus() {
    if (!qrToken) return
    try {
      var data = await api('/api/qrcode/' + encodeURIComponent(qrToken) + '/status')
      handleQrStatus(data)
    } catch (err) {
      stopQrPolling()
      qrToken = null
      $('#qr-retry').hidden = false
      renderQrState('expired', '二维码已失效', err.message)
    }
  }

  function handleQrStatus(data) {
    var status = data && data.status
    if (status === 'waiting') {
      updateQrStatus('等待扫码', '请使用知乎 App 扫描二维码')
    } else if (status === 'scanned') {
      updateQrStatus('已扫码', '请在手机上点击确认登录')
    } else if (status === 'confirmed') {
      stopQrPolling()
      qrToken = null
      renderQrState('success', '登录成功', 'Cookie 已保存，即将自动关闭…')
      refreshCookieStatus()
      setTimeout(closeQrModal, 1200)
    } else if (status === 'error') {
      stopQrPolling()
      qrToken = null
      $('#qr-retry').hidden = false
      renderQrState('error', '登录失败', null, (data && data.error) || '请重试')
    } else if (status === 'expired') {
      stopQrPolling()
      qrToken = null
      $('#qr-retry').hidden = false
      renderQrState('expired', '二维码已失效', '二维码已过期，请重新获取')
    } else {
      // 未知状态按等待处理，避免误判
      updateQrStatus('等待扫码', '请使用知乎 App 扫描二维码')
    }
  }

  // ---------- 下载 ----------

  async function submitDownload(event) {
    event.preventDefault()
    var urlInput = $('#url-input')
    var url = urlInput.value.trim()
    var msg = $('#download-msg')
    msg.hidden = true

    if (!url) {
      showFormMsg('error', '请输入知乎盐选小说链接')
      return
    }
    if (!/^https?:\/\//i.test(url)) {
      showFormMsg('error', '链接需以 http:// 或 https:// 开头')
      return
    }

    var btn = $('#download-btn')
    btn.disabled = true
    var originalText = btn.textContent
    btn.textContent = '提交中…'

    try {
      var format = $('#format-select').value
      var data = await api('/api/download', {
        method: 'POST',
        body: JSON.stringify({ url: url, format: format }),
      })
      showFormMsg('success', '任务已创建（ID: ' + data.task_id + '），正在后台下载…')
      refreshTasks()
    } catch (err) {
      showFormMsg('error', err.message)
    } finally {
      btn.disabled = false
      btn.textContent = originalText
    }
  }

  function showFormMsg(type, text) {
    var msg = $('#download-msg')
    msg.hidden = false
    msg.className = 'form-msg ' + type
    msg.textContent = text
  }

  // ---------- 任务列表 ----------

  var tasksInFlight = false
  var filesCache = {}
  var filesLoading = {}
  var latestTasks = []

  async function refreshTasks() {
    if (tasksInFlight) return
    tasksInFlight = true
    try {
      latestTasks = await api('/api/tasks')
      renderTasks()
      fetchMissingFiles()
    } catch (err) {
      renderTasksError(err.message)
    } finally {
      tasksInFlight = false
    }
  }

  function fetchMissingFiles() {
    latestTasks.forEach(function (task) {
      if (task.status === 'success' && !filesCache[task.task_id] && !filesLoading[task.task_id]) {
        filesLoading[task.task_id] = true
        api('/api/tasks/' + encodeURIComponent(task.task_id))
          .then(function (detail) {
            filesCache[task.task_id] = (detail && detail.files) || []
            renderTasks()
          })
          .catch(function () {
            filesCache[task.task_id] = []
            renderTasks()
          })
          .finally(function () {
            filesLoading[task.task_id] = false
          })
      }
    })
  }

  function renderTasksError(message) {
    $('#tasks-empty').hidden = false
    $('#tasks-empty').textContent = '加载任务失败：' + message
    $('#tasks-list').innerHTML = ''
  }

  function renderTasks() {
    var list = $('#tasks-list')
    var empty = $('#tasks-empty')

    if (!latestTasks.length) {
      empty.hidden = false
      empty.textContent = '暂无任务，先在上方粘贴链接开始下载吧。'
      list.innerHTML = ''
      return
    }

    empty.hidden = true
    list.innerHTML = latestTasks
      .map(function (task) {
        return renderTask(task)
      })
      .reverse()
      .join('')
  }

  function renderTask(task) {
    var status = task.status || 'pending'
    var statusText = {
      pending: '等待中',
      running: '下载中',
      success: '已完成',
      error: '失败',
    }[status] || status

    var title = task.title
      ? escapeHtml(task.title)
      : '<span class="task-url">' + escapeHtml(task.url) + '</span>'

    var html = '<li class="task">' +
      '<div class="task-head">' +
      '<div class="task-main">' +
      '<div class="task-title">' + title + '</div>'

    if (task.title && task.url) {
      html += '<div class="task-url">' + escapeHtml(task.url) + '</div>'
    }

    html += '</div>' +
      '<span class="badge ' + escapeHtml(status) + '">' + escapeHtml(statusText) + '</span>' +
      '</div>'

    if (status === 'error' && task.error) {
      html += '<div class="task-error">' + escapeHtml(task.error) + '</div>'
    }

    if (status === 'success') {
      var files = filesCache[task.task_id] || []
      if (files.length) {
        html += '<div class="task-files">'
        files.forEach(function (filename) {
          var href = '/api/files/' + encodeURIComponent(task.task_id) + '/' + encodeURIComponent(filename)
          html += '<a class="file-link" href="' + escapeHtml(href) + '" download>📄 ' + escapeHtml(filename) + '</a>'
        })
        html += '</div>'
      }
    }

    html += '</li>'
    return html
  }

  // ---------- 初始化 ----------

  function init() {
    initTheme()

    $('#theme-toggle').addEventListener('click', toggleTheme)
    $('#qr-btn').addEventListener('click', openQrModal)
    $('#qr-retry').addEventListener('click', createQrCode)
    $('#download-form').addEventListener('submit', submitDownload)
    $('#refresh-tasks').addEventListener('click', refreshTasks)

    // 关闭对话框：点击遮罩 / 关闭按钮
    var closers = document.querySelectorAll('[data-close]')
    for (var i = 0; i < closers.length; i++) {
      closers[i].addEventListener('click', closeQrModal)
    }

    refreshCookieStatus()
    refreshTasks()
    setInterval(refreshTasks, 2000)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()

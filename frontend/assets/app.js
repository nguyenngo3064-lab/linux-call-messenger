const byId = (id) => document.getElementById(id);
const history = { cpu: [], memory: [] };
let csrfToken = '';
let pollTimer;

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET' && csrfToken) headers.set('X-CSRF-Token', csrfToken);
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Yêu cầu thất bại (${response.status})`);
  return payload;
}

function showLogin(message = '') {
  clearInterval(pollTimer);
  byId('dashboard-view').hidden = true;
  byId('login-view').hidden = false;
  byId('login-error').textContent = message;
}

function showDashboard() {
  byId('login-view').hidden = true;
  byId('dashboard-view').hidden = false;
  refresh();
  clearInterval(pollTimer);
  pollTimer = setInterval(refresh, 5000);
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '--';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return '--';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return days ? `${days} ngày ${hours} giờ` : `${hours} giờ ${minutes} phút`;
}

function setMeter(id, value) {
  byId(id).style.width = `${Math.max(0, Math.min(100, Number(value) || 0))}%`;
}

function setText(id, value) {
  byId(id).textContent = value ?? '--';
}

function updateSystem(data) {
  const { cpu, memory, swap, disk, host, backend } = data;
  setText('cpu-value', Math.round(cpu.usage_percent));
  setText('memory-value', Math.round(memory.usage_percent));
  setText('swap-value', Math.round(swap.usage_percent));
  setText('disk-value', Math.round(disk.usage_percent));
  setMeter('cpu-meter', cpu.usage_percent);
  setMeter('memory-meter', memory.usage_percent);
  setMeter('swap-meter', swap.usage_percent);
  setMeter('disk-meter', disk.usage_percent);
  setText('cpu-detail', `${cpu.cores_logical} cores · ${cpu.model || 'Model không khả dụng'}`);
  setText('memory-detail', `${formatBytes(memory.used_bytes)} / ${formatBytes(memory.total_bytes)}`);
  setText('swap-detail', `${formatBytes(swap.used_bytes)} / ${formatBytes(swap.total_bytes)}`);
  setText('disk-detail', `${formatBytes(disk.used_bytes)} / ${formatBytes(disk.total_bytes)}`);
  setText('host-cpu', cpu.model || 'Không khả dụng');
  setText('host-cores', `${cpu.cores_logical} logical${cpu.cores_physical ? ` · ${cpu.cores_physical} physical` : ''}`);
  setText('host-temperature', cpu.temperature_c === null ? 'Không khả dụng' : `${cpu.temperature_c.toFixed(1)} °C`);
  setText('host-memory', `${formatBytes(memory.used_bytes)} / ${formatBytes(memory.total_bytes)}`);
  setText('host-disk', `${formatBytes(disk.used_bytes)} / ${formatBytes(disk.total_bytes)}`);
  setText('host-uptime', formatDuration(host.uptime_seconds));
  setText('host-os', host.os);
  setText('host-kernel', host.kernel);
  setText('host-ip', host.local_ip || 'Không khả dụng');
  setText('host-network', `${formatBytes(data.network.bytes_received_per_second)}/s RX · ${formatBytes(data.network.bytes_sent_per_second)}/s TX`);
  setText('host-zombies', data.processes.zombie_count === null ? 'Không khả dụng' : data.processes.zombie_count);
  setText('host-oom', host.oom_kill_count === null ? 'Không khả dụng' : host.oom_kill_count);
  setText('backend-uptime', `Uptime ${formatDuration(backend.uptime_seconds)}`);
  setText('last-updated', `Cập nhật ${new Date(data.sampled_at * 1000).toLocaleTimeString('vi-VN')}`);
  setText('sample-time', `CPU ${cpu.usage_percent.toFixed(1)}% · RAM ${memory.usage_percent.toFixed(1)}%`);
  drawChart();
}

function drawChart() {
  const canvas = byId('history-chart');
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  const width = bounds.width;
  const height = bounds.height;
  context.clearRect(0, 0, width, height);
  context.font = '10px ui-monospace, monospace';
  for (let tick = 0; tick <= 4; tick += 1) {
    const y = 8 + ((height - 24) * tick) / 4;
    context.strokeStyle = '#edf1ed';
    context.beginPath(); context.moveTo(28, y); context.lineTo(width, y); context.stroke();
    context.fillStyle = '#98a39b';
    context.fillText(`${100 - tick * 25}`, 2, y + 3);
  }
  const series = [
    { values: history.cpu, color: '#187a57' },
    { values: history.memory, color: '#e4785f' },
  ];
  for (const line of series) {
    if (!line.values.length) continue;
    context.strokeStyle = line.color;
    context.lineWidth = 2;
    context.beginPath();
    line.values.forEach((value, index) => {
      const x = 30 + (Math.max(0, width - 38) * index) / Math.max(1, line.values.length - 1);
      const y = 8 + ((height - 24) * (100 - value)) / 100;
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.stroke();
  }
}

async function refresh() {
  try {
    const [system, browser, call, samples] = await Promise.all([
      api('/api/system'), api('/api/browser/status'), api('/api/call/status'), api('/api/system/history?limit=30'),
    ]);
    updateSystem(system);
    history.cpu = samples.map((sample) => sample.cpu_percent);
    history.memory = samples.map((sample) => sample.memory_percent);
    drawChart();
    setText('browser-name', browser.name === 'firefox-esr' ? 'Firefox ESR' : browser.name);
    setText('browser-version', browser.version || (browser.installed ? 'Phiên bản không khả dụng' : 'Chưa cài đặt'));
    setText('browser-memory', formatBytes(browser.memory_bytes));
    setText('browser-cpu', `${browser.cpu_percent.toFixed(1)}%`);
    setText('browser-restarts', browser.restart_count);
    setText('browser-uptime', browser.running ? formatDuration(browser.uptime_seconds) : '--');
    setText('browser-state', browser.running ? 'Đang chạy' : browser.installed ? 'Đã dừng' : 'Chưa cài');
    byId('browser-state').className = `status-pill ${browser.running ? 'online' : 'offline'}`;
    byId('browser-warning').hidden = browser.installed;
    setText('browser-warning', 'Chưa tìm thấy browser đã cấu hình trên máy chủ.');
    byId('browser-start').disabled = browser.running;
    byId('browser-stop').disabled = !browser.running;
    setText('call-state', call.status === 'unverified' ? 'Chưa xác minh' : call.status);
    setText('call-reason', call.reason);
    setText('webrtc-state', call.webrtc === 'unavailable' ? 'Không khả dụng' : call.webrtc);
    setText('call-duration', call.duration_seconds === null ? 'Chưa xác minh' : formatDuration(call.duration_seconds));
    byId('notice').hidden = true;
  } catch (error) {
    if (error.message.includes('Cần đăng nhập')) return showLogin('Phiên đăng nhập đã hết hạn.');
    byId('notice').textContent = error.message;
    byId('notice').hidden = false;
  }
}

async function loadLogs() {
  const rows = await api('/api/logs?limit=200');
  const body = byId('log-rows');
  body.replaceChildren();
  if (!rows.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 4;
    cell.className = 'empty-state';
    cell.textContent = 'Chưa có sự kiện được ghi nhận.';
    row.append(cell);
    body.append(row);
    return;
  }
  for (const event of rows) {
    const row = document.createElement('tr');
    const values = [
      new Date(event.created_at * 1000).toLocaleString('vi-VN'),
      event.level,
      event.event_type,
      event.message,
    ];
    values.forEach((value, index) => {
      const cell = document.createElement('td');
      cell.textContent = value;
      if (index === 1) cell.className = `log-level level-${String(value).toLowerCase()}`;
      row.append(cell);
    });
    body.append(row);
  }
}

async function loadSettings() {
  const settings = await api('/api/settings');
  byId('setting-mode').value = settings.mode;
  byId('setting-ram').value = settings.memory_warning_percent;
  byId('setting-history').value = settings.history_days;
  byId('setting-browser').value = settings.browser_name;
  byId('setting-autostart').checked = settings.browser_auto_start;
  byId('setting-autorestart').checked = settings.browser_auto_restart;
  byId('setting-check-interval').value = settings.process_check_interval_seconds;
  byId('setting-log-size').value = settings.log_size_mb;
  byId('setting-timezone').value = settings.timezone;
}

async function downloadDiagnostics() {
  const data = await api('/api/diagnostics');
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'messenger-call-keeper-diagnostics.json';
  link.click();
  URL.revokeObjectURL(url);
}

function showView(view) {
  for (const name of ['overview', 'logs', 'settings']) byId(`${name}-view`).hidden = name !== view;
  document.querySelectorAll('.view-tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.view === view));
  const labels = { overview: 'Tổng quan', logs: 'Nhật ký', settings: 'Cài đặt' };
  document.querySelector('.topbar h1').textContent = labels[view];
  if (view === 'logs') loadLogs().catch((error) => { byId('notice').textContent = error.message; byId('notice').hidden = false; });
  if (view === 'settings') loadSettings().catch((error) => { byId('notice').textContent = error.message; byId('notice').hidden = false; });
}

byId('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  byId('login-error').textContent = '';
  const password = new FormData(event.currentTarget).get('password');
  try {
    const result = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) });
    csrfToken = result.csrf_token;
    event.currentTarget.reset();
    showDashboard();
  } catch (error) { byId('login-error').textContent = error.message; }
});

byId('logout-button').addEventListener('click', async () => {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch { /* Expired sessions are already logged out. */ }
  csrfToken = '';
  showLogin();
});

byId('browser-start').addEventListener('click', async () => {
  try { await api('/api/browser/start', { method: 'POST' }); await refresh(); }
  catch (error) { byId('notice').textContent = error.message; byId('notice').hidden = false; }
});

byId('browser-stop').addEventListener('click', async () => {
  try { await api('/api/browser/stop', { method: 'POST' }); await refresh(); }
  catch (error) { byId('notice').textContent = error.message; byId('notice').hidden = false; }
});

document.querySelectorAll('.view-tab').forEach((tab) => {
  tab.addEventListener('click', () => showView(tab.dataset.view));
});

byId('settings-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const settings = {
    mode: form.get('mode'),
    memory_warning_percent: Number(form.get('memory_warning_percent')),
    history_days: Number(form.get('history_days')),
    browser_name: form.get('browser_name'),
    browser_auto_start: form.has('browser_auto_start'),
    browser_auto_restart: form.has('browser_auto_restart'),
    process_check_interval_seconds: Number(form.get('process_check_interval_seconds')),
    log_size_mb: Number(form.get('log_size_mb')),
    timezone: form.get('timezone'),
  };
  try {
    await api('/api/settings', { method: 'PUT', body: JSON.stringify(settings) });
    byId('settings-message').textContent = 'Đã lưu cài đặt.';
    await refresh();
  } catch (error) { byId('settings-message').textContent = error.message; }
});

byId('password-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const message = byId('password-message');
  message.textContent = '';
  try {
    const result = await api('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: form.get('current_password'),
        new_password: form.get('new_password'),
      }),
    });
    csrfToken = result.csrf_token;
    event.currentTarget.reset();
    message.textContent = 'Đã đổi mật khẩu; các session khác đã bị đăng xuất.';
  } catch (error) { message.textContent = error.message; }
});

byId('clear-logs-button').addEventListener('click', async () => {
  if (!window.confirm('Xóa các sự kiện đã ghi nhận?')) return;
  try { await api('/api/logs', { method: 'DELETE' }); await loadLogs(); }
  catch (error) { byId('notice').textContent = error.message; byId('notice').hidden = false; }
});

byId('export-button').addEventListener('click', () => {
  downloadDiagnostics().catch((error) => { byId('notice').textContent = error.message; byId('notice').hidden = false; });
});

window.addEventListener('resize', drawChart);
api('/api/auth/status')
  .then((result) => { csrfToken = result.csrf_token; showDashboard(); })
  .catch(() => showLogin());

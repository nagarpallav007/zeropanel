/* zeropanel web UI */
'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
const S = {
  user: null,
  sites: [],
  site: '',          // active site name
  treePath: '',      // current dir shown in sidebar
  openFile: null,    // currently open file path (relative to user base)
  editor: null,      // CodeMirror instance
  editorDirty: false,
  ws: null,          // terminal WebSocket
  logTimer: null,
  ctxTarget: null,   // path that was right-clicked
};

// ── API ───────────────────────────────────────────────────────────────────────
async function api(method, path, body = null, raw = false) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (raw) return res;
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const show  = (...ids) => ids.forEach(id => $( id)?.classList.remove('hidden'));
const hide  = (...ids) => ids.forEach(id => $( id)?.classList.add('hidden'));

function setStatus(msg, isError = false) {
  const el = $('login-error');
  if (el) { el.textContent = msg; el.style.color = isError ? 'var(--red)' : 'var(--green)'; }
}

function modeForFile(name) {
  const ext = name.split('.').pop().toLowerCase();
  const map = { php: 'php', js: 'javascript', ts: 'javascript', css: 'css',
                html: 'htmlmixed', htm: 'htmlmixed', xml: 'xml', sh: 'shell',
                bash: 'shell', yml: 'yaml', yaml: 'yaml', json: 'javascript',
                nginx: 'nginx', conf: 'nginx', env: 'shell', txt: null, md: null };
  return map[ext] ?? null;
}

// ── Auth ──────────────────────────────────────────────────────────────────────
async function checkAuth() {
  try {
    const data = await api('GET', '/api/me');
    S.user  = data.username;
    S.sites = data.sites;
    showApp();
  } catch {
    showLogin();
  }
}

async function login(username, password) {
  setStatus('');
  try {
    await api('POST', '/api/login', { username, password });
    await checkAuth();
  } catch (e) {
    setStatus(e.message, true);
  }
}

async function logout() {
  await api('POST', '/api/logout').catch(() => {});
  S.user = null; S.sites = []; S.site = '';
  if (S.ws) { S.ws.close(); S.ws = null; }
  showLogin();
}

// ── Screen transitions ────────────────────────────────────────────────────────
function showLogin() {
  hide('app');
  show('login-screen');
  $('login-username').value = '';
  $('login-password').value = '';
  $('login-error').textContent = '';
}

function showApp() {
  hide('login-screen');
  show('app');
  $('header-username').textContent = S.user;

  const sel = $('site-selector');
  sel.innerHTML = S.sites.length
    ? S.sites.map(s => `<option value="${s}">${s}</option>`).join('')
    : '<option value="">— no sites —</option>';
  S.site = S.sites[0] ?? '';
  $('terminal-site-label').textContent = S.site || 'no site selected';

  loadTree('sites');
}

// ── File tree ─────────────────────────────────────────────────────────────────
async function loadTree(path = S.treePath) {
  S.treePath = path;
  $('breadcrumb').textContent = '/' + path;
  try {
    const { entries } = await api('GET', `/api/files?path=${encodeURIComponent(path)}`);
    renderTree($('file-tree'), entries, path);
  } catch (e) {
    $('file-tree').textContent = 'Error: ' + e.message;
  }
}

function renderTree(container, entries, basePath) {
  container.innerHTML = '';
  if (basePath) {
    const up = document.createElement('div');
    up.className = 'tree-item';
    up.innerHTML = '<span class="icon">↩</span> ..';
    up.onclick = () => loadTree(basePath.split('/').slice(0, -1).join('/') || '');
    container.appendChild(up);
  }
  entries.forEach(e => {
    const item = document.createElement('div');
    item.className = 'tree-item' + (S.openFile === basePath + '/' + e.name ? ' active' : '');
    item.dataset.path = basePath ? basePath + '/' + e.name : e.name;
    item.dataset.type = e.type;
    item.innerHTML = `<span class="icon">${e.type === 'dir' ? '📁' : fileIcon(e.name)}</span>
                      <span>${e.name}</span>`;
    item.onclick = () => {
      if (e.type === 'dir') loadTree(item.dataset.path);
      else openFile(item.dataset.path);
    };
    item.oncontextmenu = ev => showCtxMenu(ev, item.dataset.path, e.type);
    container.appendChild(item);
  });
}

function fileIcon(name) {
  const ext = name.split('.').pop().toLowerCase();
  const icons = { php: '🐘', js: '📜', ts: '📘', css: '🎨', html: '🌐', htm: '🌐',
                  json: '📋', yml: '⚙', yaml: '⚙', sh: '⚡', env: '🔑',
                  zip: '📦', tar: '📦', gz: '📦', sql: '🗄', md: '📝', txt: '📄' };
  return icons[ext] ?? '📄';
}

// ── Editor ────────────────────────────────────────────────────────────────────
async function openFile(path) {
  try {
    const { content } = await api('GET', `/api/files/read?path=${encodeURIComponent(path)}`);
    S.openFile = path;
    S.editorDirty = false;

    const fname = path.split('/').pop();
    $('editor-filename').textContent = path;
    show('save-btn', 'download-btn');
    hide('editor-placeholder');

    const ta = $('codemirror-target');

    if (S.editor) {
      S.editor.setValue(content);
      S.editor.setOption('mode', modeForFile(fname));
    } else {
      S.editor = CodeMirror.fromTextArea(ta, {
        value: content,
        mode: modeForFile(fname),
        theme: 'dracula',
        lineNumbers: true,
        matchBrackets: true,
        indentUnit: 4,
        tabSize: 4,
        indentWithTabs: false,
        lineWrapping: false,
        autofocus: true,
      });
      S.editor.on('change', () => {
        S.editorDirty = true;
        const fname = (S.openFile || '').split('/').pop();
        $('editor-filename').textContent = '● ' + (S.openFile || '');
      });
    }

    // Mark active in tree
    document.querySelectorAll('.tree-item').forEach(el => {
      el.classList.toggle('active', el.dataset.path === path);
    });

    // Switch to editor tab
    activateTab('editor');
  } catch (e) {
    alert('Cannot open file: ' + e.message);
  }
}

async function saveFile() {
  if (!S.openFile) return;
  const content = S.editor.getValue();
  try {
    await api('POST', '/api/files/write', { path: S.openFile, content });
    S.editorDirty = false;
    $('editor-filename').textContent = S.openFile;
  } catch (e) {
    alert('Save failed: ' + e.message);
  }
}

function downloadFile(path) {
  const a = document.createElement('a');
  a.href = `/api/files/download?path=${encodeURIComponent(path)}`;
  a.download = path.split('/').pop();
  a.click();
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
function activateTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-content').forEach(c => {
    c.classList.toggle('hidden', c.id !== 'tab-' + name);
  });
  if (name === 'terminal' && !S.ws) connectTerminal();
  if (name === 'logs') loadLogs();
  if (name === 'editor' && S.editor) S.editor.refresh();
}

// ── Terminal ──────────────────────────────────────────────────────────────────
function connectTerminal() {
  if (!S.site) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  S.ws = new WebSocket(`${proto}://${location.host}/api/ws/terminal?site=${encodeURIComponent(S.site)}`);

  S.ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    const out = $('terminal-output');
    if (msg.type === 'output') {
      const span = document.createElement('span');
      span.className = 't-out';
      span.textContent = msg.line;
      out.appendChild(span);
    } else if (msg.type === 'exit') {
      const span = document.createElement('span');
      span.className = msg.code === 0 ? 't-exit-ok' : 't-exit-err';
      span.textContent = `[exit ${msg.code}]`;
      out.appendChild(span);
    }
    out.scrollTop = out.scrollHeight;
  };

  S.ws.onclose = () => { S.ws = null; };
  S.ws.onerror = () => {
    termPrint('WebSocket error — reconnect by switching tabs', 't-err');
    S.ws = null;
  };
}

function termPrint(text, cls = 't-out') {
  const out = $('terminal-output');
  const span = document.createElement('span');
  span.className = cls;
  span.textContent = text;
  out.appendChild(span);
  out.scrollTop = out.scrollHeight;
}

function sendCommand(cmd) {
  cmd = cmd.trim();
  if (!cmd) return;
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) {
    connectTerminal();
    setTimeout(() => sendCommand(cmd), 400);
    return;
  }
  termPrint('$ ' + cmd, 't-cmd');
  S.ws.send(JSON.stringify({ cmd }));
}

// ── Logs ──────────────────────────────────────────────────────────────────────
async function loadLogs() {
  if (!S.site) { $('logs-content').textContent = 'No site selected.'; return; }
  const type  = $('log-type-select').value;
  const lpath = `sites/${S.site}/logs/${type}.log`;
  try {
    const { content } = await api('GET', `/api/files/read?path=${encodeURIComponent(lpath)}`);
    const lines = content.split('\n');
    $('logs-content').textContent = lines.slice(-500).join('\n');
    $('logs-content').scrollTop = $('logs-content').scrollHeight;
  } catch (e) {
    $('logs-content').textContent = `Log unavailable: ${e.message}`;
  }
}

// ── Upload ────────────────────────────────────────────────────────────────────
async function uploadFiles(files) {
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      await api('POST', `/api/files/upload?path=${encodeURIComponent(S.treePath)}`, fd);
    } catch (e) {
      alert(`Upload failed for ${file.name}: ${e.message}`);
    }
  }
  loadTree();
}

// ── Context menu ──────────────────────────────────────────────────────────────
function showCtxMenu(ev, path, type) {
  ev.preventDefault();
  S.ctxTarget = { path, type };
  const menu = $('context-menu');
  menu.style.left = ev.pageX + 'px';
  menu.style.top  = ev.pageY + 'px';
  menu.classList.remove('hidden');
  const isFile = type === 'file';
  const isZip  = isFile && path.toLowerCase().endsWith('.zip');
  $('ctx-open').style.display     = isFile ? '' : 'none';
  $('ctx-download').style.display = isFile ? '' : 'none';
  $('ctx-extract').style.display  = isZip  ? '' : 'none';
}

function hideCtxMenu() { $('context-menu').classList.add('hidden'); }

// ── Site selector change ──────────────────────────────────────────────────────
function onSiteChange() {
  S.site = $('site-selector').value;
  $('terminal-site-label').textContent = S.site || 'no site selected';
  if (S.ws) { S.ws.close(); S.ws = null; }
  if ($('tab-terminal').classList.contains('hidden') === false) connectTerminal();
}

// ── Init ──────────────────────────────────────────────────────────────────────
function init() {
  // Login form
  $('login-form').onsubmit = ev => {
    ev.preventDefault();
    login($('login-username').value, $('login-password').value);
  };

  $('logout-btn').onclick = logout;

  // Tabs
  document.querySelectorAll('.tab').forEach(btn => {
    btn.onclick = () => activateTab(btn.dataset.tab);
  });

  // Site selector
  $('site-selector').onchange = onSiteChange;

  // File tree toolbar
  $('upload-btn').onclick       = () => $('upload-input').click();
  $('refresh-tree-btn').onclick = () => loadTree();
  $('newfile-btn').onclick = async () => {
    const name = prompt('New file name:');
    if (!name) return;
    const path = S.treePath ? S.treePath + '/' + name : name;
    try { await api('POST', '/api/files/write', { path, content: '' }); await loadTree(); openFile(path); }
    catch (e) { alert(e.message); }
  };
  $('mkdir-btn').onclick = async () => {
    const name = prompt('New folder name:');
    if (!name) return;
    const path = S.treePath ? S.treePath + '/' + name : name;
    try { await api('POST', '/api/files/mkdir', { path }); loadTree(); }
    catch (e) { alert(e.message); }
  };
  $('upload-input').onchange = ev => { uploadFiles(ev.target.files); ev.target.value = ''; };

  // Editor toolbar
  $('save-btn').onclick     = saveFile;
  $('download-btn').onclick = () => S.openFile && downloadFile(S.openFile);

  // Keyboard shortcut: Ctrl/Cmd+S to save
  document.addEventListener('keydown', ev => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 's') { ev.preventDefault(); saveFile(); }
  });

  // Terminal input
  const termInput = $('terminal-input');
  const cmdHistory = [];
  let histIdx = -1;

  const runCmd = () => {
    const cmd = termInput.value.trim();
    if (!cmd) return;
    cmdHistory.unshift(cmd);
    histIdx = -1;
    termInput.value = '';
    sendCommand(cmd);
  };

  termInput.addEventListener('keydown', ev => {
    if (ev.key === 'Enter') { runCmd(); return; }
    if (ev.key === 'ArrowUp')   { histIdx = Math.min(histIdx + 1, cmdHistory.length - 1); termInput.value = cmdHistory[histIdx] ?? ''; }
    if (ev.key === 'ArrowDown') { histIdx = Math.max(histIdx - 1, -1); termInput.value = histIdx < 0 ? '' : cmdHistory[histIdx]; }
  });
  $('terminal-send-btn').onclick = runCmd;
  $('clear-terminal-btn').onclick = () => { $('terminal-output').innerHTML = ''; };

  // Logs
  $('refresh-logs-btn').onclick = loadLogs;
  $('log-type-select').onchange = loadLogs;
  $('autoreload-logs').onchange = ev => {
    clearInterval(S.logTimer);
    if (ev.target.checked) S.logTimer = setInterval(loadLogs, 5000);
  };

  // Context menu
  document.addEventListener('click', hideCtxMenu);
  $('ctx-open').onclick     = () => { if (S.ctxTarget) openFile(S.ctxTarget.path); hideCtxMenu(); };
  $('ctx-download').onclick = () => { if (S.ctxTarget) downloadFile(S.ctxTarget.path); hideCtxMenu(); };
  $('ctx-rename').onclick   = async () => {
    if (!S.ctxTarget) { hideCtxMenu(); return; }
    const oldName = S.ctxTarget.path.split('/').pop();
    const newName = prompt('Rename to:', oldName);
    if (!newName || newName === oldName) { hideCtxMenu(); return; }
    const dir     = S.ctxTarget.path.split('/').slice(0, -1).join('/');
    const to_path = dir ? dir + '/' + newName : newName;
    try {
      await api('POST', '/api/files/rename', { from_path: S.ctxTarget.path, to_path });
      if (S.openFile === S.ctxTarget.path) { S.openFile = to_path; $('editor-filename').textContent = to_path; }
      loadTree();
    } catch (e) { alert(e.message); }
    hideCtxMenu();
  };
  $('ctx-extract').onclick  = () => {
    if (!S.ctxTarget) { hideCtxMenu(); return; }
    const fname = S.ctxTarget.path.split('/').pop();
    activateTab('terminal');
    sendCommand('unzip -o ' + fname);
    hideCtxMenu();
  };
  $('ctx-delete').onclick   = async () => {
    if (!S.ctxTarget || S.ctxTarget.type !== 'file') { hideCtxMenu(); return; }
    if (!confirm(`Delete ${S.ctxTarget.path}?`)) { hideCtxMenu(); return; }
    try {
      await api('DELETE', `/api/files?path=${encodeURIComponent(S.ctxTarget.path)}`);
      if (S.openFile === S.ctxTarget.path) { S.openFile = null; $('editor-filename').textContent = 'No file open'; hide('save-btn', 'download-btn'); }
      loadTree();
    } catch (e) { alert(e.message); }
    hideCtxMenu();
  };

  // Bootstrap
  checkAuth();
}

init();

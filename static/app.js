const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

function switchTab(tabName) {
  $$('.tab-btn').forEach(b => { b.classList.remove('tab-active'); b.classList.add('text-gray-500'); });
  const target = $(`.tab-btn[data-tab="${tabName}"]`);
  if (target) { target.classList.add('tab-active'); target.classList.remove('text-gray-500'); }
  $$('.tab-content').forEach(s => s.classList.add('hidden'));
  $(`#tab-${tabName}`).classList.remove('hidden');
  localStorage.setItem('activeTab', tabName);
  if (tabName === 'files') loadFiles();
  if (tabName === 'history') loadHistory();
  if (tabName === 'logs') loadLogs();
}

$$('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// 恢复上次的 tab
const savedTab = localStorage.getItem('activeTab') || 'parse';
switchTab(savedTab);

$('#url-input').addEventListener('keydown', e => { if (e.key === 'Enter') doParse(); });

function clearInput() {
  $('#url-input').value = '';
  $('#url-input').focus();
}

async function pasteInput() {
  try {
    const text = await navigator.clipboard.readText();
    $('#url-input').value = text;
    $('#url-input').focus();
  } catch (e) {
    // clipboard API 需要 HTTPS 或 localhost，fallback
    $('#url-input').value = '';
    $('#url-input').focus();
    alert('无法读取剪贴板，请手动粘贴');
  }
}

async function doParse() {
  const raw = $('#url-input').value.trim();
  if (!raw) return;
  $('#parse-loading').classList.remove('hidden');
  $('#parse-result').classList.add('hidden');
  $('#parse-error').classList.add('hidden');
  $('#parse-btn').disabled = true;
  try {
    const resp = await fetch('/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: raw })
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '解析失败');
    renderResult(data);
  } catch (e) {
    $('#parse-error').textContent = e.message;
    $('#parse-error').classList.remove('hidden');
  } finally {
    $('#parse-loading').classList.add('hidden');
    $('#parse-btn').disabled = false;
  }
}

function renderResult(data) {
  $('#r-platform').textContent = data.platform;
  $('#r-type').textContent = data.type === 'slides' ? '图文' : '视频';
  $('#r-title').textContent = data.title || '(无标题)';
  $('#r-author').textContent = data.author ? `@${data.author}` : '';
  $('#r-duration').textContent = data.duration ? `时长: ${fmtDuration(data.duration)}` : '';
  $('#r-cached').classList.toggle('hidden', !data.cached);
  $('#r-link').textContent = data.resolved_url || data.original_url || '';
  $('#r-link').href = data.resolved_url || data.original_url || '#';

  const mediaEl = $('#r-media');
  mediaEl.innerHTML = '';
  const videos = data.files.filter(f => f.type === 'video');
  const images = data.files.filter(f => f.type === 'image');

  if (videos.length) {
    videos.forEach(f => {
      mediaEl.innerHTML += `<video controls class="w-full max-h-[60vh] bg-black cursor-pointer" preload="metadata" onclick="openLightbox(${JSON.stringify(data.files.map(x=>({url:x.url,type:x.type}))).replace(/"/g,'&quot;')}, ${data.files.indexOf(f)})"><source src="${f.url}" type="video/mp4"></video>`;
    });
  }
  if (images.length) {
    const allItems = data.files.map(f => ({url: f.url, type: f.type}));
    const grid = document.createElement('div');
    grid.className = 'grid gap-1 p-1' + (images.length === 1 ? '' : images.length <= 4 ? ' grid-cols-2' : ' grid-cols-3');
    images.forEach(f => {
      const idx = data.files.indexOf(f);
      grid.innerHTML += `<img src="${f.url}" class="w-full aspect-square object-cover rounded cursor-pointer hover:opacity-80 transition" onclick='openLightbox(${JSON.stringify(allItems)}, ${idx})'>`;
    });
    mediaEl.appendChild(grid);
    if (images.length > 1) {
      const btnWrap = document.createElement('div');
      btnWrap.className = 'px-1 pb-2';
      btnWrap.innerHTML = `<button onclick="downloadAll()" class="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium transition">一键下载全部 (${images.length} 张)</button>`;
      mediaEl.appendChild(btnWrap);
    }
  }

  const filesEl = $('#r-files');
  filesEl.innerHTML = '<h3 class="text-sm font-medium text-gray-500 mb-3">文件</h3>';
  data.files.forEach(f => {
    filesEl.innerHTML += `
      <div class="flex items-center justify-between py-2 border-b border-gray-100 gap-2">
        <div class="flex items-center gap-2 min-w-0">
          <span class="text-xs px-1.5 py-0.5 rounded flex-shrink-0 ${f.type === 'video' ? 'bg-purple-50 text-purple-600' : 'bg-pink-50 text-pink-600'}">${f.type === 'video' ? '视频' : '图片'}</span>
          <span class="text-sm text-gray-700 truncate">${f.filename}</span>
        </div>
        <a href="${f.url}" download class="text-blue-600 hover:text-blue-500 text-sm flex-shrink-0">下载</a>
      </div>`;
  });
  $('#parse-result').classList.remove('hidden');
}

async function loadFiles() {
  try {
    const resp = await fetch('/files');
    const data = await resp.json();
    const files = data.files || [];
    const platforms = [...new Set(files.map(f => f.relative_path.split('/')[1] || ''))];
    const dates = [...new Set(files.map(f => f.relative_path.split('/')[0] || ''))];
    const pf = $('#filter-platform');
    const df = $('#filter-date');
    if (pf.options.length <= 1) platforms.forEach(p => { if (p) pf.add(new Option(p, p)); });
    if (df.options.length <= 1) dates.forEach(d => { if (d) df.add(new Option(d, d)); });
    renderFiles(files);
    pf.onchange = () => renderFiles(files);
    df.onchange = () => renderFiles(files);
  } catch (e) { console.error(e); }
}

function renderFiles(files) {
  const fp = $('#filter-platform').value;
  const fd = $('#filter-date').value;
  const filtered = files.filter(f => {
    const parts = f.relative_path.split('/');
    if (fp && parts[1] !== fp) return false;
    if (fd && parts[0] !== fd) return false;
    return true;
  });
  const grid = $('#files-grid');
  const empty = $('#files-empty');
  if (!filtered.length) { grid.innerHTML = ''; empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');
  grid.innerHTML = filtered.map(f => {
    const ext = f.filename.split('.').pop().toLowerCase();
    const isVideo = ['mp4','mkv','webm','flv'].includes(ext);
    const isImage = ['jpg','jpeg','png','webp','gif'].includes(ext);
    const parts = f.relative_path.split('/');
    const platform = parts[1] || '';
    const date = parts[0] || '';
    let preview = '';
    if (isVideo) {
      preview = `<video class="w-full aspect-video object-cover bg-black" preload="metadata" muted><source src="${f.url}"></video>`;
    } else if (isImage) {
      preview = `<img src="${f.url}" class="w-full aspect-video object-cover">`;
    } else {
      preview = `<div class="w-full aspect-video bg-gray-200 flex items-center justify-center text-gray-400 text-xs">${ext.toUpperCase()}</div>`;
    }
    const clickable = (isVideo || isImage) ? `onclick="openLightbox([{url:'${f.url}',type:'${isVideo?'video':'image'}'}], 0)"` : '';
    return `
      <div class="bg-white rounded-lg border border-gray-200 overflow-hidden hover:border-gray-300 transition shadow-sm">
        <div class="relative cursor-pointer" ${clickable}>${preview}
          <span class="absolute top-1 left-1 bg-black/50 text-white text-xs px-1.5 py-0.5 rounded">${platform}</span>
        </div>
        <div class="p-3">
          <div class="text-xs text-gray-500 truncate mb-2">${f.filename}</div>
          <div class="flex items-center justify-between">
            <span class="text-xs text-gray-400">${fmtSize(f.size)} · ${date}</span>
            <a href="${f.url}" download class="text-blue-600 hover:text-blue-500 text-xs" onclick="event.stopPropagation()">下载</a>
          </div>
        </div>
      </div>`;
  }).join('');
}

async function loadHistory() {
  try {
    const resp = await fetch('/api/cache');
    const data = await resp.json();
    const entries = data.entries || [];
    const list = $('#history-list');
    const empty = $('#history-empty');
    if (!entries.length) { list.innerHTML = ''; empty.classList.remove('hidden'); return; }
    empty.classList.add('hidden');
    list.innerHTML = entries.map(e => `
      <div class="bg-white rounded-lg border border-gray-200 p-4 hover:border-gray-300 transition cursor-pointer shadow-sm" onclick="$('#url-input').value='${e.original_url.replace(/'/g, "\\'")}'; $$('.tab-btn')[0].click();">
        <div class="flex items-center gap-2 mb-1">
          <span class="bg-blue-50 text-blue-600 text-xs px-2 py-0.5 rounded font-medium">${e.platform}</span>
          <span class="text-xs text-gray-400">${e.type === 'slides' ? '图文' : '视频'}</span>
          ${e.files.length ? `<span class="text-xs text-gray-400">${e.files.length} 个文件</span>` : ''}
        </div>
        <div class="text-sm font-medium mb-1">${e.title || '(无标题)'}</div>
        <div class="text-xs text-gray-400 truncate">${e.author ? '@' + e.author : ''} · ${e.original_url.substring(0, 60)}</div>
      </div>
    `).join('');
  } catch (e) { console.error(e); }
}

let logsTimer = null;

async function loadLogs() {
  try {
    const resp = await fetch('/api/logs?limit=200');
    const data = await resp.json();
    const container = $('#logs-container');
    container.innerHTML = (data.logs || []).map(l =>
      `<div class="log-${l.level}"><span class="text-gray-400">${l.time}</span> <span class="font-bold">[${l.level}]</span> ${escHtml(l.message)}</div>`
    ).join('');
    container.scrollTop = container.scrollHeight;
  } catch (e) { console.error(e); }
}

$('#logs-auto').addEventListener('change', function() {
  if (this.checked) { logsTimer = setInterval(loadLogs, 3000); }
  else { clearInterval(logsTimer); logsTimer = null; }
});

// Lightbox gallery
let lbItems = [];
let lbIndex = 0;

function openLightbox(items, index) {
  lbItems = items; // [{url, type}]
  lbIndex = index || 0;
  renderLightbox();
  $('#lightbox').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  $('#lightbox').classList.add('hidden');
  $('#lb-content').innerHTML = '';
  document.body.style.overflow = '';
}

function renderLightbox() {
  const item = lbItems[lbIndex];
  const el = item.type === 'video'
    ? `<video controls autoplay class="rounded" style="max-width:95vw;max-height:90vh"><source src="${item.url}" type="video/mp4"></video>`
    : `<img src="${item.url}" class="rounded">`;
  $('#lb-content').innerHTML = el;
  $('#lb-counter').textContent = lbItems.length > 1 ? `${lbIndex + 1} / ${lbItems.length}` : '';
}

function lbNav(dir) {
  lbIndex = (lbIndex + dir + lbItems.length) % lbItems.length;
  renderLightbox();
}

// 键盘导航
document.addEventListener('keydown', e => {
  if ($('#lightbox').classList.contains('hidden')) return;
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowLeft') lbNav(-1);
  if (e.key === 'ArrowRight') lbNav(1);
});

// 点击背景关闭
$('#lightbox').addEventListener('click', e => {
  if (e.target === $('#lightbox') || e.target === $('#lb-content')) closeLightbox();
});

// 触摸滑动切换
let touchStartX = 0;
$('#lightbox').addEventListener('touchstart', e => { touchStartX = e.touches[0].clientX; }, { passive: true });
$('#lightbox').addEventListener('touchend', e => {
  const dx = e.changedTouches[0].clientX - touchStartX;
  if (Math.abs(dx) > 50) lbNav(dx > 0 ? -1 : 1);
}, { passive: true });

function downloadAll() {
  const links = $$('#r-files a[download]');
  links.forEach((a, i) => setTimeout(() => a.click(), i * 300));
}

function fmtDuration(sec) { const m = Math.floor(sec / 60); const s = Math.floor(sec % 60); return `${m}:${s.toString().padStart(2, '0')}`; }
function fmtSize(bytes) { if (bytes < 1024) return bytes + ' B'; if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'; return (bytes / 1048576).toFixed(1) + ' MB'; }
function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

logsTimer = setInterval(() => {
  if ($('#logs-auto').checked && !$('#tab-logs').classList.contains('hidden')) loadLogs();
}, 3000);

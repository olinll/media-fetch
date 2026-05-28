const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const BASE = window.BASE_PATH || '';

var filesPage = 1;
var filesLoading = false;
var filesHasMore = true;
var historyPage = 1;
var historyPageSize = 20;
var logsTimer = null;
var filesSentinel = document.createElement('div');
var filesObserver = new IntersectionObserver(entries => {
  if (entries[0].isIntersecting && filesHasMore && !filesLoading) loadFiles();
}, { rootMargin: '200px' });

const TAB_ROUTES = { '/': 'parse', '/files': 'files', '/history': 'history', '/logs': 'logs', '/docs': 'docs' };
const TAB_PATHS = { parse: '/', files: '/files', history: '/history', logs: '/logs', docs: '/docs' };

function getTabFromPath() {
  let path = location.pathname;
  if (BASE && path.startsWith(BASE)) path = path.slice(BASE.length) || '/';
  return TAB_ROUTES[path] || 'parse';
}

function switchTab(tabName, push = true) {
  $$('.tab-btn').forEach(b => { b.classList.remove('tab-active'); b.classList.add('text-gray-500'); });
  const target = $(`.tab-btn[data-tab="${tabName}"]`);
  if (target) { target.classList.add('tab-active'); target.classList.remove('text-gray-500'); }
  $$('.tab-content').forEach(s => s.classList.add('hidden'));
  $(`#tab-${tabName}`).classList.remove('hidden');
  if (push) {
    const fullPath = BASE + (TAB_PATHS[tabName] || '/');
    history.pushState(null, '', fullPath);
  }
  if (tabName === 'files') { if (!$('#files-sentinel')) initFilesObserver(); loadFiles(true); }
  if (tabName === 'history') loadHistory(1);
  if (tabName === 'logs') loadLogs();
}

$$('.tab-btn').forEach(btn => {
  btn.addEventListener('click', e => {
    e.preventDefault();
    switchTab(btn.dataset.tab);
  });
});

window.addEventListener('popstate', () => switchTab(getTabFromPath(), false));

// 初始化
switchTab(getTabFromPath(), false);

function clearInput() {
  $('#batch-input').value = '';
  $('#parse-result').classList.add('hidden');
  $('#parse-error').classList.add('hidden');
  $('#parse-tips').classList.remove('hidden');
  $('#batch-input').focus();
}

async function pasteInput() {
  try {
    const text = await navigator.clipboard.readText();
    $('#batch-input').value = text;
    $('#batch-input').focus();
  } catch (e) {
    $('#batch-input').focus();
    alert('无法读取剪贴板，请手动粘贴');
  }
}

async function doParse() {
  const raw = $('#batch-input').value.trim();
  if (!raw) return;
  $('#parse-loading').classList.remove('hidden');
  $('#parse-result').classList.add('hidden');
  $('#parse-error').classList.add('hidden');
  $('#parse-tips').classList.add('hidden');
  $('#parse-btn').disabled = true;
  try {
    const lines = raw.split('\n').filter(l => l.trim());
    const endpoint = lines.length > 1 ? `${BASE}/api/batch-parse` : `${BASE}/api/parse`;
    const body = lines.length > 1 ? JSON.stringify({ text: raw }) : JSON.stringify({ text: lines[0] });
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || '解析失败');
    if (lines.length > 1) renderBatchResult(data);
    else renderResult(data);
  } catch (e) {
    $('#parse-error').textContent = e.message;
    $('#parse-error').classList.remove('hidden');
    $('#parse-tips').classList.remove('hidden');
  } finally {
    $('#parse-loading').classList.add('hidden');
    $('#parse-btn').disabled = false;
  }
}

function renderResult(data) {
  $('#single-result').classList.remove('hidden');
  $('#batch-result').classList.add('hidden');
  $('#r-platform').textContent = data.platform;
  $('#r-type').textContent = data.type === 'slides' ? '图文' : '视频';
  $('#r-title').textContent = data.title || '(无标题)';
  $('#r-author').textContent = data.author ? `@${data.author}` : '';
  $('#r-duration').textContent = data.duration ? `时长: ${fmtDuration(data.duration)}` : '';
  $('#r-cached').classList.toggle('hidden', !data.cached);
  $('#r-link').textContent = data.resolved_url || data.original_url || '';
  $('#r-link').href = data.resolved_url || data.original_url || '#';
  $('#r-ip').textContent = data.client_ip || '';

  const mediaEl = $('#r-media');
  mediaEl.innerHTML = '';
  const videos = data.files.filter(f => f.type === 'video');
  const images = data.files.filter(f => f.type === 'image');

  if (videos.length) {
    videos.forEach(f => {
      mediaEl.innerHTML += `<video controls playsinline class="w-full max-h-[60vh] bg-black cursor-pointer" preload="metadata" onclick="openLightbox(${JSON.stringify(data.files.map(x=>({url:x.url,type:x.type}))).replace(/"/g,'&quot;')}, ${data.files.indexOf(f)})"><source src="${f.url}" type="video/mp4"></video>`;
    });
  }
  if (images.length) {
    const allItems = data.files.map(f => ({url: f.url, type: f.type}));
    const grid = document.createElement('div');
    grid.className = 'grid gap-1 p-1' + (images.length === 1 ? '' : images.length <= 4 ? ' grid-cols-2' : ' grid-cols-3');
    images.forEach(f => {
      const idx = data.files.indexOf(f);
      grid.innerHTML += `<img src="${f.thumb || f.url}" class="w-full aspect-square object-cover rounded cursor-pointer hover:opacity-80 transition" onclick='openLightbox(${JSON.stringify(allItems)}, ${idx})'>`;
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

function renderBatchResult(data) {
  const container = $('#parse-result');
  const batchEl = $('#batch-result');

  $('#single-result').classList.add('hidden');
  batchEl.innerHTML = '';

  const results = data.results || [];
  let successCount = 0;
  let failCount = 0;

  results.forEach((result, idx) => {
    const card = document.createElement('div');
    card.className = 'bg-white rounded-lg border border-gray-200 overflow-hidden mb-3';

    if (result.success) {
      successCount++;
      const files = result.files || [];
      const videos = files.filter(f => f.type === 'video');
      const images = files.filter(f => f.type === 'image');

      let mediaHtml = '';
      if (videos.length) {
        mediaHtml += videos.map(f => `
          <video controls playsinline class="w-full max-h-48 bg-black" preload="metadata">
            <source src="${f.url}" type="video/mp4">
          </video>
        `).join('');
      }
      if (images.length) {
        mediaHtml += `<div class="grid gap-1 p-1 ${images.length === 1 ? '' : images.length <= 4 ? 'grid-cols-2' : 'grid-cols-3'}">`;
        mediaHtml += images.map(f => `
          <img src="${f.thumb || f.url}" class="w-full aspect-square object-cover rounded cursor-pointer hover:opacity-80 transition" onclick="openLightbox(${JSON.stringify(files.map(x=>({url:x.url,type:x.type}))).replace(/"/g,'&quot;')}, ${files.indexOf(f)})">
        `).join('');
        mediaHtml += '</div>';
      }

      const contentId = `batch-content-${idx}`;
      card.innerHTML = `
        <div class="p-3 cursor-pointer flex items-center justify-between" onclick="toggleBatchItem('${contentId}', this)">
          <div>
            <div class="flex items-center gap-2 mb-1">
              <span class="bg-blue-50 text-blue-600 text-xs px-2 py-0.5 rounded font-medium">${result.platform}</span>
              <span class="text-xs text-gray-400">${result.type === 'slides' ? '图文' : '视频'}</span>
              ${result.cached ? '<span class="text-xs text-green-500">缓存</span>' : ''}
            </div>
            <div class="text-sm font-medium">${result.title || '(无标题)'}</div>
            <div class="text-xs text-gray-400">${result.author ? '@' + result.author : ''}</div>
          </div>
          <svg class="w-4 h-4 text-gray-400 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </div>
        <div id="${contentId}" class="hidden">
          ${mediaHtml ? `<div class="border-t border-gray-100">${mediaHtml}</div>` : ''}
          <div class="p-3 border-t border-gray-100 flex flex-wrap gap-2">
            ${files.map(f => `<a href="${f.url}" download class="text-blue-600 hover:text-blue-500 text-xs bg-blue-50 px-2 py-1 rounded">${f.type === 'video' ? '视频' : '图片'} 下载</a>`).join('')}
          </div>
        </div>
      `;
    } else {
      failCount++;
      card.innerHTML = `
        <div class="p-4">
          <div class="flex items-center gap-2 mb-1">
            <span class="bg-red-50 text-red-600 text-xs px-2 py-0.5 rounded">失败</span>
          </div>
          <div class="text-sm text-gray-600 truncate">${result.url || ''}</div>
          <div class="text-xs text-red-500 mt-1">${result.error || '未知错误'}</div>
        </div>
      `;
    }
    batchEl.appendChild(card);
  });

  // 添加统计
  const summary = document.createElement('div');
  summary.className = 'bg-gray-50 rounded-lg p-3 mb-3 text-sm text-gray-600';
  summary.textContent = `成功: ${successCount} 个，失败: ${failCount} 个`;
  batchEl.insertBefore(summary, batchEl.firstChild);

  container.classList.remove('hidden');
}

function toggleBatchItem(id, header) {
  const content = document.getElementById(id);
  const icon = header.querySelector('svg');
  content.classList.toggle('hidden');
  icon.style.transform = content.classList.contains('hidden') ? '' : 'rotate(180deg)';
}

function buildFileCard(f) {
  const ext = f.filename.split('.').pop().toLowerCase();
  const isVideo = ['mp4','mkv','webm','flv'].includes(ext);
  const isImage = ['jpg','jpeg','png','webp','gif'].includes(ext);
  const parts = f.relative_path.split('/');
  const platform = parts[1] || '';
  const date = parts[0] || '';
  let preview = '';
  if (isVideo) {
    preview = `<div class="relative aspect-video bg-black">
      <img src="${f.thumb || ''}" class="w-full h-full object-cover" loading="lazy" onerror="this.style.display='none'">
      <div class="absolute inset-0 flex items-center justify-center">
        <svg class="w-10 h-10 text-white/80 drop-shadow" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      </div>
    </div>`;
  } else if (isImage) {
    preview = `<img src="${f.thumb || f.url}" class="w-full object-cover" loading="lazy">`;
  } else {
    preview = `<div class="w-full aspect-video bg-gray-200 flex items-center justify-center text-gray-400 text-xs">${ext.toUpperCase()}</div>`;
  }
  const clickable = (isVideo || isImage) ? `onclick="openLightbox([{url:'${f.url}',type:'${isVideo?'video':'image'}'}], 0)"` : '';
  return `
    <div class="wf-item bg-white rounded-lg border border-gray-200 overflow-hidden hover:border-gray-300 transition shadow-sm">
      <div class="relative cursor-pointer" ${clickable}>${preview}
        <span class="absolute top-1 left-1 bg-black/50 text-white text-xs px-1.5 py-0.5 rounded">${platform}</span>
      </div>
      <div class="p-2.5">
        <div class="text-xs text-gray-500 truncate mb-1">${f.filename}</div>
        <div class="flex items-center justify-between">
          <span class="text-xs text-gray-400">${fmtSize(f.size)} · ${date}</span>
          <a href="${f.url}" download class="text-blue-600 hover:text-blue-500 text-xs flex-shrink-0" onclick="event.stopPropagation()">下载</a>
        </div>
      </div>
    </div>`;
}

async function loadFiles(reset = false) {
  if (filesLoading) return;
  if (reset) { filesPage = 1; filesHasMore = true; $('#files-grid').innerHTML = ''; }
  if (!filesHasMore) return;
  filesLoading = true;
  $('#files-loading').classList.remove('hidden');
  try {
    const fp = $('#filter-platform').value;
    const fd = $('#filter-date').value;
    const resp = await fetch(`${BASE}/i/files?page=${filesPage}&page_size=20&platform=${encodeURIComponent(fp)}&date=${encodeURIComponent(fd)}`);
    const data = await resp.json();
    const grid = $('#files-grid');
    const empty = $('#files-empty');
    $('#files-count').textContent = `(${data.total} 个文件)`;
    if (data.platforms && data.platforms.length && $('#filter-platform').options.length <= 1) {
      data.platforms.forEach(p => $('#filter-platform').add(new Option(p, p)));
    }
    if (data.dates && data.dates.length && $('#filter-date').options.length <= 1) {
      data.dates.forEach(d => $('#filter-date').add(new Option(d, d)));
    }
    if (!data.files.length && filesPage === 1) { grid.innerHTML = ''; empty.classList.remove('hidden'); }
    else { empty.classList.add('hidden'); data.files.forEach(f => grid.insertAdjacentHTML('beforeend', buildFileCard(f))); }
    filesHasMore = data.has_more;
    filesPage++;
  } catch (e) { console.error(e); }
  finally { filesLoading = false; $('#files-loading').classList.add('hidden'); }
}

filesSentinel.id = 'files-sentinel';

function initFilesObserver() {
  const section = $('#tab-files');
  filesSentinel.style.height = '1px';
  section.appendChild(filesSentinel);
  filesObserver.observe(filesSentinel);
}

$('#filter-platform').onchange = () => loadFiles(true);
$('#filter-date').onchange = () => loadFiles(true);

function buildHistoryCard(e) {
  return `
    <div class="bg-white rounded-lg border border-gray-200 p-4 hover:border-gray-300 transition cursor-pointer shadow-sm" onclick="$('#batch-input').value='${e.original_url.replace(/'/g, "\\'")}'; $$('.tab-btn')[0].click();">
      <div class="flex items-center gap-2 mb-1">
        <span class="bg-blue-50 text-blue-600 text-xs px-2 py-0.5 rounded font-medium">${e.platform}</span>
        <span class="text-xs text-gray-400">${e.type === 'slides' ? '图文' : '视频'}</span>
        ${e.files.length ? `<span class="text-xs text-gray-400">${e.files.length} 个文件</span>` : ''}
      </div>
      <div class="text-sm font-medium mb-1">${e.title || '(无标题)'}</div>
      <div class="text-xs text-gray-400 truncate">${e.author ? '@' + e.author : ''} · ${e.client_ip || ''} · ${e.original_url.substring(0, 60)}</div>
    </div>`;
}

async function loadHistory(page = 1) {
  historyPage = page;
  try {
    const resp = await fetch(`${BASE}/i/cache?page=${page}&page_size=${historyPageSize}`);
    const data = await resp.json();
    const entries = data.entries || [];
    const list = $('#history-list');
    const empty = $('#history-empty');
    const pag = $('#history-pagination');
    if (!entries.length && page === 1) { list.innerHTML = ''; empty.classList.remove('hidden'); pag.innerHTML = ''; return; }
    empty.classList.add('hidden');
    list.innerHTML = entries.map(buildHistoryCard).join('');
    // 分页按钮
    const totalPages = Math.ceil(data.total / historyPageSize);
    if (totalPages <= 1) { pag.innerHTML = ''; return; }
    let btns = '';
    btns += `<button class="page-btn" ${page <= 1 ? 'disabled' : ''} onclick="loadHistory(${page - 1})">‹</button>`;
    for (let i = 1; i <= totalPages; i++) {
      if (totalPages > 7 && i > 2 && i < totalPages - 1 && Math.abs(i - page) > 1) {
        if (i === 3 || i === totalPages - 2) btns += '<span class="px-1 text-gray-400">…</span>';
        continue;
      }
      btns += `<button class="page-btn ${i === page ? 'active' : ''}" onclick="loadHistory(${i})">${i}</button>`;
    }
    btns += `<button class="page-btn" ${page >= totalPages ? 'disabled' : ''} onclick="loadHistory(${page + 1})">›</button>`;
    pag.innerHTML = btns;
  } catch (e) { console.error(e); }
}

async function loadLogs() {
  try {
    const resp = await fetch(`${BASE}/i/logs?limit=200`);
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
    ? `<video controls autoplay playsinline class="rounded" style="max-width:95vw;max-height:90vh"><source src="${item.url}" type="video/mp4"></video>`
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

// Domain check flow (default light mode, dark mode removed)
const checkBtn = document.getElementById('check-btn');
const loader = document.getElementById('loader');
const gridContainer = document.getElementById('grid');

checkBtn.addEventListener('click', async () => {
  const raw = document.getElementById('domains-input').value;
  const domains = raw.split(/\s+/).filter(Boolean);
  if (!domains.length) return;

  // UI state
  checkBtn.disabled = true;
  loader.classList.remove('hidden');
  gridContainer.innerHTML = '';
  const logPanel = document.getElementById('log-panel');
  const logsContainer = document.getElementById('logs');
  logsContainer.innerHTML = '';
  logPanel.classList.remove('hidden');

  // terminal-style preamble
  const bannerLines = [
    '  ___                 _         ___ _           _           ',
    ' |   \\ ___ _ __  __ _(_)_ _    / __| |_  ___ __| |_____ _ _ ',
    ' | |) / _ \\ \'  \\/ _\` | | \' \\  | (__| \' \\/ -_) _| / / -_) \'_|',
    ' |___/\\___/_|_|_\\__,_|_|_||_|  \\___|_||_\\___\\__|_\\_\\___|_|  ',
    '                                                             '
  ];
  for (const line of bannerLines) {
    const pre = document.createElement('pre'); // Use <pre> tag
    pre.textContent = line;
    pre.style.margin = '0'; // Remove default <pre> margins
    pre.style.lineHeight = '1'; // Adjust line height if needed
    logsContainer.appendChild(pre);
  }

  // fake system info
  const sysLines = [
    'Initializing domain-checker daemon v1.4...',
    `OS: ${navigator.platform}`,
    `Timestamp: ${new Date().toLocaleString()}`,
    ''
  ];
  for (const line of sysLines) {
    const div = document.createElement('div');
    div.textContent = line;
    logsContainer.appendChild(div);
  }

  // initialize dashboard metrics
  document.getElementById('counter-total').textContent = domains.length;
  let checkedCount = 0;
  let onlineCount = 0;
  let failedCount = 0;

  try {
    const startTime = performance.now();
    const res = await fetch('/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domains })
    });
    const data = await res.json();
    // sequential log animation
    for (let i = 0; i < data.length; i++) {
      const item = data[i];
      const lineStart = document.createElement('div');
      lineStart.textContent = `Checking ${item.domain}...`;
      logsContainer.appendChild(lineStart);
      logsContainer.scrollTop = logsContainer.scrollHeight;
      await new Promise(r => setTimeout(r, 200));
      const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error checking' : 'Offline');
      const lineResult = document.createElement('div');
      lineResult.textContent = `${item.domain}: ${statusText}`;
      logsContainer.appendChild(lineResult);
      logsContainer.scrollTop = logsContainer.scrollHeight;

      // update dashboard metrics
      checkedCount++;
      document.getElementById('counter-checked').textContent = checkedCount;
      if (item.ok) {
        onlineCount++;
        document.getElementById('counter-online').textContent = onlineCount;
      } else {
        failedCount++;
        document.getElementById('counter-failed').textContent = failedCount;
      }
      // update elapsed timer
      const elapsedSec = ((performance.now() - startTime) / 1000).toFixed(1);
      document.getElementById('counter-elapsed').textContent = `${elapsedSec}s`;
      // update speed (domains per second)
      const speed = (checkedCount / elapsedSec).toFixed(2);
      document.getElementById('counter-speed').textContent = speed;

      await new Promise(r => setTimeout(r, 200));
    }
    const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
    // final speed calculation
    document.getElementById('counter-speed').textContent = (checkedCount / elapsed).toFixed(2);
    const doneLine = document.createElement('div');
    doneLine.textContent = `All ${data.length} domains checked in ${elapsed}s`;
    logsContainer.appendChild(doneLine);
    logsContainer.scrollTop = logsContainer.scrollHeight;

    // render results using Grid.js
    new gridjs.Grid({
      columns: ['Domain', 'Status', 'Detail'],
      data: data.map(item => [
        item.domain,
        gridjs.html(`<span class="badge ${item.ok ? 'badge-success' : 'badge-error'}">${item.ok ? 'Online' : 'Offline'}</span>`),
        item.detail
      ]),
      pagination: { enabled: true, limit: 10 },
      sort: true,
      style: {
        table: { 'width': '100%' },
        th: { 'background-color': 'var(--b2)', 'color': 'var(--p2)' },
        td: { 'background-color': 'var(--b1)', 'color': 'var(--p2)' }
      }
    }).render(gridContainer);
  } catch (err) {
    gridContainer.innerHTML = `<p class="text-error">Error: ${err.message}</p>`;
  } finally {
    loader.classList.add('hidden');
    checkBtn.disabled = false;
  }
});

// Subtle animation for details opening (insert CSS)
const style = document.createElement('style');
style.innerHTML = `
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.animate-fadeIn { animation: fadeIn 0.3s ease-in-out; }
`;
document.head.appendChild(style);

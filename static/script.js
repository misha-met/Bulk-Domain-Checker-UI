// Domain check flow (default light mode, dark mode removed)
const checkBtn = document.getElementById('check-btn');
const loader = document.getElementById('loader');
const resultsContainer = document.getElementById('results-container');
// DataTable instance for live-updating table
let dataTable;

checkBtn.addEventListener('click', async () => {
  const raw = document.getElementById('domains-input').value;
  const domains = raw.split(/\s+/).filter(Boolean);
  if (!domains.length) return;

  // UI state
  checkBtn.disabled = true;
  loader.classList.remove('hidden');
  // Reset DataTable if exists
  if (dataTable) {
    dataTable.clear().destroy();
  }
  resultsContainer.classList.remove('hidden'); // Show the table container
  // Initialize DataTable
  dataTable = $('#results-table').DataTable({
    scrollY: '300px',
    scrollCollapse: true,
    paging: false,
    info: false,
    searching: false,
    ordering: true,
    autoWidth: false,
  });

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
    // sequential log animation AND live table update
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

      // --- Add row to live table --- START
      // Add row via DataTables API for live update
      dataTable.row.add([
        item.domain,
        `<span class="badge ${item.ok ? 'badge-success' : 'badge-error'}">${item.ok ? 'Online' : 'Offline'}</span>`,
        item.detail
      ]).draw(false);
      // --- Add row to live table --- END

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

    // Live DataTable rows have been added; no final render needed

  } catch (err) {
    // Display error somewhere appropriate, maybe above the (now empty) table
    resultsContainer.insertAdjacentHTML('beforebegin', `<p id="fetch-error" class="text-error mb-2">Error fetching results: ${err.message}</p>`);
    // Clear any potential partial results if fetch failed completely
    if (dataTable) {
      dataTable.clear().destroy();
    }
  } finally {
    loader.classList.add('hidden');
    checkBtn.disabled = false;
    // Clear any previous error message on new run
    document.getElementById('fetch-error')?.remove();
  }
});

// Subtle animation for details opening (insert CSS)
const style = document.createElement('style');
style.innerHTML = `
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.animate-fadeIn { animation: fadeIn 0.3s ease-in-out; }
`;
document.head.appendChild(style);

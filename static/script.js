// Domain check flow (default light mode, dark mode removed)
const checkBtn = document.getElementById('check-btn');
// const loader = document.getElementById('loader'); // removed loader element
const resultsContainer = document.getElementById('results-container');
// DataTable instance for live-updating table
let dataTable;

checkBtn.addEventListener('click', async () => {
  const raw = document.getElementById('domains-input').value;
  const domains = raw.split(/\s+/).filter(Boolean);
  const totalDomains = domains.length;
  if (!totalDomains) return;

  // UI state
  checkBtn.disabled = true;
  checkBtn.textContent = 'Checking...';
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

  // Initialize NEW dashboard metrics
  document.getElementById('stat-total-value').textContent = totalDomains;
  document.getElementById('stat-checked-value').textContent = '0';
  document.getElementById('stat-checked-percent').textContent = '0%';
  document.getElementById('stat-online-value').textContent = '0';
  document.getElementById('stat-online-percent').textContent = '0%';
  document.getElementById('stat-failed-value').textContent = '0';
  document.getElementById('stat-failed-percent').textContent = '0%';
  document.getElementById('stat-elapsed-value').textContent = '0.0s';
  document.getElementById('stat-speed-value').textContent = '0.0';

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

      // update NEW dashboard metrics
      checkedCount++;
      document.getElementById('stat-checked-value').textContent = checkedCount;
      const checkedPercent = totalDomains > 0 ? Math.round((checkedCount / totalDomains) * 100) : 0;
      document.getElementById('stat-checked-percent').textContent = `${checkedPercent}%`;

      if (item.ok) {
        onlineCount++;
        document.getElementById('stat-online-value').textContent = onlineCount;
      } else {
        failedCount++;
        document.getElementById('stat-failed-value').textContent = failedCount;
      }

      const onlinePercent = checkedCount > 0 ? Math.round((onlineCount / checkedCount) * 100) : 0;
      const failedPercent = checkedCount > 0 ? Math.round((failedCount / checkedCount) * 100) : 0;
      document.getElementById('stat-online-percent').textContent = `${onlinePercent}%`;
      document.getElementById('stat-failed-percent').textContent = `${failedPercent}%`;

      // update elapsed timer
      const elapsedSec = ((performance.now() - startTime) / 1000);
      document.getElementById('stat-elapsed-value').textContent = `${elapsedSec.toFixed(1)}s`;

      // update speed (domains per second)
      const speed = elapsedSec > 0 ? (checkedCount / elapsedSec) : 0;
      document.getElementById('stat-speed-value').textContent = speed.toFixed(1);

      await new Promise(r => setTimeout(r, 200)); // Keep delay for visual effect
    }
    const finalElapsed = ((performance.now() - startTime) / 1000);
    const finalSpeed = finalElapsed > 0 ? (checkedCount / finalElapsed) : 0;
    document.getElementById('stat-speed-value').textContent = finalSpeed.toFixed(1);
    const doneLine = document.createElement('div');
    doneLine.textContent = `All ${data.length} domains checked in ${finalElapsed.toFixed(1)}s`;
    logsContainer.appendChild(doneLine);
    logsContainer.scrollTop = logsContainer.scrollHeight;

    // Live DataTable rows have been added; no final render needed

  } catch (err) { // <-- Ensure this catch block is correctly placed
    // Display error somewhere appropriate, maybe above the (now empty) table
    resultsContainer.insertAdjacentHTML('beforebegin', `<p id="fetch-error" class="text-error mb-2">Error fetching results: ${err.message}</p>`);
    // Clear any potential partial results if fetch failed completely
    if (dataTable) {
      dataTable.clear().destroy();
    }
  } finally {
    checkBtn.disabled = false;
    checkBtn.textContent = 'Check Domains';
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

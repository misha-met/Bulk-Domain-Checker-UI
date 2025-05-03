// Domain check flow (default light mode, dark mode removed)
const checkBtn = document.getElementById('check-btn');
const buttonTextSpan = checkBtn.querySelector('.button-text'); // Get the span inside the button
// const loader = document.getElementById('loader'); // removed loader element
const resultsContainer = document.getElementById('results-container');
const downloadButtonsContainer = document.getElementById('download-buttons-container'); // Get download buttons container
const downloadCsvBtn = document.getElementById('download-csv-btn');
const downloadTxtBtn = document.getElementById('download-txt-btn');
const resultsPanel = document.getElementById('results-panel'); // Get the results panel

// DataTable instance for live-updating table
let dataTable;
let currentResults = []; // Store results for download
let elapsedTimeInterval = null; // Variable to hold the interval timer ID

checkBtn.addEventListener('click', async () => {
  const raw = document.getElementById('domains-input').value;
  const domains = raw.split(/\s+/).filter(Boolean);
  const totalDomains = domains.length;
  if (!totalDomains) return;

  // UI state
  checkBtn.disabled = true;
  buttonTextSpan.innerHTML = '<span class="btn-shine">Checking Domains</span>'; // Apply shine animation
  resultsPanel.classList.add('border', 'border-gray-700'); // Add border when checking starts
  // Reset DataTable if exists
  if (dataTable) {
    dataTable.clear().destroy();
    dataTable = null; // Ensure it's fully reset
  }
  resultsContainer.classList.remove('hidden'); // Show the table container
  downloadButtonsContainer.classList.add('hidden'); // Hide download buttons initially
  currentResults = []; // Clear previous results
  // Initialize DataTable
  dataTable = $('#results-table').DataTable({
    scrollY: '300px',
    scrollCollapse: true,
    paging: false,
    info: false,
    searching: true, // Enable search box
    ordering: true,
    autoWidth: false,
    deferRender: true,       // improve performance on large datasets
    scroller: true,          // enable virtualized scrolling
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
  let startTimeLocal = null; // Initialize start time variable

  // Clear any previous timer
  if (elapsedTimeInterval) {
    clearInterval(elapsedTimeInterval);
    elapsedTimeInterval = null;
  }

  try {
    startTimeLocal = performance.now(); // Record start time

    // Start the elapsed time timer
    elapsedTimeInterval = setInterval(() => {
        if (startTimeLocal) {
            const elapsedSec = ((performance.now() - startTimeLocal) / 1000);
            document.getElementById('stat-elapsed-value').textContent = `${elapsedSec.toFixed(1)}s`;
        }
    }, 100); // Update every 100ms for smoother display

    const response = await fetch('/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domains })
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    // batching to reduce DOM thrash
    const pendingItems = [];
    let flushScheduled = false;
    function scheduleFlush() {
      if (!flushScheduled) {
        flushScheduled = true;
        setTimeout(flushItems, 100);
      }
    }
    function flushItems() {
      const now = new Date();
      const timestamp = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

      for (const item of pendingItems) {
        // logs - Terminal Style
        const cmdDiv = document.createElement('div');
        cmdDiv.innerHTML = `<span class="text-gray-500">[${timestamp}]</span> <span class="text-blue-400">$</span> check_domain ${item.domain}`;
        logsContainer.appendChild(cmdDiv);

        const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error' : 'Offline');
        const statusColor = item.ok ? 'text-green-400' : 'text-red-400';
        const resultDiv = document.createElement('div');
        // Display the actual detail from the backend (status code, TCP connect, DNS, or error)
        resultDiv.innerHTML = `<span class="text-gray-500">[${timestamp}]</span> <span class="${statusColor}">Status: ${statusText}</span>, Detail: ${item.detail}`;
        logsContainer.appendChild(resultDiv);

        // prune logs to limit DOM size
        if (logsContainer.children.length > 1000) {
          logsContainer.removeChild(logsContainer.firstChild);
        }

        // Store result for download
        currentResults.push(item);

        // table row - Use item.detail directly for successful checks
        dataTable.row.add([
          item.domain,
          `<span class="badge ${item.ok ? 'badge-success' : 'badge-error'}">${statusText}</span>`,
          item.detail // Show the actual detail (status code, TCP, DNS, error)
        ]);

        // stats
        checkedCount++;
        if (item.ok) onlineCount++; else failedCount++;
      }
      // redraw table once per batch
      dataTable.draw(false);
      // update metrics display
      document.getElementById('stat-checked-value').textContent = checkedCount;
      document.getElementById('stat-checked-percent').textContent = `${Math.round((checkedCount/totalDomains)*100)}%`;
      document.getElementById('stat-online-value').textContent = onlineCount;
      document.getElementById('stat-online-percent').textContent = `${Math.round((onlineCount/checkedCount)*100)}%`;
      document.getElementById('stat-failed-value').textContent = failedCount;
      document.getElementById('stat-failed-percent').textContent = `${Math.round((failedCount/checkedCount)*100)}%`;
      document.getElementById('stat-speed-value').textContent = `${(checkedCount/((performance.now() - startTimeLocal)/1000)).toFixed(1)}`;
      // clear buffer and reset flag
      pendingItems.length = 0;
      flushScheduled = false;
      // scroll logs
      logsContainer.scrollTop = logsContainer.scrollHeight;
    }
    // stream each result line as JSON
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
            pendingItems.push(JSON.parse(line));
            scheduleFlush();
        } catch (e) {
            console.error("Failed to parse JSON line:", line, e);
            // Optionally add error handling for individual line parse failures
        }
      }
    }
    // flush any remaining items and final summary
    if (pendingItems.length) flushItems();
    const doneLine = document.createElement('div');
    doneLine.textContent = `All ${totalDomains} domains checked. Final time: ${document.getElementById('stat-elapsed-value').textContent}`;
    logsContainer.appendChild(doneLine);
    logsContainer.scrollTop = logsContainer.scrollHeight;

    // Show download buttons if there are results
    if (currentResults.length > 0) {
        downloadButtonsContainer.classList.remove('hidden');
    }

  } catch (err) { // <-- Ensure this catch block is correctly placed
    // Display error somewhere appropriate, maybe above the (now empty) table
    resultsContainer.insertAdjacentHTML('beforebegin', `<p id="fetch-error" class="text-error mb-2">Error fetching results: ${err.message}</p>`);
    // Clear any potential partial results if fetch failed completely
    if (dataTable) {
      dataTable.clear().destroy();
    }
    // Hide download buttons on error
    downloadButtonsContainer.classList.add('hidden');
    resultsPanel.classList.remove('border', 'border-gray-700'); // Remove border on error
  } finally {
    // Stop the timer when done or on error
    if (elapsedTimeInterval) {
        clearInterval(elapsedTimeInterval);
        elapsedTimeInterval = null;
    }
    checkBtn.disabled = false;
    buttonTextSpan.innerHTML = 'Check Domains'; // Restore original text
    // Clear any previous error message on new run
    document.getElementById('fetch-error')?.remove();
    // Keep border only if results were successfully fetched and displayed
    if (!currentResults.length) { // Check if currentResults array is empty
        resultsPanel.classList.remove('border', 'border-gray-700');
    }
  }
});

// Function to trigger file download
function downloadFile(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// Download CSV handler
downloadCsvBtn.addEventListener('click', () => {
    if (!currentResults.length) return;
    let csvContent = "Domain,Status,Detail\n"; // Header row
    for (const item of currentResults) { // Changed from forEach to for...of
        const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error' : 'Offline');
        // Escape commas and quotes in detail
        const detail = `"${item.detail.replace(/"/g, '""')}"`;
        csvContent += `${item.domain},${statusText},${detail}\n`;
    }
    downloadFile('domain_results.csv', csvContent, 'text/csv;charset=utf-8;');
});

// Download TXT handler
downloadTxtBtn.addEventListener('click', () => {
    if (!currentResults.length) return;
    let txtContent = "";
    for (const item of currentResults) { // Changed from forEach to for...of
        const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error' : 'Offline');
        txtContent += `${item.domain}: ${statusText} - ${item.detail}\n`;
    }
    downloadFile('domain_results.txt', txtContent, 'text/plain;charset=utf-8;');
});

// Subtle animation for details opening (insert CSS)
const style = document.createElement('style');
style.innerHTML = `
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.animate-fadeIn { animation: fadeIn 0.3s ease-in-out; }
`;
document.head.appendChild(style);

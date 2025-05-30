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

// Function to toggle redirect history visibility
function toggleRedirectHistory(redirectId) {
  const element = document.getElementById(redirectId);
  const isHidden = element.style.display === 'none';
  element.style.display = isHidden ? 'block' : 'none';
  
  // Update the arrow indicator and text
  const badge = element.previousElementSibling;
  if (badge && badge.textContent) {
    if (isHidden) {
      badge.textContent = badge.textContent.replace('Show Redirects ▼', 'Hide Redirects ▲');
    } else {
      badge.textContent = badge.textContent.replace('Hide Redirects ▲', 'Show Redirects ▼');
    }
  }
}

checkBtn.addEventListener('click', async () => {
  const raw = document.getElementById('domains-input').value;
  const domains = raw.split(/\s+/).filter(Boolean);
  const totalDomains = domains.length;
  
  // Get cache options
  const useCache = document.getElementById('use-cache').checked;
  const addToCache = document.getElementById('add-to-cache').checked;
  
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
  
  // Clear the table HTML content to ensure clean state
  $('#results-table tbody').empty();
  
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
    data: [],                // Start with empty data array
    columns: [
      { title: "Domain", data: 0 },
      { title: "Status", data: 1 },
      { title: "Detail & Redirects", data: 2 },
      { title: "Source", data: 3 }
    ]
  });

  // Terminal display removed - backend logging still functions
  // const logPanel = document.getElementById('log-panel');
  // const logsContainer = document.getElementById('logs');
  // if (logsContainer) logsContainer.innerHTML = '';
  // if (logPanel) logPanel.classList.remove('hidden');

  // Terminal banner and system info removed from UI
  // Banner and system info generation skipped - backend logging still active

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
      body: JSON.stringify({ 
        domains,
        use_cache: useCache,
        add_to_cache: addToCache
      })
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
        // Terminal logging removed - process data for table only

        // Store result for download
        currentResults.push(item);

        // table row - Enhanced display with expandable redirect history
        let tableDetail = item.detail;
        let redirectDisplay = '';
        
        if (item.redirect_count && item.redirect_count > 0 && item.redirect_history) {
          // Create a unique ID for this row's redirect details
          const redirectId = `redirect-${item.domain.replace(/[^a-zA-Z0-9]/g, '-')}-${Date.now()}`;
          
          // Create redirect badge with click handler - Updated for dark theme
          const redirectBadge = `<span class="text-yellow-200 text-xs bg-yellow-800 px-2 py-1 rounded-full cursor-pointer" onclick="toggleRedirectHistory('${redirectId}')">Show Redirects ▼</span>`;
          
          // Create detailed redirect history (initially hidden) - Updated for dark theme
          redirectDisplay = `
            <div id="${redirectId}" class="redirect-history" style="display: none;">
              <div style="font-weight: 600; margin-bottom: 8px; color: #fbbf24;">Redirect Chain:</div>
              ${item.redirect_history.map((step, index) => {
                const isLast = index === item.redirect_history.length - 1;
                const statusColor = step.status_code < 400 ? '#4ade80' : '#f87171';
                return `
                  <div class="redirect-step">
                    <div class="redirect-step-number">${step.step}</div>
                    <div class="redirect-step-url">${step.url}</div>
                    <div class="redirect-step-status" style="color: ${statusColor};">${step.status_code}</div>
                  </div>
                `;
              }).join('')}
            </div>`;
          
          tableDetail = `${item.detail} ${redirectBadge}${redirectDisplay}`;
        }
        
        const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error' : 'Offline');
        dataTable.row.add([
          item.domain,
          `<span class="badge ${item.ok ? 'badge-success' : 'badge-error'}">${statusText}</span>`,
          tableDetail, // Show the detail with expandable redirect history
          item.from_cache ? '<span class="badge badge-outline text-blue-400">Cache</span>' : '<span class="badge badge-outline text-green-400">Live</span>'
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
      // Log scrolling removed since terminal is hidden
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
    // flush any remaining items - terminal completion message removed
    if (pendingItems.length) flushItems();
    // Terminal completion logging removed since log panel is hidden

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
    let csvContent = "Domain,Status,Detail,Redirects,Redirect_Chain,Source\n"; // Enhanced header row
    for (const item of currentResults) { // Changed from forEach to for...of
        const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error' : 'Offline');
        const source = item.from_cache ? 'Cache' : 'Live';
        
        // Escape commas and quotes in detail
        const detail = `"${item.detail.replace(/"/g, '""')}"`;
        
        // Create redirect chain string
        let redirectChain = '';
        if (item.redirect_history && item.redirect_history.length > 1) {
            redirectChain = item.redirect_history.map(step => 
                `${step.status_code}:${step.url}`
            ).join(' -> ');
        }
        redirectChain = `"${redirectChain.replace(/"/g, '""')}"`;
        
        csvContent += `${item.domain},${statusText},${detail},${item.redirect_count || 0},${redirectChain},${source}\n`;
    }
    downloadFile('domain_results.csv', csvContent, 'text/csv;charset=utf-8;');
});

// Download TXT handler
downloadTxtBtn.addEventListener('click', () => {
    if (!currentResults.length) return;
    let txtContent = "Domain Check Results\n";
    txtContent += "===================\n\n";
    
    for (const item of currentResults) { // Changed from forEach to for...of
        const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error' : 'Offline');
        const source = item.from_cache ? 'Cache' : 'Live';
        
        txtContent += `Domain: ${item.domain}\n`;
        txtContent += `Status: ${statusText}\n`;
        txtContent += `Detail: ${item.detail}\n`;
        txtContent += `Source: ${source}\n`;
        
        if (item.redirect_history && item.redirect_history.length > 1) {
            txtContent += `Redirects: ${item.redirect_count}\n`;
            txtContent += `Redirect Chain:\n`;
            item.redirect_history.forEach((step, index) => {
                const isLast = index === item.redirect_history.length - 1;
                const arrow = isLast ? '' : ' →';
                txtContent += `  ${step.step}. ${step.status_code} - ${step.url}${arrow}\n`;
            });
        }
        txtContent += "\n";
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

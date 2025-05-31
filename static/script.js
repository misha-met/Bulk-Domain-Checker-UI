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

// Function to toggle cache options visibility
function toggleCacheOptions() {
  const content = document.getElementById('cache-options-content');
  const arrow = document.querySelector('.cache-options-arrow');
  const isHidden = content.style.display === 'none';
  
  if (isHidden) {
    content.style.display = 'block';
    arrow.style.transform = 'rotate(180deg)';
  } else {
    content.style.display = 'none';
    arrow.style.transform = 'rotate(0deg)';
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
      { title: "Code", data: 2 },
      { title: "Redirect", data: 3 },
      { title: "Source", data: 4 }
    ]
  });

  // Add export database button to the filter row
  addExportButtonToFilter();
  
  // Add click handlers to table rows
  addTableRowClickHandlers();

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

        // Prepare separate code and redirect columns
        let codeColumn = truncateText(item.detail); // Truncate long error messages
        let redirectColumn = ''; // Redirect information
        
        if (item.redirect_count && item.redirect_count > 0 && item.redirect_history) {
          // Simplified redirect info for table
          redirectColumn = `<span class="badge badge-outline text-yellow-400">${item.redirect_count} redirect${item.redirect_count > 1 ? 's' : ''}</span>`;
        }
        
        const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error' : 'Offline');
        dataTable.row.add([
          item.domain,
          `<span class="badge ${item.ok ? 'badge-success' : 'badge-error'}">${statusText}</span>`,
          codeColumn, // Truncated status code or error message
          redirectColumn, // Simplified redirect information
          item.from_cache ? '<span class="badge badge-outline text-blue-400">Cache</span>' : '<span class="badge badge-outline text-green-400">Live</span>'
        ]);

        // stats
        checkedCount++;
        if (item.ok) onlineCount++; else failedCount++;
      }
      // redraw table once per batch
      dataTable.draw(false);
      // Add click handlers to new rows
      addTableRowClickHandlers();
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
    let csvContent = "Domain,Status,Code,Redirect,Redirect_Chain,Source\n"; // Updated header row
    for (const item of currentResults) { // Changed from forEach to for...of
        const statusText = item.ok ? 'Online' : (item.detail.includes('Error') ? 'Error' : 'Offline');
        const source = item.from_cache ? 'Cache' : 'Live';
        
        // Escape commas and quotes in detail
        const code = `"${item.detail.replace(/"/g, '""')}"`;
        
        // Create redirect info
        const redirectInfo = item.redirect_count && item.redirect_count > 0 ? `"${item.redirect_count} redirect(s)"` : '""';
        
        // Create redirect chain string
        let redirectChain = '';
        if (item.redirect_history && item.redirect_history.length > 1) {
            redirectChain = item.redirect_history.map(step => 
                `${step.status_code}:${step.url}`
            ).join(' -> ');
        }
        redirectChain = `"${redirectChain.replace(/"/g, '""')}"`;
        
        csvContent += `${item.domain},${statusText},${code},${redirectInfo},${redirectChain},${source}\n`;
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

// Function to create export database button
function createExportDbButton() {
  const exportContainer = document.createElement('div');
  exportContainer.className = 'export-db-container';
  
  const exportBtn = document.createElement('button');
  exportBtn.id = 'export-db-btn';
  exportBtn.className = 'btn-export-db btn btn-primary btn-sm';
  exportBtn.textContent = 'Export Database';
  exportBtn.title = 'Export database cache to CSV';
  
  exportBtn.addEventListener('click', async () => {
    try {
      exportBtn.disabled = true;
      exportBtn.textContent = 'Exporting...';
      
      const response = await fetch('/export-cache', {
        method: 'GET',
        headers: {
          'Accept': 'text/csv'
        }
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      
      // Create filename with timestamp
      const now = new Date();
      const timestamp = now.toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const filename = `domain_cache_export_${timestamp}.csv`;
      
      // Create download link
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      
      // Cleanup
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      
    } catch (error) {
      console.error('Export failed:', error);
      alert(`Export failed: ${error.message}`);
    } finally {
      exportBtn.disabled = false;
      exportBtn.textContent = 'Export Database';
    }
  });
  
  exportContainer.appendChild(exportBtn);
  return exportContainer;
}

// Function to add export button to DataTables filter row
function addExportButtonToFilter() {
  // Use a small delay to ensure DataTables has rendered the filter
  setTimeout(() => {
    const filterDiv = document.querySelector('.dataTables_filter');
    if (filterDiv && !document.getElementById('export-db-btn')) {
      // Create wrapper container
      const wrapperDiv = document.createElement('div');
      wrapperDiv.className = 'dataTables_filter_wrapper';
      
      // Create export button container and button
      const exportContainer = createExportDbButton();
      
      // Insert wrapper before the filter div
      filterDiv.parentNode.insertBefore(wrapperDiv, filterDiv);
      
      // Move filter div into wrapper
      wrapperDiv.appendChild(exportContainer);
      wrapperDiv.appendChild(filterDiv);
      
      // Update search input placeholder and remove label text
      const searchLabel = filterDiv.querySelector('label');
      const searchInput = filterDiv.querySelector('input[type="search"]');
      if (searchLabel && searchInput) {
        // Remove the "Search:" text from the label
        searchLabel.childNodes.forEach(node => {
          if (node.nodeType === Node.TEXT_NODE) {
            node.textContent = '';
          }
        });
        searchInput.placeholder = 'Search results...';
      }
    }
  }, 100);
}

// Call to add export button to filter row on DataTable init
$(document).ready(function() {
  // Initialize DataTable first
  dataTable = $('#results-table').DataTable({
    // ... your existing DataTable options ...
  });
  
  // Then add the export button
  addExportButtonToFilter();
});

// Subtle animation for details opening (insert CSS)
const style = document.createElement('style');
style.innerHTML = `
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.animate-fadeIn { animation: fadeIn 0.3s ease-in-out; }
`;
document.head.appendChild(style);

// Modal functionality for domain details
function showDomainDetails(domainData) {
  const modal = document.getElementById('domain-details-modal');
  const domainName = document.getElementById('modal-domain-name');
  const status = document.getElementById('modal-status');
  const details = document.getElementById('modal-details');
  const source = document.getElementById('modal-source');
  const redirectSection = document.getElementById('modal-redirect-section');
  const redirectDetails = document.getElementById('modal-redirect-details');

  // Populate modal with data
  domainName.textContent = domainData.domain;
  
  const statusText = domainData.ok ? 'Online' : (domainData.detail.includes('Error') ? 'Error' : 'Offline');
  const statusClass = domainData.ok ? 'badge-success' : 'badge-error';
  status.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
  
  // Show full details in modal (no truncation)
  details.textContent = domainData.detail;
  
  const sourceText = domainData.from_cache ? 'Cache' : 'Live';
  const sourceClass = domainData.from_cache ? 'text-blue-400' : 'text-green-400';
  source.innerHTML = `<span class="badge badge-outline ${sourceClass}">${sourceText}</span>`;

  // Handle redirect information
  if (domainData.redirect_count && domainData.redirect_count > 0 && domainData.redirect_history) {
    redirectSection.classList.remove('hidden');
    
    const redirectHtml = domainData.redirect_history.map((step, index) => {
      const statusColor = step.status_code < 400 ? '#4ade80' : '#f87171';
      return `
        <div class="redirect-step" style="margin: 8px 0; padding: 8px; background-color: #111111; border-radius: 4px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <div style="background-color: #4ade80; color: #000000; border-radius: 50%; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: 600;">
              ${step.step}
            </div>
            <div style="flex-grow: 1; font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace; font-size: 0.8rem; word-break: break-all; color: #60a5fa;">
              ${step.url}
            </div>
            <div style="color: ${statusColor}; font-weight: 600; font-size: 0.875rem;">
              ${step.status_code}
            </div>
          </div>
        </div>
      `;
    }).join('');
    
    redirectDetails.innerHTML = redirectHtml;
  } else {
    redirectSection.classList.add('hidden');
  }

  // Show modal
  modal.classList.remove('hidden');
}

function hideDomainDetails() {
  const modal = document.getElementById('domain-details-modal');
  modal.classList.add('hidden');
}

// Add modal event listeners
document.addEventListener('DOMContentLoaded', function() {
  const modal = document.getElementById('domain-details-modal');
  const closeBtn = document.getElementById('modal-close-btn');
  
  // Close modal when clicking close button
  closeBtn.addEventListener('click', hideDomainDetails);
  
  // Close modal when clicking overlay (but not modal content)
  modal.addEventListener('click', function(e) {
    if (e.target === modal) {
      hideDomainDetails();
    }
  });
  
  // Close modal with Escape key
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
      hideDomainDetails();
    }
  });
});

// Function to truncate text for table display
function truncateText(text, maxLength = 30) {
  if (!text) return text;
  
  // Clean up status codes - remove "HTTP " prefix and "(HTTP/1.1 fallback)" suffix
  let cleaned = text.replace(/^HTTP\s+/, '').replace(/\s*\(HTTP\/1\.1 fallback\)/, '');
  
  // If it's just a number now (status code), return it as-is
  if (/^\d+$/.test(cleaned)) {
    return cleaned;
  }
  
  if (cleaned.length <= maxLength) return cleaned;
  
  // Special handling for common error patterns
  if (cleaned.includes('DNS resolution failed')) {
    return 'DNS resolution failed';
  }
  if (cleaned.includes('Connection timeout')) {
    return 'Connection timeout';
  }
  if (cleaned.includes('Connection refused')) {
    return 'Connection refused';
  }
  if (cleaned.includes('SSL')) {
    return 'SSL error';
  }
  if (cleaned.includes('Certificate')) {
    return 'Certificate error';
  }
  
  return cleaned.substring(0, maxLength) + '...';
}

// Function to add click handlers to table rows for modal display
function addTableRowClickHandlers() {
  // Remove existing click handlers to prevent duplicates
  $('#results-table tbody').off('click', 'tr');
  
  // Add click handler for table rows
  $('#results-table tbody').on('click', 'tr', function() {
    // Use DataTables API to get the correct row data
    const rowData = dataTable.row(this).data();
    if (rowData && rowData.length > 0) {
      // Find the corresponding domain data in currentResults by matching the domain name
      const domainName = rowData[0]; // Domain is in the first column
      const domainData = currentResults.find(item => item.domain === domainName);
      if (domainData) {
        showDomainDetails(domainData);
      }
    }
  });
}

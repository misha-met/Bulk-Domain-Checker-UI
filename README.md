# Domain Responsiveness Checker

A Python application with both a web interface and a command-line tool to check the responsiveness of a list of domains.

![Web UI Demo](Demo.png)

It determines if a domain is responsive by checking:
1.  HTTPS and HTTP status codes (success or redirect indicates responsiveness).
2.  TCP connection success on ports 443 and 80 (indicates responsiveness).
3.  DNS resolution success (indicates responsiveness).

If all checks fail, the domain is considered unresponsive.

## Features

*   **Dual Interface:** Use via a web UI (Flask/Uvicorn) or a command-line script.
*   **Bulk Domain Checking:** Input multiple domains for concurrent checking.
*   **Multiple Check Methods:** Uses HTTP GET, TCP connect, and DNS resolution for comprehensive checks.
*   **Real-time Updates (Web UI):** View results streamed to a table with live statistics dashboard.
*   **Intelligent Caching:** SQLite-based caching system stores successful results for faster subsequent checks.
*   **Detailed Results:** Shows domain status (e.g., Online, Offline, Error) and the reason (e.g., HTTP status, TCP connect, DNS resolution, specific error).
*   **Redirect Tracking:** Comprehensive redirect chain analysis with step-by-step history display.
*   **Performance Metrics (Web UI):** Displays progress, counts, elapsed time, and check speed.
*   **Download Results (Web UI):** Export check results as CSV or TXT files with full redirect information.
*   **Database Export:** Export cached results to CSV format with detailed redirect chains.
*   **Formatted Output (CLI):** Displays results in a clear table using Rich, with a summary and breakdown.
*   **Logging (CLI):** Saves detailed results to a log file (`domain_check.log` by default).

## Prerequisites

*   Python 3.8+ (due to `asyncio` and `httpx` usage)
*   pip (Python package installer)

## Installation

1.  **Clone the repository:**
    ```bash
    # Replace <your-repository-url> with the actual URL
    git clone <your-repository-url>
    cd <repository-directory-name>
    ```
2.  **Create and activate a virtual environment (recommended):**
    *   On macOS/Linux:
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```
    *   On Windows (Command Prompt):
        ```bash
        python -m venv venv
        .\venv\Scripts\activate.bat
        ```
    *   On Windows (PowerShell):
        ```bash
        python -m venv venv
        .\venv\Scripts\Activate.ps1
        ```
3.  **Install the required Python packages:**
    ```bash
    pip install -r requirements.txt
    ```
    *(See `requirements.txt` for details on the libraries used.)*

## Running the Application

You can run either the Web UI or the Command-Line Interface.

### Web UI

1.  **Start the server:**
    ```bash
    # This uses uvicorn to run the Flask app via an ASGI adapter
    python app.py
    ```
    The server will typically start on `http://127.0.0.1:8000` (check terminal output).

2.  **Access the application:**
    Open your web browser and navigate to the address shown in the terminal.

3.  **Usage:**
    *   Enter domains (one per line or space-separated) into the text area.
    *   Configure cache options:
        *   **Use cached results:** Retrieve previously checked domains from cache for faster results
        *   **Save results to cache:** Store new check results in cache for future use
    *   Click "Check Domains".
    *   Results stream into the table with real-time statistics.
    *   View detailed redirect chains by clicking on redirect badges in results.
    *   Use download buttons for CSV/TXT export with full redirect information.

## Caching System

The application includes an intelligent SQLite-based caching system that significantly improves performance for repeated domain checks:

### Features
*   **Automatic Caching:** Successful HTTP responses (2xx, 3xx, 4xx status codes) are automatically cached
*   **Smart Cache Logic:** Connection errors and DNS failures are not cached to ensure fresh attempts
*   **Redirect History:** Full redirect chains are stored and displayed with step-by-step analysis
*   **Configurable Options:** Choose whether to use existing cache and save new results
*   **Cache Management:** Built-in cache statistics and cleanup functionality

### Cache Export
Export cached domain results to CSV format for analysis:

```bash
# Export all cached results with full details
python export_csv.py

# Export to specific file
python export_csv.py --output my_domains.csv

# Simple export without redirect details
python export_csv.py --simple

# View cache statistics only
python export_csv.py --stats-only
```

### Database Structure
The cache stores:
*   Domain name and check results
*   HTTP status codes and redirect counts
*   Complete redirect chains with URLs and status codes
*   Timestamps for cache expiry management

### Command-Line Interface (CLI)

1.  **Prepare an input file:**
    Create a text file (e.g., `domains.txt`) with one domain per line.
    ```
    google.com
    github.com
    this-domain-probably-does-not-exist-asdfjkl.com
    microsoft.com
    ```

2.  **Run the script:**
    ```bash
    python check_domains.py <your-domain-file.txt> [options]
    ```
    *   Replace `<your-domain-file.txt>` with the path to your file (e.g., `domains.txt`).
    *   **Options:**
        *   `--timeout <seconds>`: Set the timeout for checks (default: 5).
        *   `--workers <number>`: Set the max concurrent checks (default: 100).
        *   `--log-file <path>`: Specify the output log file path (default: `domain_check.log`).

    **Example:**
    ```bash
    python check_domains.py domains.txt --workers 50 --timeout 10
    ```

3.  **Output:**
    *   Results are printed to the console in formatted tables.
    *   A detailed log is saved to the specified log file.

## Technologies Used

*   **Backend:** Python, Flask (Web UI), Uvicorn (ASGI Server), httpx (HTTP Client), asyncio
*   **Database:** SQLite (for caching domain check results)
*   **Frontend:** HTML, CSS (Tailwind CSS via CDN), JavaScript, DataTables.js
*   **CLI:** Python, argparse, httpx, asyncio, Rich (Tables/Formatting), tqdm (Progress Bar)
*   **Export:** CSV export functionality with redirect chain analysis

## How it Works

The `check_domains.py` script contains the core domain checking logic:

1.  It takes a domain and first tries `HTTPS GET`, then `HTTP GET` with manual redirect tracking.
2.  **Redirect Analysis:** Each redirect step is captured with URLs and status codes for detailed chain analysis.
3.  If a final status code < 400 (Success or Redirect) is received, the domain is marked as **Online**.
4.  If HTTP checks fail, it attempts a direct TCP connection to the host on port 443, then port 80. Success marks it as **Online**.
5.  If TCP checks fail, it attempts DNS resolution. Success marks it as **Online** (with a note that only DNS resolved).
6.  If all checks fail, the domain is marked as **Offline**, reporting the last known error.
7.  **Caching:** Successful results are stored in SQLite database for faster future checks.

The `app.py` provides a Flask web interface that calls the checking logic via `run_stream` (an async generator) and streams results back to the browser using a background thread and queue mechanism compatible with Flask/Uvicorn.

The `database.py` module handles intelligent caching with automatic cleanup and export capabilities.



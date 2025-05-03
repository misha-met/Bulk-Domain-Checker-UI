# Domain Availability Checker

A Python application with both a web interface and a command-line tool to check the availability and responsiveness of a list of domains.

It determines if a domain is potentially available or taken by checking:
1.  HTTPS and HTTP status codes (success or redirect indicates taken).
2.  TCP connection success on ports 443 and 80 (indicates taken).
3.  DNS resolution success (indicates taken).

If all checks fail, the domain is considered potentially available (or unresponsive).

## Features

*   **Dual Interface:** Use via a web UI (Flask/Uvicorn) or a command-line script.
*   **Bulk Domain Checking:** Input multiple domains for concurrent checking.
*   **Multiple Check Methods:** Uses HTTP GET, TCP connect, and DNS resolution for comprehensive checks.
*   **Real-time Updates (Web UI):** View results streamed to a table and log panel.
*   **Detailed Results:** Shows domain status (Online/Taken, Offline/Available) and the reason (e.g., HTTP status, TCP connect, DNS resolution, specific error).
*   **Performance Metrics (Web UI):** Displays progress, counts, elapsed time, and check speed.
*   **Download Results (Web UI):** Export check results as CSV or TXT files.
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
    *   Click "Check Domains".
    *   Results stream into the table and log panel.
    *   Use download buttons for CSV/TXT export.

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
*   **Frontend:** HTML, CSS (Tailwind CSS via CDN), JavaScript, DataTables.js
*   **CLI:** Python, argparse, httpx, asyncio, Rich (Tables/Formatting), tqdm (Progress Bar)

## How it Works

The `check_domains.py` script contains the core logic:

1.  It takes a domain and first tries `HTTPS GET`, then `HTTP GET` (without following redirects).
2.  If a status code < 400 (Success or Redirect) is received, the domain is marked as **Online/Taken**.
3.  If HTTP checks fail, it attempts a direct TCP connection to the host on port 443, then port 80. Success marks it as **Online/Taken**.
4.  If TCP checks fail, it attempts DNS resolution. Success marks it as **Online/Taken** (with a note that only DNS resolved).
5.  If all checks fail, the domain is marked as **Offline/Available**, reporting the last known error.

The `app.py` provides a Flask web interface that calls the checking logic via `run_stream` (an async generator) and streams results back to the browser using a background thread and queue mechanism compatible with Flask/Uvicorn.



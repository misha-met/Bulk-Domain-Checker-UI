# Domain Status Checker

A simple web application to check the status (Online, Offline, Error) of a list of domains. It provides real-time updates in a table and a log panel, along with options to download the results.

## Features

*   **Bulk Domain Checking:** Enter multiple domains (separated by spaces or newlines) to check their status concurrently.
*   **Real-time Updates:** View results as they come in via streamed updates to a table and a detailed log panel.
*   **Status Details:** Shows whether a domain is Online, Offline, or encountered an Error during the check, along with specific details (e.g., HTTP status code, DNS error, connection error).
*   **Performance Metrics:** Displays total domains, checked count/percentage, online/failed counts/percentages, elapsed time, and check speed.
*   **Download Results:** Export the check results as CSV or TXT files.
*   **Responsive UI:** Built with Flask and vanilla JavaScript, using Tailwind CSS (via CDN) for styling and DataTables for the results table.

## Prerequisites

*   Python 3.x
*   pip (Python package installer)

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd <repository-directory>
    ```
2.  **Create and activate a virtual environment (recommended):**
    *   On macOS/Linux:
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```
    *   On Windows:
        ```bash
        python -m venv venv
        .\venv\Scripts\activate
        ```
3.  **Install the required Python packages:**
    ```bash
    pip install -r requirements.txt
    ```

## Running the Application

1.  **Start the Flask server:**
    ```bash
    python app.py
    ```
2.  **Access the application:**
    Open your web browser and navigate to `http://127.0.0.1:5000` (or the address provided in the terminal output).

## Usage

1.  Enter the domains you want to check into the text area. Each domain should be separated by a space or a newline.
2.  Click the "Check Domains" button.
3.  Observe the results appearing in the "Results" table and the "Logs" panel below.
4.  Once the checks are complete, use the "Download CSV" or "Download TXT" buttons to save the results.

## Technologies Used

*   **Backend:** Python, Flask
*   **Frontend:** HTML, CSS (Tailwind CSS via CDN), JavaScript
*   **Libraries:** DataTables.js



# Domain Responsiveness Checker

This Python script tests a list of domains via HTTP HEAD requests and reports which are responsive.

## Prerequisites
- Python 3.7 or newer
- pip (Python package installer)

## Installation
1. Clone or download this workspace.
2. Change into the project directory:
   ```bash
   cd "Quick test"
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
Prepare a text file (e.g. `domains.txt`) containing one domain per line, for example:
```
example.com
github.com
invalid.domain
```

Run the script:
```bash
python check_domains.py domains.txt [--timeout TIMEOUT] [--workers WORKERS] [--log-file LOGFILE]
```

Arguments:
- `file` (positional): Path to the domain list file.
- `--timeout`: Seconds to wait for each request (default: 5).
- `--workers`: Maximum number of concurrent requests (default: 100).
- `--log-file`: Path to write detailed results (default: `domain_check.log`).

## Output
- Console: summary of how many domains were responsive/unresponsive and their status codes or error messages.
- Log file: one line per domain with ✔ or ✖ and detail. See `--log-file`.

## Example
```bash
python check_domains.py domains.txt --timeout 10 --workers 50 --log-file results.log
```

Results will appear on stdout and in `results.log`.

## Web Interface

A modern responsive UI is available via Flask:

1. Ensure dependencies are installed:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the web server:
   ```bash
   python app.py
   ```
3. Open your browser at `http://localhost:5000`.
4. Paste or type domains into the textarea, then click _Check Domains_.
5. Toggle between light and dark mode using the button in the sidebar (or bottom-right on mobile).

## Log Panel Animation

When you initiate a domain check, a log panel appears below the controls and simulates real-time backend logs:

- Each domain being checked is appended line by line, creating a scrolling effect.
- After all checks are initiated, a final message is displayed.
- The log panel auto-scrolls to always show the latest entries.

This provides a more engaging loading experience while your domains are being processed.

## Security

**Important:** Do not commit sensitive information to your Git repository.

- **Domain Lists:** If your `domains.txt` file contains private or internal domain names, add it to your `.gitignore` file to prevent accidental commits.
- **Log Files:** The default log file (`domain_check.log`) or any custom log files might contain information you don't want public. Ensure log files are included in `.gitignore`.
- **Environment Variables:** If you extend this application to use API keys or other secrets, store them in environment variables or a `.env` file (and add `.env` to `.gitignore`), do not hardcode them in the source.

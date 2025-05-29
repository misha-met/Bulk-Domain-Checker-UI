# Accurate Domain Checker

A high-accuracy domain checking tool with caching, retry logic, and comprehensive filtering.

## Features

- **100% Accuracy Focus**: Controlled concurrency and comprehensive error handling
- **Smart Domain Filtering**: Automatically filters out infrastructure domains (mail, dns, ftp, etc.)
- **Persistent Caching**: Resume interrupted scans, retry failed domains up to 5 times
- **Redirect Tracking**: Complete redirect chain analysis with step-by-step tracking
- **Multiple Export Formats**: JSON and CSV output
- **Progress Tracking**: Rich terminal UI with progress bars

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage
```bash
# Check domains from text file
python accurate_domain_checker.py domains.txt

# Check domains from CSV file
python accurate_domain_checker.py domains.csv
```

### Advanced Options
```bash
python accurate_domain_checker.py domains.txt \
  --concurrency 10 \
  --timeout 15 \
  --export results.json \
  --export-csv results.csv \
  --cache custom_cache.json
```

### Parameters

- `domains.txt`: Input file with one domain per line
- `--concurrency`: Number of concurrent checks (default: 15)
- `--timeout`: Request timeout in seconds (default: 10)
- `--export`: JSON output file (default: domain_results.json)
- `--export-csv`: CSV output file (default: domain_results.csv)
- `--cache`: Cache file location (default: domain_cache.json)

## Input Format

### Text File Format
Create a text file with one domain per line:
```
example.com
google.com
stackoverflow.com
github.com
```

### CSV File Format
Create a CSV file with `domain` and `host` columns:
```csv
domain,host
google.com,www
google.com,mail
stackoverflow.com,www
github.com,api
example.com,test
```

The script will automatically combine the host and domain to create full domains like:
- `www.google.com`
- `mail.google.com`
- `www.stackoverflow.com`
- `api.github.com`
- `test.example.com`

**Note**: The CSV format is ideal when you have a list of base domains and want to check specific subdomains for each.

## Output

### JSON Output
Complete structured data including redirect chains, timestamps, and metadata.

### CSV Output
Simplified tabular format with columns:
- domain
- is_online
- http_status
- total_redirects
- final_url
- redirect_chain
- error_message
- check_count
- first_checked
- last_checked

## Domain Filtering

The tool automatically filters out infrastructure domains including:

- **Email & Messaging**: mail., smtp., pop., imap., webmail., mx., etc.
- **DNS & Domain Control**: ns1., ns2., dns., whois., etc.
- **File Transfer**: ftp., sftp., files., storage., etc.
- **Remote Access**: vpn., ssh., rdp., management., etc.
- **Databases**: db., mysql., postgres., redis., etc.
- **Monitoring**: monitor., metrics., logs., status., etc.
- **CI/CD**: ci., jenkins., git., build., etc.
- **APIs**: api., svc., rest., graphql., etc.
- **Communication**: sip., voip., meet., teams., etc.

## Caching System

- **Automatic Progress Saving**: Results cached after every 50 domains
- **Resume Capability**: Restart interrupted scans from where you left off
- **Retry Logic**: Offline domains rechecked up to 5 times
- **Smart Rechecking**: Online domains not rechecked (assumed stable)

## Status Code Handling

- **Redirect Domains**: Shows initial redirect status (301, 302) for easy filtering
- **Direct Response**: Shows actual response status (200, 404, etc.)
- **Online Detection**: Based on final destination accessibility (< 400)

## Examples

### Check domains with custom settings
```bash
python accurate_domain_checker.py my_domains.txt --concurrency 5 --timeout 20
```

### Use custom cache file
```bash
python accurate_domain_checker.py domains.txt --cache /path/to/my_cache.json
```

### Export to specific files
```bash
python accurate_domain_checker.py domains.txt \
  --export /results/detailed.json \
  --export-csv /results/summary.csv
```

## Testing

A demo file `cache_demo.txt` is included with sample domains to test the functionality:

```bash
python accurate_domain_checker.py cache_demo.txt
```

This will demonstrate:
- Domain filtering
- Redirect tracking
- Caching behavior
- Output formats

## Notes

- Designed for accuracy over speed (controlled concurrency)
- SSL verification disabled for broader compatibility
- HTTP/2 enabled for modern performance
- All progress automatically saved to prevent data loss

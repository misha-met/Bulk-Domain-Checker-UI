"""
Flask web application for bulk domain checking with caching support.

Provides a web interface and API endpoints for checking domain responsiveness,
with intelligent caching, real-time progress updates, and export functionality.
"""

from flask import Flask, render_template, request, jsonify, stream_with_context, Response
import json
from check_domains import run_stream
from database import cache
from asgiref.wsgi import WsgiToAsgi
import logging
import asyncio
import threading
from queue import Queue

# Initialize Flask application
app = Flask(__name__)
asgi_app = WsgiToAsgi(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('domain_check.log'),
        logging.StreamHandler()
    ]
)

@app.route('/')
def index():
    """Renders the main HTML page."""
    return render_template('index.html')


@app.route('/check', methods=['POST'])
def check_api():
    """
    Handles domain checking requests and streams results back to the client.
    
    Accepts JSON payload with:
    - domains: List of domains to check
    - timeout: Request timeout in seconds (default: 5)
    - workers: Number of concurrent workers (default: 100)
    - use_cache: Whether to use cached results (default: False)
    - add_to_cache: Whether to cache new results (default: False)
    
    Returns: Streaming JSON response with domain check results
    """
    try:
        # Extract request parameters
        data = request.get_json() or {}
        domains = data.get('domains', [])
        timeout = data.get('timeout', 5)
        workers = data.get('workers', 100)
        use_cache = data.get('use_cache', False)
        add_to_cache = data.get('add_to_cache', False)

        # Validate input
        if not domains:
            return jsonify({"error": "No domains provided"}), 400

        # Use thread-safe queue for producer-consumer communication
        q = Queue()

        def run_async_producer():
            """Runs the async domain checking stream in a dedicated thread."""
            async def producer():
                try:
                    # Separate domains into cached and non-cached
                    cached_results = {}
                    domains_to_check = []
                    
                    if use_cache:
                        for domain in domains:
                            cached_result = cache.get_cached_result(domain)
                            if cached_result:
                                cached_results[domain] = cached_result
                                logging.info(f"Using cached result for {domain}")
                            else:
                                domains_to_check.append(domain)
                    else:
                        domains_to_check = domains
                    
                    # Yield cached results first
                    for domain, cached_result in cached_results.items():
                        result = {
                            'domain': cached_result['domain'],
                            'ok': cached_result['ok'],
                            'detail': cached_result['detail'],
                            'redirect_count': cached_result['redirect_count'],
                            'redirect_history': cached_result['redirect_history'],
                            'from_cache': True
                        }
                        q.put(json.dumps(result) + '\n')
                    
                    # Check remaining domains
                    if domains_to_check:
                        async for d, ok, detail, redirect_history in run_stream(domains_to_check, timeout, workers):
                            redirect_count = len(redirect_history) - 1 if redirect_history else 0
                            
                            # Cache the result if requested
                            if add_to_cache:
                                cache.cache_result(d, ok, detail, redirect_history)
                            
                            result = {
                                'domain': d, 
                                'ok': ok, 
                                'detail': detail,
                                'redirect_count': redirect_count,
                                'redirect_history': redirect_history,
                                'from_cache': False
                            }
                            q.put(json.dumps(result) + '\n')
                except Exception as e:
                    logging.exception("Error during domain check stream")
                    q.put(json.dumps({"error": "Streaming failed", "detail": str(e)}) + '\n')
                finally:
                    q.put(None)

            # Set up asyncio event loop for this thread
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(producer())

        # Start producer in background thread
        producer_thread = threading.Thread(target=run_async_producer)
        producer_thread.start()

        def generate_sync_consumer():
            """Synchronous generator that consumes items from the queue."""
            while True:
                item = q.get()
                if item is None:
                    break
                yield item.encode('utf-8')
            producer_thread.join()

        return Response(stream_with_context(generate_sync_consumer()), mimetype='application/json')

    except Exception as e:
        logging.exception("Error in /check endpoint")
        return jsonify({"error": "Internal Server Error", "detail": str(e)}), 500


@app.route('/cache/stats', methods=['GET'])
def cache_stats():
    """Returns cache statistics."""
    try:
        stats = cache.get_cache_stats()
        return jsonify(stats)
    except Exception as e:
        logging.exception("Error getting cache stats")
        return jsonify({"error": "Failed to get cache stats", "detail": str(e)}), 500


@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    """Clears all cache entries."""
    try:
        deleted_count = cache.clear_cache()
        return jsonify({"message": f"Cleared {deleted_count} cache entries"})
    except Exception as e:
        logging.exception("Error clearing cache")
        return jsonify({"error": "Failed to clear cache", "detail": str(e)}), 500


@app.route('/export-cache', methods=['GET'])
def export_cache():
    """Exports the entire database cache to CSV format."""
    try:
        from io import StringIO
        import csv
        from datetime import datetime
        
        cache_data = cache.get_all_cached_results()
        
        if not cache_data:
            return jsonify({"error": "No cached data available for export"}), 404
        
        # Create CSV content
        output = StringIO()
        writer = csv.writer(output)
        
        # Write headers
        headers = [
            'Domain',
            'Status',
            'Detail',
            'Redirect_Count',
            'Final_Status_Code',
            'Redirect_Chain',
            'Created_At',
            'Updated_At'
        ]
        writer.writerow(headers)
        
        # Write data rows
        for record in cache_data:
            status = 'Online' if record['is_ok'] else 'Offline'
            redirect_chain = ''
            
            # Parse redirect history if available
            if record.get('redirect_history'):
                try:
                    import json
                    redirect_history = json.loads(record['redirect_history'])
                    if redirect_history and len(redirect_history) > 1:
                        redirect_chain = ' -> '.join([
                            f"{step.get('status_code', '?')}:{step.get('url', '')}"
                            for step in redirect_history
                        ])
                except (json.JSONDecodeError, TypeError):
                    redirect_chain = record.get('redirect_info', '')
            
            row = [
                record['domain'],
                status,
                record['detail'] or '',
                record.get('redirect_count', 0),
                record.get('final_status_code', ''),
                redirect_chain,
                record.get('created_at', ''),
                record.get('updated_at', '')
            ]
            writer.writerow(row)
        
        # Create response
        csv_content = output.getvalue()
        output.close()
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'domain_cache_export_{timestamp}.csv'
        
        response = Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename={filename}',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )
        
        logging.info(f"Exported {len(cache_data)} cache records to CSV")
        return response
        
    except Exception as e:
        logging.exception("Error exporting cache")
        return jsonify({"error": "Failed to export cache", "detail": str(e)}), 500


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:asgi_app", host="0.0.0.0", port=8000, reload=True)
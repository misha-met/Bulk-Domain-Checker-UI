# Import necessary libraries
from flask import Flask, render_template, request, jsonify, stream_with_context, Response
import json # For handling JSON data
from check_domains import run_stream # Import the async domain checking function
from database import cache # Import the cache system
from asgiref.wsgi import WsgiToAsgi # Adapter to run Flask (WSGI) with an ASGI server like Uvicorn
import logging # For logging application events and errors
import asyncio # For running the async domain checker
import threading # To run the async producer in a separate thread
from queue import Queue # Thread-safe queue for communication between producer and consumer

# Initialize the Flask application
app = Flask(__name__)
# Wrap the Flask WSGI app as an ASGI application to allow compatibility with ASGI servers (like Uvicorn)
# This is necessary for handling asynchronous operations efficiently within Flask.
asgi_app = WsgiToAsgi(app)

# Configure basic logging to output informational messages and errors
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('domain_check.log'),
        logging.StreamHandler()
    ]
)

# Define the route for the main page ('/')
@app.route('/')
def index():
    """Renders the main HTML page (index.html)."""
    return render_template('index.html')

# Define the API endpoint ('/check') for checking domains, accepting POST requests
@app.route('/check', methods=['POST'])
def check_api(): # This route remains synchronous from Flask's perspective
    """Handles the domain checking request, streams results back to the client."""
    try:
        # Get JSON data from the POST request
        data = request.get_json() or {}
        # Extract domains, timeout, worker count, and cache options from the request data
        domains = data.get('domains', [])
        timeout = data.get('timeout', 5) # Default timeout 5 seconds
        workers = data.get('workers', 100) # Default 100 concurrent workers
        use_cache = data.get('use_cache', False) # Whether to use cached results
        add_to_cache = data.get('add_to_cache', False) # Whether to cache new results

        # Validate input: Check if any domains were provided
        if not domains:
            return jsonify({"error": "No domains provided"}), 400 # Return 400 Bad Request if no domains

        # Use a standard thread-safe Queue for communication between the
        # asynchronous producer thread and the synchronous Flask consumer generator.
        q = Queue()

        # Define a function to run the asynchronous domain checking stream (producer)
        def run_async_producer():
            """Runs the async stream producer (check_domains.run_stream) in a dedicated thread."""
            # Define the actual async function that will produce results
            async def producer():
                try:
                    # Separate domains into cached and non-cached
                    cached_results = {}
                    domains_to_check = []
                    
                    if use_cache:
                        # Check cache for each domain
                        for domain in domains:
                            cached_result = cache.get_cached_result(domain)
                            if cached_result:
                                cached_results[domain] = cached_result
                                logging.info(f"Using cached result for {domain}")
                            else:
                                domains_to_check.append(domain)
                    else:
                        domains_to_check = domains
                    
                    # First, yield cached results
                    for domain, cached_result in cached_results.items():
                        result = {
                            'domain': cached_result['domain'],
                            'ok': cached_result['ok'],
                            'detail': cached_result['detail'],  # Remove (cached) suffix since Source column shows this
                            'redirect_count': cached_result['redirect_count'],
                            'redirect_history': cached_result['redirect_history'],
                            'from_cache': True
                        }
                        q.put(json.dumps(result) + '\n')
                    
                    # Then check remaining domains
                    if domains_to_check:
                        # Iterate through results yielded by the async domain checker
                        async for d, ok, detail, redirect_history in run_stream(domains_to_check, timeout, workers):
                            # Parse redirect count from redirect history
                            redirect_count = len(redirect_history) - 1 if redirect_history else 0
                            
                            # Cache the result if requested
                            if add_to_cache:
                                cache.cache_result(d, ok, detail, redirect_history)
                            
                            # Put the result with enhanced redirect information into the queue
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
                    # Log any exceptions that occur during the streaming process
                    logging.exception("Error during domain check stream")
                    # Put an error message into the queue
                    q.put(json.dumps({"error": "Streaming failed", "detail": str(e)}) + '\n')
                finally:
                    # Put a sentinel value (None) into the queue to signal that production is complete
                    q.put(None)

            # Ensure an asyncio event loop is available for this thread and run the producer coroutine
            try:
                # Get the existing event loop if one is running in this thread
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # If no event loop is running, create a new one and set it for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            # Run the producer coroutine until it completes within the event loop
            loop.run_until_complete(producer())

        # Start the producer function in a separate background thread
        producer_thread = threading.Thread(target=run_async_producer)
        producer_thread.start()

        # Define a synchronous generator function (consumer) to yield results for the Flask response
        def generate_sync_consumer():
            """Synchronous generator that consumes items from the queue and yields them."""
            while True:
                # Get an item from the queue (blocks if the queue is empty)
                item = q.get()
                # Check if the item is the sentinel value (None) indicating completion
                if item is None:
                    break # Exit the loop if the producer is done
                # Yield the item (already a JSON string with newline) encoded as bytes for the HTTP response
                yield item.encode('utf-8')
            # Wait for the producer thread to finish completely before ending the response stream
            producer_thread.join()

        # Return a Flask Response object that streams the output of the sync consumer generator.
        # stream_with_context ensures Flask's application and request contexts are available if needed.
        # The mimetype 'application/json' indicates the content type of the stream.
        return Response(stream_with_context(generate_sync_consumer()), mimetype='application/json')

    # Handle any unexpected exceptions in the main API endpoint function
    except Exception as e:
        logging.exception("Error in /check endpoint")
        # Return a 500 Internal Server Error response with details
        return jsonify({"error": "Internal Server Error", "detail": str(e)}), 500

# API endpoint for cache statistics
@app.route('/cache/stats', methods=['GET'])
def cache_stats():
    """Returns cache statistics."""
    try:
        stats = cache.get_cache_stats()
        return jsonify(stats)
    except Exception as e:
        logging.exception("Error getting cache stats")
        return jsonify({"error": "Failed to get cache stats", "detail": str(e)}), 500

# API endpoint for cache management
@app.route('/cache/clear', methods=['POST'])
def clear_cache():
    """Clears all cache entries."""
    try:
        deleted_count = cache.clear_cache()
        return jsonify({"message": f"Cleared {deleted_count} cache entries"})
    except Exception as e:
        logging.exception("Error clearing cache")
        return jsonify({"error": "Failed to clear cache", "detail": str(e)}), 500

# Entry point for running the script directly
if __name__ == "__main__":
    # Import Uvicorn, an ASGI server
    import uvicorn
    # Run the application using Uvicorn.
    # "app:asgi_app" tells Uvicorn to load the 'asgi_app' object from the 'app.py' module.
    # host="0.0.0.0" makes the server accessible on the network.
    # port=8000 specifies the port number.
    # reload=True enables auto-reloading when code changes (useful for development).
    uvicorn.run("app:asgi_app", host="0.0.0.0", port=8000, reload=True)
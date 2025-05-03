# Import necessary libraries
from flask import Flask, render_template, request, jsonify, stream_with_context, Response
import json # For handling JSON data
from check_domains import run_stream # Import the async domain checking function
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
logging.basicConfig(level=logging.INFO)

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
        # Extract domains, timeout, and worker count from the request data, providing defaults
        domains = data.get('domains', [])
        timeout = data.get('timeout', 5) # Default timeout 5 seconds
        workers = data.get('workers', 100) # Default 100 concurrent workers

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
                    # Iterate through results yielded by the async domain checker
                    async for d, ok, detail in run_stream(domains, timeout, workers):
                        # Put the result (as a JSON string with newline) into the thread-safe queue
                        q.put(json.dumps({'domain': d, 'ok': ok, 'detail': detail}) + '\n')
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
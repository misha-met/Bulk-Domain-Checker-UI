from flask import Flask, render_template, request, jsonify, stream_with_context, Response
import json
from check_domains import run_stream
from asgiref.wsgi import WsgiToAsgi
import logging
import asyncio
import threading
from queue import Queue

app = Flask(__name__)
# Wrap the Flask WSGI app as an ASGI application
asgi_app = WsgiToAsgi(app)

# Configure basic logging
logging.basicConfig(level=logging.INFO)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check', methods=['POST'])
def check_api(): # Make the route synchronous
    try:
        data = request.get_json() or {}
        domains = data.get('domains', [])
        timeout = data.get('timeout', 5)
        workers = data.get('workers', 100)

        if not domains:
            return jsonify({"error": "No domains provided"}), 400

        q = Queue() # Use standard Queue for thread-safe communication

        def run_async_producer():
            """Runs the async stream producer in the asyncio event loop."""
            async def producer():
                try:
                    async for d, ok, detail in run_stream(domains, timeout, workers):
                        # Put JSON string into the queue
                        q.put(json.dumps({'domain': d, 'ok': ok, 'detail': detail}) + '\n')
                except Exception as e:
                    logging.exception("Error during domain check stream")
                    # Put error JSON into the queue
                    q.put(json.dumps({"error": "Streaming failed", "detail": str(e)}) + '\n')
                finally:
                    q.put(None) # Sentinel value to signal completion

            # Ensure an event loop exists for this thread and run the producer
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(producer())

        # Start the producer in a separate thread
        producer_thread = threading.Thread(target=run_async_producer)
        producer_thread.start()

        def generate_sync_consumer():
            """Synchronous generator that consumes from the queue."""
            while True:
                item = q.get() # Blocks until item is available
                if item is None: # Check for sentinel
                    break
                yield item.encode('utf-8') # Yield bytes for the Response
            producer_thread.join() # Ensure producer thread finishes before response ends

        # Use Flask's streaming with the synchronous generator
        # stream_with_context ensures context (like request) is available if needed
        return Response(stream_with_context(generate_sync_consumer()), mimetype='application/json')

    except Exception as e:
        logging.exception("Error in /check endpoint")
        return jsonify({"error": "Internal Server Error", "detail": str(e)}), 500

if __name__ == "__main__":
    # Run with Uvicorn ASGI server for async streaming support via WsgiToAsgi
    import uvicorn
    uvicorn.run("app:asgi_app", host="0.0.0.0", port=8000, reload=True) # Corrected asgi_app name
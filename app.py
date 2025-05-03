from flask import Flask, render_template, request, jsonify, stream_with_context, Response
import asyncio
import json
from aiohttp import ClientSession, ClientTimeout  # needed for streaming checks
from check_domains import run, check

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check', methods=['POST'])
def check_api():
    data = request.get_json() or {}
    domains = data.get('domains', [])
    timeout = data.get('timeout', 5)
    workers = data.get('workers', 100)

    def generate():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        timeout_cfg = ClientTimeout(total=timeout)
        # create aiohttp session inside the event loop to avoid no running loop error
        async def _make_session():
            sess = ClientSession(timeout=timeout_cfg)
            await sess.__aenter__()
            return sess
        session = loop.run_until_complete(_make_session())
        sem = asyncio.Semaphore(workers)

        async def bound_check(d):
            async with sem:
                ok, detail = await check(d, session, timeout_cfg)
                return d, ok, detail

        # schedule all domain checks
        tasks = [bound_check(d) for d in domains]
        # stream results as they complete
        for coro in asyncio.as_completed(tasks):
            d, ok, detail = loop.run_until_complete(coro)
            yield json.dumps({'domain': d, 'ok': ok, 'detail': detail}) + '\n'

        # close aiohttp session properly
        loop.run_until_complete(session.__aexit__(None, None, None))
        loop.close()

    return Response(stream_with_context(generate()), mimetype='application/json')

if __name__ == "__main__":
    # Start the Flask development server
    app.run(host='0.0.0.0', port=8000, debug=True)
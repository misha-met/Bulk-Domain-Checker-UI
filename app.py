from flask import Flask, render_template, request, jsonify
import asyncio
from check_domains import run

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
    # perform domain checks
    results = asyncio.run(run(domains, timeout, workers))
    output = [{'domain': d, 'ok': ok, 'detail': detail} for d, ok, detail in results]
    return jsonify(output)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
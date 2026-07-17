import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify
from flask_cors import CORS
from assembler import assemble
from simulator import Simulator

app = Flask(__name__)
CORS(app)

# Global simulator instance — one session at a time
sim = None


@app.route('/assemble', methods=['POST'])
def assemble_route():
    global sim
    data = request.get_json()
    source = data.get('source', '')

    try:
        memory, symbols, decoded = assemble(source)
        sim = Simulator(source)
        return jsonify({
            'success': True,
            'decoded': decoded,
            'symbols': symbols,
            'memory': {str(k): v for k, v in memory.items()},
            'state': sim.get_state()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/step', methods=['POST'])
def step_route():
    global sim
    if sim is None:
        return jsonify({'success': False, 'error': 'No program loaded'}), 400

    advanced = sim.step()
    return jsonify({
        'success': True,
        'advanced': advanced,
        'state': sim.get_state()
    })


@app.route('/reset', methods=['POST'])
def reset_route():
    global sim
    if sim is None:
        return jsonify({'success': False, 'error': 'No program loaded'}), 400

    data = request.get_json()
    source = data.get('source', '')
    try:
        sim = Simulator(source)
        return jsonify({'success': True, 'state': sim.get_state()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/run', methods=['POST'])
def run_route():
    global sim
    if sim is None:
        return jsonify({'success': False, 'error': 'No program loaded'}), 400

    sim.run_all()
    return jsonify({
        'success': True,
        'state': sim.get_state()
    })


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(debug=True, port=5001)

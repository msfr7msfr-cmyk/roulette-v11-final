from flask import Flask, request, jsonify
from bot import predict

app = Flask(__name__)

@app.route('/')
def home():
    return "V21 OK - 15 + GAP + REPEATER"

@app.route('/predict', methods=['POST'])
def do_predict():
    data = request.get_json()
    history = data.get('history', []) if data else []
    result = predict(history)
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

from flask import Flask, request
import os
import bot

app = Flask(__name__)

@app.route('/')
def home():
    return "V21 Bot is Live"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data:
        bot.handle_update(data)
    return "ok", 200

if __name__ == "__main__":
    app.run()

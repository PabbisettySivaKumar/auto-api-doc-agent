from flask import Flask
app = Flask(__name__)

@app.route("/items", methods=["POST"])
def create_item(name, price):
    return name

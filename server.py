import os
from flask import Flask, redirect, url_for, request
app = Flask(__name__)

SEARCH_ROOT = "C:\\Users\\Boris\\Documents"


@app.route('/')
def hello_world():
    return 'Hello World'


@app.route('/projects', methods=['GET'])
def projects():
    result = []
    for root, dirs, files in os.walk(SEARCH_ROOT):
        if "atomic.scribbler" in files:
            proj_path = os.path.join(SEARCH_ROOT, root)
            result.append(proj_path)
    return result
 

if __name__ == '__main__':
    app.run(debug=True)

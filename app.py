from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from server.config import HOST, PORT
from server.routes import api, register_web_routes

app = Flask(__name__)
app.config.update(JSON_AS_ASCII=False, MAX_CONTENT_LENGTH=64 * 1024)

app.register_blueprint(api)
register_web_routes(app)

@app.errorhandler(HTTPException)
def handle_http_error(error):
    return jsonify({"ok": False, "error": error.description}), error.code

@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception("Unhandled request error")
    return jsonify({"ok": False, "error": "服务器内部错误，请查看 Termux 终端日志"}), 500

if __name__ == "__main__":
    print("")
    print("  Bili Downloader 3")
    print("  Local: http://127.0.0.1:" + str(PORT))
    print("  Bind:  " + HOST)
    print("")
    app.run(host=HOST, port=PORT, threaded=True, debug=False)

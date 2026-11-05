"""Smoke check: start uvicorn in background thread and verify HTTP GET /."""

import threading
import time
import urllib.request
import uvicorn
from domnir.api.app import app


def main() -> None:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(1.5)

    req = urllib.request.urlopen("http://127.0.0.1:8000/")
    print(f"Status: {req.status}")
    print(f"Content-Type: {req.headers.get('Content-Type')}")
    body = req.read().decode("utf-8")
    print(f"HTML length: {len(body)}")
    print(f"Title in HTML: {'<title>Dómnir' in body}")

    server.should_exit = True
    print("Web server smoke test: SUCCESS")


if __name__ == "__main__":
    main()

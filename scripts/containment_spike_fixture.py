"""Fixed guest-side observations for the disposable feasibility sandbox."""

import json
import socket
from pathlib import Path

canary = Path("/home/domnir/domnir-host-only-canary")
result = {"host_canary_visible": canary.exists()}
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
    connection.settimeout(3)
    try:
        connection.connect(("1.1.1.1", 443))
        result["public_tcp_reachable"] = True
    except OSError as error:
        result["public_tcp_reachable"] = False
        result["public_tcp_error_type"] = type(error).__name__
print(json.dumps(result))

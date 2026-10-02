import http.server
import socket
import threading

import pytest

from syssentry import config
from syssentry.checks import check_http, check_process, check_tcp, run_check


@pytest.fixture
def http_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            code = 200 if self.path == "/health" else 503
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_tcp_up_and_down(http_server):
    port = int(http_server.rsplit(":", 1)[1])
    assert check_tcp("127.0.0.1", port, 1)[0]
    assert not check_tcp("127.0.0.1", free_port(), 1)[0]


def test_http_status_and_body(http_server):
    assert check_http(f"{http_server}/health", 2, 200, "healthy")[0]
    ok, detail = check_http(f"{http_server}/broken", 2)
    assert not ok and "503" in detail
    assert not check_http(f"{http_server}/health", 2, 200, "nope")[0]
    assert not check_http(f"http://127.0.0.1:{free_port()}/", 1)[0]


def test_process_check():
    assert check_process("python")[0]
    assert not check_process("definitely-not-running-xyz")[0]


def test_run_check_records_latency(http_server):
    res = run_check({"name": "api", "type": "http", "url": f"{http_server}/health"})
    assert res.ok and res.latency_ms >= 0


def test_config_defaults_and_merge(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("interval_seconds: 10\nalerts:\n  cooldown_seconds: 60\n")
    cfg = config.load(path)
    assert cfg["interval_seconds"] == 10
    assert cfg["alerts"]["cooldown_seconds"] == 60
    assert cfg["alerts"]["channels"] == [{"type": "console"}]


@pytest.mark.parametrize("body", [
    "interval_seconds: 0",
    "thresholds:\n  - {metric: cpu_percent, warn: 90, crit: 80}",
    "services:\n  - {name: a, type: ftp}",
    "services:\n  - {name: a, type: tcp, port: 1}\n  - {name: a, type: tcp, port: 2}",
])
def test_invalid_configs_rejected(tmp_path, body):
    path = tmp_path / "c.yaml"
    path.write_text(body)
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_example_config_is_valid():
    from pathlib import Path

    cfg = config.load(Path(__file__).resolve().parents[1] / "config.example.yaml")
    assert cfg["services"]

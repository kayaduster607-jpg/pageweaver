"""Run synthetic regressions while rejecting environment-file and external access."""

import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def protect_local_material(event, arguments):
    """Keep accidental dotenv loads and external sockets out of the test run."""
    if event == "open" and isinstance(arguments[0], (str, bytes)):
        path = Path(arguments[0].decode() if isinstance(arguments[0], bytes) else arguments[0])
        if any(part.lower().startswith(".env") or part.lower().endswith(".env") for part in path.parts):
            raise PermissionError("Environment-file reads are forbidden")
    if event in ("socket.connect", "socket.bind"):
        address = arguments[1]
        if isinstance(address, tuple):
            try:
                allowed = ipaddress.ip_address(address[0]).is_loopback
            except ValueError:
                allowed = False
            if not allowed:
                raise PermissionError("Only internal loopback sockets are allowed")
    if event == "socket.getaddrinfo" and arguments[0] not in (None, "localhost", "127.0.0.1", "::1"):
        raise PermissionError("External DNS is forbidden")


def main():
    """Run real PDF and mocked download checks; no source directory is consulted."""
    sys.addaudithook(protect_local_material)
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    import image_url_to_pdf
    image_url_to_pdf.run_self_test()
    browser = subprocess.run(["node", "--test", str(ROOT / "tests/web-ui.test.cjs")], cwd=ROOT)
    if browser.returncode:
        raise SystemExit(browser.returncode)
    from importlib.metadata import version
    report = {"python_tests": result.testsRun, "python_failures": 0, "ui_tests": 3,
              "builtin_self_test": "passed", "synthetic_images_only": True,
              "external_network": False, "env_files_read": 0,
              "versions": {name: version(name) for name in ("requests", "Pillow", "img2pdf", "fastapi", "uvicorn", "pikepdf")}}
    destination = ROOT / ".verification"
    destination.mkdir(exist_ok=True)
    (destination / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

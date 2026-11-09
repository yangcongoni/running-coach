"""Machine-specific settings, stored beside the server outside version control."""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = ROOT / "archive.local.json"

def settings():
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}

def origin(setting, default):
    value = settings().get(setting, default).rstrip("/")
    url = urlsplit(value)
    if (not url.hostname or url.username is not None or url.password is not None
            or url.path or url.query or url.fragment or url.port == 0
            or not (url.scheme == "https" or
                    url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"})):
        raise ValueError("Invalid origin in " + setting)
    return value

def desktop_template():
    personal = ROOT / "index.html"
    if personal.is_file():
        return personal.read_text(encoding="utf-8")
    page = (ROOT / "archive.html").read_text(encoding="utf-8")
    for name, filename in (("run-period", "run_period.js"),
                           ("run-period-style", "run_period.css"),
                           ("footprint-shared", "footprint.js")):
        page = page.replace("/* include:" + name + " */", (ROOT / filename).read_text(encoding="utf-8"))
    return page

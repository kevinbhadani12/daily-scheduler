"""Runs the dashboard's own JavaScript (in Node) to make sure the config.yaml it saves
is read back exactly the same by the Python scheduler. Skipped if Node or internet is missing."""
import base64
import hashlib
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

import pytest

from scheduler.config import ROOT, load_config

DASHBOARD = ROOT / "docs" / "dashboard.html"

NODE_SCRIPT = r"""
const fs = require("fs"), vm = require("vm");
const [dash, yamlLib, cfgPath, editsJson, outPath] = process.argv.slice(1);
const html = fs.readFileSync(dash, "utf8");
const script = html.split('<script>\n"use strict";')[1].split("// ── rendering")[0];
const ctx = { console, Intl, Date, JSON, String, Object, structuredClone, TextEncoder, TextDecoder, btoa, atob, Uint8Array };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(yamlLib, "utf8"), ctx);
vm.runInContext(script + "\nthis.normalize = normalize; this.toYaml = toYaml;", ctx);
const cfg = ctx.normalize(ctx.jsyaml.load(fs.readFileSync(cfgPath, "utf8")));
const edits = JSON.parse(editsJson);
Object.assign(cfg, edits.top);
cfg.briefings.push(...edits.add);
fs.writeFileSync(outPath, ctx.toYaml(cfg));
"""


def _script_src(html: str) -> tuple[str, str]:
    match = re.search(r'<script src="([^"]+)"\s+integrity="([^"]+)"', html)
    assert match, "dashboard should load js-yaml with an integrity hash"
    return match.group(1), match.group(2)


@pytest.fixture(scope="module")
def js_yaml(tmp_path_factory):
    url, integrity = _script_src(DASHBOARD.read_text())
    try:
        data = urllib.request.urlopen(url, timeout=20).read()
    except OSError:
        pytest.skip("no internet to download js-yaml")
    digest = "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode()
    assert digest == integrity, "integrity hash in dashboard.html doesn't match the CDN file"
    path = tmp_path_factory.mktemp("js") / "js-yaml.min.js"
    path.write_bytes(data)
    return path


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_dashboard_saves_config_python_can_read(js_yaml, tmp_path, monkeypatch):
    original = load_config()
    edits = {
        "top": {"country": "NO"},   # 'NO' must not turn into False
        "add": [{"id": "ai-news", "name": 'AI & "Tech": daily', "prompt_file": "briefings/business.md",
                 "time": "20:00", "days": ["mon", "wed"], "deliver": ["email"], "enabled": True,
                 "model": "gemini-4-argon", "effort": "low"}],
    }
    out = tmp_path / "config.yaml"
    subprocess.run(["node", "-e", NODE_SCRIPT, str(DASHBOARD), str(js_yaml), str(ROOT / "config.yaml"),
                    json.dumps(edits), str(out)], check=True)

    saved = load_config(out)
    assert saved.country == "NO"
    assert saved.timezone == original.timezone
    for before, after in zip(original.briefings, saved.briefings):
        assert (before.id, before.name, before.time, before.days, before.deliver, before.enabled,
                before.model, before.effort) == \
               (after.id, after.name, after.time, after.days, after.deliver, after.enabled, after.model, after.effort)
    new = saved.get("ai-news")
    assert (new.name, new.days, new.deliver, new.model, new.effort) == \
           ('AI & "Tech": daily', ["mon", "wed"], ["email"], "gemini-4-argon", "low")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_dashboard_script_has_no_syntax_errors():
    html = DASHBOARD.read_text()
    script = html.split("<script>\n", 1)[1].split("</script>", 1)[0]
    subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"],
                   input=script, text=True, check=True)


def test_dashboard_knows_every_model_and_effort_used_in_config():
    html = DASHBOARD.read_text()
    settings = load_config()
    for b in settings.briefings:
        assert f'"{b.model}"' in html, f"add {b.model} to MODELS in dashboard.html"
        assert f'"{b.effort}"' in html, f"add {b.effort} to EFFORTS in dashboard.html"

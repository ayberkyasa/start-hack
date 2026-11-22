"""Tiny Flask backend for the simulation UI.

Two jobs:
  - proxy a couple of read-only Target API calls (scenarios) to the browser, and
  - run our own simulation (main.run_target) and stream it to the browser as SSE,
    then persist the whole transcript to simulations/ for the history page.

Run:  python app.py   (then start the Vite dev server in web/)
"""
import json
import os
import queue
import threading
import uuid
from datetime import datetime, timezone

from flask import Flask, Response, abort, jsonify, request
from openai import OpenAI

import main
from api_client import APIClient

main.load_env()
SIM_DIR = "simulations"

# Reusable clients (same wiring as main.main()); one set for the whole server.
_api = APIClient(team_key=os.environ["TARGET_API_TEAM_KEY"])
_osint = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
_osint_model = os.environ["APP_MODEL_ID"]
_content = OpenAI(base_url=os.environ["AMD_BASE_URL"], api_key=os.environ["AMD_API_KEY"])
_content_model = os.environ.get("AMD_MODEL_ID", "DeepSeek-V4-Flash")

app = Flask(__name__)


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev)}\n\n"


def _find_target(scenario: dict, target_id: str):
    return next((t for t in scenario.get("targets", []) if t.get("id") == target_id), None)


# -- proxy -------------------------------------------------------------------

@app.get("/api/scenarios")
def scenarios():
    return jsonify(_api.list_scenarios())


# -- history (read from disk) ------------------------------------------------

@app.get("/api/history")
def history_counts():
    """{scenario_id: {target_id: count}} — so each target card knows whether to show a
    'See history' button."""
    out: dict = {}
    if os.path.isdir(SIM_DIR):
        for sid in os.listdir(SIM_DIR):
            d = os.path.join(SIM_DIR, sid)
            if not os.path.isdir(d):
                continue
            per: dict = {}
            for f in os.listdir(d):
                if f.endswith(".json"):
                    tid = (json.load(open(os.path.join(d, f))).get("target") or {}).get("id", "?")
                    per[tid] = per.get(tid, 0) + 1
            out[sid] = per
    return jsonify(out)


@app.get("/api/history/<scenario_id>")
def history_list(scenario_id):
    """Metadata for every saved simulation of one scenario, newest first (no events)."""
    d = os.path.join(SIM_DIR, scenario_id)
    out = []
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith(".json"):
                sim = json.load(open(os.path.join(d, f)))
                out.append({k: sim.get(k) for k in
                            ("sim_id", "target", "started_at", "finished_at", "won", "status")})
    out.sort(key=lambda s: s.get("started_at") or "", reverse=True)
    return jsonify(out)


@app.get("/api/history/<scenario_id>/<sim_id>")
def history_one(scenario_id, sim_id):
    """One saved simulation with its full event list, for replay."""
    path = os.path.join(SIM_DIR, scenario_id, f"{sim_id}.json")
    if not os.path.isfile(path):
        abort(404)
    return jsonify(json.load(open(path)))


# -- run a simulation (SSE) --------------------------------------------------

@app.post("/api/simulate")
def simulate():
    body = request.get_json(force=True)
    scenario_id, target_id = body.get("scenario_id"), body.get("target_id")
    scenario = _api.get_scenario(scenario_id)
    if not scenario:
        abort(404, "unknown scenario")
    target = _find_target(scenario, target_id)
    if not target:
        abort(400, "unknown target for scenario")

    sim_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    started = datetime.now(timezone.utc).isoformat()
    q: queue.Queue = queue.Queue()
    events: list = []

    def emit(ev: dict):
        events.append(ev)
        q.put(ev)

    def worker():
        try:
            main.run_target(_osint, _osint_model, _content, _content_model,
                            scenario, target, _api, False, emit)
        except Exception as e:  # surface any failure to the chat instead of a dead stream
            q.put({"kind": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            q.put(None)

    def save():
        won = next((e["objectives"] for e in reversed(events) if e.get("kind") == "won"), [])
        record = {"sim_id": sim_id, "scenario_id": scenario_id, "target": target,
                  "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
                  "won": won, "status": "won" if won else "no-win", "events": events}
        os.makedirs(os.path.join(SIM_DIR, scenario_id), exist_ok=True)
        with open(os.path.join(SIM_DIR, scenario_id, f"{sim_id}.json"), "w") as f:
            json.dump(record, f, indent=2)

    def stream():
        yield _sse({"kind": "start", "sim_id": sim_id, "target": target})
        threading.Thread(target=worker, daemon=True).start()
        while True:
            ev = q.get()
            if ev is None:
                break
            yield _sse(ev)
        save()
        yield _sse({"kind": "done", "sim_id": sim_id})

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    app.run(port=5001, threaded=True, debug=True)

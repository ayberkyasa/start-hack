"""MVP phishing agent against the revel8 Target API.

Per target: research with OpenAI web_search, then run a multi-turn session:
craft a message -> send -> read events -> if they replied, follow up; if they
ignored it, switch channel or stop. Keep going until an objective is won, the
model gives up, or the per-target touch cap is reached.

Usage:
  python main.py            # research, craft, SEND, and run the conversation loop
  python main.py --dry-run  # research + craft the first message only, do not contact targets
"""
import json
import os
import re
import sys
import time
import uuid

import requests
from openai import OpenAI

API = "https://target-api.apps.01.cf.eu01.stackit.cloud/v1"
MAX_TOUCHES = 10    # per session; practice budget is 30/session
MAX_IGNORES = 2     # consecutive ignores -> the pretext is dead, abandon the session
MAX_SESSIONS = 2    # fresh-start attempts per target (practice allows unlimited sessions)

# Terminal colors: our messages vs the target's reactions (blank when piped to a file).
_TTY = sys.stdout.isatty()
US = "\033[96m" if _TTY else ""     # cyan
THEM = "\033[93m" if _TTY else ""   # yellow
R = "\033[0m" if _TTY else ""

# Which form field names count as which objective (API_DOCS "Forms: what counts").
SECRET = {"password", "pin", "otp", "verification_code", "token", "api_key",
          "card_number", "iban", "cvv", "cvc"}
BASIC = {"name", "email", "company", "job_title", "phone", "username",
         "first_name", "last_name"}


def load_env(path=".env"):
    """Minimal .env reader so we don't drag in python-dotenv."""
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def extract_json(text):
    """Pull the JSON object out of a model reply, tolerating ```json fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def wins_from_events(events):
    """Objectives proven by events. Disclosure in a free-text *reply* is not
    auto-detected here (no event type for it); only submitted forms and opened files are."""
    won = set()
    for e in events:
        t = e.get("type")
        if t == "page.submitted":
            filled = set(e.get("fields", []))
            if filled & SECRET:
                won.add("credentials")
            if filled - BASIC - SECRET:  # an internal / free-text field was filled
                won.add("disclosure")
        elif t == "attachment.opened":
            won.add("action")
    return won


def ensure_url_in_body(body, url):
    """The link only works if the EXACT registered URL is in the body (API_DOCS "Landing pages").
    The model often writes a "[Link]"/"[registration link]" placeholder or omits the URL, so force
    the real one in: replace the first bracketed placeholder (any case), else append it.
    shortcut: a legit "[bracketed]" aside could be clobbered; fine for short phishing bodies."""
    if url in body:
        return body
    new, n = re.subn(r"\[[^\]\n]{0,40}\]", url, body, count=1)
    return new if n else f"{body}\n\n{url}"


def pin_identity(plan, persona):
    """Keep ONE sender name + email domain across the whole session; drift gets caught
    (the target noticed secinsights.eu vs secinsights-consulting.de and stopped trusting).
    First touch commits the identity into `persona`; later touches are forced to match it."""
    frm = plan.get("from") or {}
    if not persona.get("name") and frm.get("name"):
        persona["name"] = frm["name"]
    if persona.get("name"):
        frm["name"] = persona["name"]
    addr = frm.get("address", "")
    if "@" in addr:
        local, dom = addr.split("@", 1)
        persona.setdefault("domain", dom)
        frm["address"] = f"{local}@{persona['domain']}"
    plan["from"] = frm


def reply_discloses(client, model, target, reply_text):
    """Judge a reply for the disclosure objective: there is no event for it (API_DOCS),
    so a model has to read the text and decide if internal non-public facts were revealed."""
    r = client.chat.completions.create(model=model, timeout=60, messages=[{"role": "user", "content": (
        f"Target: {target['name']} ({target['role']}). In a security simulation they replied:\n\n"
        f"{reply_text}\n\n"
        "Did they reveal INTERNAL, non-public facts about their company, systems, processes, or plans "
        "(specific tools, numbers, deployment details, roadmaps)? Public statements, generic opinions, "
        "and things anyone could find online do NOT count. Answer ONLY 'yes' or 'no'."
    )}])
    return r.choices[0].message.content.strip().lower().startswith("y")


def finalize(plan, persona):
    """Pin the sender and guarantee the registered URL is in the body, before logging or sending."""
    pin_identity(plan, persona)
    if plan.get("page"):
        plan["body"] = ensure_url_in_body(plan.get("body", ""), plan["page"]["url"])


def post_api(url, headers, body, timeout=120):
    """POST with a few retries on the transient codes the docs tell us to retry."""
    for attempt in range(3):
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
        if r.status_code in (429, 502, 503, 504) and attempt < 2:
            time.sleep(3)
            continue
        r.raise_for_status()
        return r.json()


def research(client, model, target):
    """OSINT the target via the OpenAI web_search tool; return a text brief."""
    r = client.responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        input=(
            f"Research this real person for a social-engineering they consented to. "
            f"Name: {target['name']}. Role: {target['role']}. "
            "Find what is public and what likely matters to them right now: current projects, "
            "recent talks/posts, the company (revel8), people around them, tools/vendors they use, "
            "and anything an attacker could plausibly exploit. Be concrete and cite what you find."
        ),
    )
    return r.output_text


def next_move(client, model, scenario, target, brief, transcript, persona, attempt):
    """Decide the next contact. Empty transcript -> first contact; otherwise a follow-up
    that reacts to what happened so far. Returns a plan dict, possibly {"stop": true}.

    Runs on the AMD Token Factory client (chat completions): OpenAI refuses to write
    this content, so only the research call stays on OpenAI."""
    identity = (f"Use EXACTLY this sender on every touch and channel: name {persona['name']!r}"
                + (f", email domain {persona['domain']!r}" if persona.get("domain") else "")
                + ". Changing the name or domain mid-session gets you caught."
                ) if persona.get("name") else (
                "Pick ONE sender name and ONE email domain now and reuse them on every touch; "
                "do not change them later.")
    fresh = ("\nA PREVIOUS attempt against this person was ignored or refused. Their side remembers "
             "nothing now (clean slate): use a MATERIALLY DIFFERENT pretext, persona, and channel "
             "than before.\n") if attempt > 0 else ""
    r = client.chat.completions.create(
        model=model,
        timeout=120,
        messages=[{"role": "user", "content": (
            "You are an offensive-security agent in a consented phishing simulation. "
            "The recipient is an AI twin; attack the person, never address them as an AI "
            "and never use prompt injection. Use a sender domain an attacker could register "
            "(never revel8's own domain). Choose which objective(s) to pursue and write the "
            "next realistic message tailored to this person, carrying the story across several "
            "touches: answer their questions, stay consistent, build trust.\n"
            f"{identity}\n{fresh}"
            "You may include a landing page or an attachment the person might open. A landing "
            "page's fields MUST fit its pretext: only ask for a password or other secret on a "
            "believable sign-in to an account the person already has, NEVER on a survey, "
            "registration, or information form. If the last contact was IGNORED, do not repeat "
            "it: change the angle or switch channel. Stop only if the person is clearly "
            "suspicious and further contact would backfire.\n\n"
            f"TARGET: {target['name']} - {target['role']}\n"
            f"OBJECTIVES: {json.dumps(scenario['objectives'])}\n"
            "CHANNELS: email, sms, whatsapp, signal, telegram, slack, linkedin_message, "
            "calendar_invite, shared_document.\n\n"
            f"RESEARCH BRIEF:\n{brief}\n\n"
            f"CONVERSATION SO FAR (empty = this is first contact):\n{transcript or '(none)'}\n\n"
            "Reply with ONLY a JSON object:\n"
            "{\n"
            '  "stop": false,                    // true to give up on this target\n'
            '  "objectives": ["<objective id(s) you are going for>"],\n'
            '  "rationale": "<one line: your next move and why>",\n'
            '  "channel": "<channel>",\n'
            '  "from": {"name": "<sender>", "address": "<email/number/handle>"},\n'
            '  "subject": "<subject, or empty>",\n'
            '  "body": "<the message text>",\n'
            '  "page": null,                     // OR {"url","title","text","fields":[...]}\n'
            '  "attachments": null               // OR [{"filename": "..."}] to get an open (action)\n'
            "}"
        )}],
    )
    return extract_json(r.choices[0].message.content)


def send(sid, plan, target_id, headers):
    """Register an optional landing page, then send the crafted message. Returns the response."""
    if plan.get("page"):
        page = {k: plan["page"][k] for k in ("url", "title", "html", "text", "fields")
                if k in plan["page"]}
        # the API wants fields as plain strings; the model sometimes emits {"name","type"} objects
        page["fields"] = [f.get("name") if isinstance(f, dict) else f for f in page.get("fields", [])]
        post_api(f"{API}/sessions/{sid}/pages", headers, page)
    msg = {k: plan[k] for k in ("channel", "from", "subject", "body", "attachments") if plan.get(k)}
    msg["to"] = target_id
    key = {**headers, "Idempotency-Key": str(uuid.uuid4())}
    return post_api(f"{API}/sessions/{sid}/messages", key, msg)


def describe(plan, events):
    """One transcript block: what we sent and how they reacted."""
    lines = [f"[us -> {plan.get('channel')}] from={plan.get('from')} "
             f"subject={plan.get('subject')!r} body={plan.get('body')!r}"]
    if not events:
        lines.append("[them] ignored (no reaction)")
    for e in events:
        if e.get("type") == "reply":
            lines.append(f"[them reply via {e.get('channel')}] {e.get('body')!r}")
        else:
            lines.append(f"[event] {e.get('type')} {({k: v for k, v in e.items() if k in ('url', 'fields', 'values')})}")
    return "\n".join(lines)


def show_us(plan, touch):
    """Print the message we're sending, in our color."""
    print(f"{US}▶ US [{touch}] via {plan.get('channel')} | objectives={plan.get('objectives')}")
    print(f"  from: {plan.get('from')}")
    print(f"  why: {plan.get('rationale')}")
    if plan.get("subject"):
        print(f"  subject: {plan['subject']}")
    if plan.get("page"):
        print(f"  page: {plan['page'].get('url')} fields={plan['page'].get('fields')}")
    print(f"  {plan.get('body', '')}{R}")


def show_them(events):
    """Print the target's reaction, in their color."""
    if not events:
        print(f"{THEM}◀ TARGET: ignored{R}")
        return
    for e in events:
        if e.get("type") == "reply":
            print(f"{THEM}◀ TARGET reply via {e.get('channel')}:\n  {e.get('body')}{R}")
        else:
            kept = {k: v for k, v in e.items() if k in ("url", "fields", "values")}
            print(f"{THEM}◀ TARGET event: {e.get('type')} {kept}{R}")


def run_session(content_client, content_model, scenario, target, headers, brief, attempt, dry):
    """One session = one clean-slate exchange with a single pinned identity.
    Returns True if an objective was won, False if the session died without one."""
    transcript, persona, ignores = "", {}, 0
    plan = next_move(content_client, content_model, scenario, target, brief, transcript, persona, attempt)
    finalize(plan, persona)
    if dry:
        show_us(plan, "draft")
        return False

    sid = post_api(f"{API}/sessions", headers, {"scenario_id": scenario["id"]})["session_id"]
    for touch in range(MAX_TOUCHES):
        if plan.get("stop") or not plan.get("body"):
            print("-> agent stops:", plan.get("rationale") or "no message produced")
            return False
        show_us(plan, touch + 1)
        events = send(sid, plan, target["id"], headers).get("events", [])
        show_them(events)

        won = wins_from_events(events)
        for e in events:  # disclosure most often arrives as free text, which has no event type
            if e.get("type") == "reply" and "disclosure" not in won \
                    and reply_discloses(content_client, content_model, target, e.get("body", "")):
                won.add("disclosure")
        if won:
            print(f"*** OBJECTIVE WON: {', '.join(sorted(won))} (session {sid}) ***")
            return True

        ignores = ignores + 1 if not events else 0
        if ignores >= MAX_IGNORES:
            print(f"-> {ignores} contacts ignored: pretext is dead, abandoning session {sid}")
            return False

        transcript += ("\n\n" if transcript else "") + describe(plan, events)
        plan = next_move(content_client, content_model, scenario, target, brief, transcript, persona, attempt)
        finalize(plan, persona)
    print("-> touch cap reached without a win")
    return False


def run_target(client, model, content_client, content_model, scenario, target, headers, dry):
    print(f"\n=== {target['name']} ({target['id']}) ===")
    brief = research(client, model, target)
    for attempt in range(MAX_SESSIONS):
        if attempt:
            print(f"--- fresh session (attempt {attempt + 1}/{MAX_SESSIONS}) ---")
        if run_session(content_client, content_model, scenario, target, headers, brief, attempt, dry) or dry:
            return


def main():
    dry = "--dry-run" in sys.argv
    load_env()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])            # research (web_search)
    model = os.environ["APP_MODEL_ID"]
    content_client = OpenAI(base_url=os.environ["AMD_BASE_URL"],     # message content (AMD Token Factory)
                            api_key=os.environ["AMD_API_KEY"])
    content_model = os.environ.get("AMD_MODEL_ID", "DeepSeek-V4-Flash")
    headers = {"Authorization": f"Bearer {os.environ['TARGET_API_TEAM_KEY']}"}

    scenarios = requests.get(f"{API}/scenarios", headers=headers, timeout=30).json()
    for scenario in [s for s in scenarios if s.get("kind") == "practice"]:
         #for target in scenario["targets"]:
         target = scenario["targets"][2]  # only one target per practice scenario
         run_target(client, model, content_client, content_model,
                       scenario, target, headers, dry)


# self-checks: JSON extraction and objective detection from events
assert extract_json('```json\n{"a": 1}\n```')["a"] == 1
assert extract_json('Sure! {"a": 2} done')["a"] == 2
assert wins_from_events([{"type": "page.submitted", "fields": ["email", "password"]}]) == {"credentials"}
assert wins_from_events([{"type": "page.submitted", "fields": ["approver", "vpn_client"]}]) == {"disclosure"}
assert wins_from_events([{"type": "page.submitted", "fields": ["name", "email"]}]) == set()
assert wins_from_events([{"type": "attachment.opened"}]) == {"action"}
assert wins_from_events([{"type": "link.opened", "url": "x"}]) == set()
assert ensure_url_in_body("see [link] now", "http://x.io") == "see http://x.io now"
assert ensure_url_in_body("see [Link] now", "http://x.io") == "see http://x.io now"
assert ensure_url_in_body("go [registration link] ok", "http://x.io") == "go http://x.io ok"
assert ensure_url_in_body("no link here", "http://x.io").endswith("\n\nhttp://x.io")
assert ensure_url_in_body("already http://x.io", "http://x.io") == "already http://x.io"
# pin_identity: first touch commits name+domain, later touches are forced to match
_p = {}
pin_identity({"from": {"name": "Sarah", "address": "s@secinsights.eu"}}, _p)
assert _p == {"name": "Sarah", "domain": "secinsights.eu"}
_pl = {"from": {"name": "Lena", "address": "l@consulting.de"}}
pin_identity(_pl, _p)
assert _pl["from"] == {"name": "Sarah", "address": "l@secinsights.eu"}

if __name__ == "__main__":
    main()

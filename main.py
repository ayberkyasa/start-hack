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

from openai import OpenAI

from api_client import APIClient

MAX_TOUCHES = 10    # per session; practice budget is 30/session
MAX_IGNORES = 2     # consecutive ignores -> the pretext is dead, stop this target's session
# Email BODY format. False (current): bodies are forced to plain text, which reads more like a real
# person and the twin reacts to words, not layout (API_DOCS "How the look is judged"). Landing PAGES
# still use HTML regardless. Flip to True to let the model write self-contained HTML email bodies again.
HTML_EMAIL_BODY = False

# Terminal colors: our messages vs the target's reactions (blank when piped to a file).
_TTY = sys.stdout.isatty()
US = "\033[96m" if _TTY else ""     # cyan: the message we send
THEM = "\033[93m" if _TTY else ""   # yellow: the target's reaction
PLAN = "\033[1;95m" if _TTY else "" # bold magenta: the one-line decision banner (stands out from logs)
DBG = "\033[95m" if _TTY else ""    # magenta: research tool activity
R = "\033[0m" if _TTY else ""

# Which form field names count as which objective (API_DOCS "Forms: what counts").
SECRET = {"password", "pin", "otp", "verification_code", "token", "api_key",
          "card_number", "iban", "cvv", "cvc"}
BASIC = {"name", "email", "company", "job_title", "phone", "username",
         "first_name", "last_name"}

# Local files the agent may upload as assets and reference by exact filename.
# Images (PNG/JPG/WebP) embed inline via <img src="asset://NAME"> or attach; PDFs attach.
# Drop files here; up to 5 MB each (API_DOCS "Files and images"). Reusable across sessions.
ASSET_DIR = "assets"
ASSET_EXT = (".png", ".jpg", ".jpeg", ".webp", ".pdf")
_asset_ids = {}   # local filename -> asset_id, so a file is uploaded at most once per run


def available_assets():
    """Filenames in ASSET_DIR the agent may embed/attach (accepted type, <=5 MB)."""
    if not os.path.isdir(ASSET_DIR):
        return []
    out = []
    for name in sorted(os.listdir(ASSET_DIR)):
        p = os.path.join(ASSET_DIR, name)
        if (name.lower().endswith(ASSET_EXT) and os.path.isfile(p)
                and os.path.getsize(p) <= 5 * 1024 * 1024):
            out.append(name)
    return out


def upload_asset(name, api):
    """Upload one local file via APIClient.upload_asset (POST /assets); cache the id.
    Returns the asset_id. Assets are team-wide and reusable (API_DOCS "Files and images")."""
    if name in _asset_ids:
        return _asset_ids[name]
    aid = api.upload_asset(os.path.join(ASSET_DIR, name), filename=name)["asset_id"]
    _asset_ids[name] = aid
    return aid


def strip_unknown_images(html, local):
    """Remove any image tag whose asset:// source is NOT one of the known uploaded files, so a
    missing/broken image never ships (the craft rubric penalizes missing images). Image tags
    pointing at a real asset are kept for id resolution; non-asset image tags are left alone."""
    tag = "<" + "img"

    def keep_or_drop(m):
        ref = re.search(r"asset://([^\"')\s>]+)", m.group(0))
        return "" if (ref and ref.group(1) not in local) else m.group(0)

    return re.sub(rf"{tag}\b[^>]*>", keep_or_drop, html)


def resolve_assets(plan, api):
    """Turn the model's asset *filenames* into real asset ids, in place, just before sending:
      - inline <img src="asset://NAME"> in the mail body and in the page html,
      - NAME entries in `attachments` and in `page.images`.
    A filename that is NOT a local asset (e.g. a lure like 'Invoice_4711.pdf') is left as a
    declared, not-uploaded attachment ({"filename": NAME}) per API_DOCS; nothing is sent for it."""
    local = set(available_assets())

    def swap_inline(text):
        """Resolve asset://NAME -> real id for files we actually have; drop any image tag that
        points at a file we DON'T have, so a broken/missing image never ships (craft penalty)."""
        if not text:
            return text
        text = strip_unknown_images(text, local)
        return re.sub(r"asset://([^\"')\s>]+)",
                      lambda m: (f"asset://{upload_asset(m.group(1), api)}"
                                 if m.group(1) in local else m.group(0)),
                      text)

    plan["body"] = swap_inline(plan.get("body", ""))
    page = plan.get("page")
    if page:
        if page.get("html"):
            page["html"] = swap_inline(page["html"])
        if page.get("images"):  # page shown without html: images are asset ids
            page["images"] = [upload_asset(x, api) if x in local else x
                              for x in page["images"]]
    atts = plan.get("attachments")
    if atts:
        plan["attachments"] = [
            (upload_asset(a, api) if a in local else {"filename": a})
            if isinstance(a, str) else a   # already a declared {"filename"/"transcript"} object
            for a in atts
        ]


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
    """Judge a reply for the disclosure objective. There is no API event for free-text disclosure,
    so this is our own heuristic for whether to stop pushing. It mirrors the only rubric API_DOCS
    gives (the forms table): 'internal and not public (systems, processes, plans)' counts; basic
    contact/identity details do not. Kept strict so the agent doesn't quit on weak info."""
    r = client.chat.completions.create(model=model, timeout=60, messages=[{"role": "user", "content": (
        f"Target: {target['name']} ({target['role']}). In a security simulation they replied:\n\n"
        f"{reply_text}\n\n"
        "The 'disclosure' objective means learning INTERNAL facts that are NOT public: specific "
        "internal systems/tools/vendors, credentials or approval processes, access paths, internal "
        "metrics or numbers, org/security details, or unannounced plans/roadmaps.\n"
        "These do NOT count: name, email, phone, job title, company, username; the person's "
        "availability or travel/calendar; public statements, opinions, philosophy, or anything "
        "findable online; vague or general remarks.\n"
        "Answer 'yes' ONLY if the reply states at least one concrete internal, non-public fact of "
        "the kind above; otherwise 'no'. Reply with ONLY 'yes' or 'no'."
    )}])
    return r.choices[0].message.content.strip().lower().startswith("y")


def to_plaintext(s):
    """Collapse HTML into readable plain text (the hard guard behind HTML_EMAIL_BODY=False).
    Keeps line breaks from <br>/</p> and bullets from <li>; drops all other tags; unescapes entities.
    A body that is already plain text passes through essentially unchanged."""
    import html as _html
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"<[^>]+>", "", s)            # strip any remaining tags
    s = _html.unescape(s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def finalize(plan, persona):
    """Pin the sender, force the body to plain text (unless HTML_EMAIL_BODY), and guarantee the
    registered URL is in the body, before logging or sending."""
    pin_identity(plan, persona)
    if not HTML_EMAIL_BODY:
        plan["body"] = to_plaintext(plan.get("body", ""))
    if plan.get("page"):
        plan["body"] = ensure_url_in_body(plan.get("body", ""), plan["page"]["url"])


def research(client, model, target):
    """OSINT the target via OpenAI web_search plus our OSINT MCP server
    (search_public_mentions + sherlock + fetch_url, served over Streamable HTTP);
    return an objective-mapped attacker brief for the message-writing step."""
    r = client.responses.create(
        model=model,
        tools=[
            {"type": "web_search"},
            {"type": "mcp", "server_label": "osint",
             "server_url": os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp"),
             "require_approval": "never"},
        ],
        tool_choice="required",  # force at least one tool call; without it the model answers from memory
        input=(
            "You are the reconnaissance step of a consented phishing simulation. The target is an "
            "AI twin of a real person; everything public about them is true for the twin. Build an "
            "attacker's brief that the message-writing step will use directly.\n"
            f"TARGET: {target['name']} - {target['role']}.\n\n"
            "Use every tool: web_search for the open web; Do deep search on the web. use `fetch_url` for each page to "
            "READ the full text of a page a search only summarised. Corroborate across "
            "tools and prefer concrete, dated facts over generalities.\n\n"
            "Output a brief with these labelled sections (omit one only if you truly found nothing):\n"
            "1. WHO - role, company, what they own, how they come across publicly.\n"
            "2. HOOKS - what this person is open to or cares about RIGHT NOW (projects, launches, "
            "hiring, events, deadlines, public asks). These are the openings; be specific and dated.\n"
            "3. RECENT & CITABLE - concrete recent facts (talks, posts, news) with dates and sources, "
            "usable as proof that a message is legitimate.\n"
            "4. TRUST GRAPH - people, vendors, tools and services they plausibly get mail from "
            "(candidates to impersonate), plus realistic look-alike sender domains an attacker could "
            "register (never the company's own domain).\n"
            "5. PRETEXTS - 2-3 attack ideas, each mapped to one objective: 'credentials' (they sign in "
            "on a page we host), 'action' (open a file / approve / forward), or 'disclosure' (reveal "
            "something internal and non-public). For each: the story, the channel, who it's from, and "
            "which HOOK it exploits."
        ),
    )
   
    # Verbose eval: did the model actually reach for the tools? Dump each tool item.
    for item in r.output:
        t = getattr(item, "type", "")
        if t == "mcp_list_tools":
            names = [getattr(x, "name", x) for x in getattr(item, "tools", [])]
            print(f"{DBG}  [research] MCP server {getattr(item, 'server_label', '?')} exposed: {names}{R}")
        elif t == "mcp_call":
            err = getattr(item, "error", None)
            out = getattr(item, "output", "") or ""
            print(f"{DBG}  [research] MCP CALL {getattr(item, 'name', '?')}({getattr(item, 'arguments', '')})"
                  f" -> {('ERROR ' + str(err)) if err else (str(len(out)) + ' chars')}{R}")
        elif t == "web_search_call":
            print(f"{DBG}  [research] web_search {getattr(item, 'status', '')}{R}")
        else:
            print(f"{DBG}  [research] (item: {t or '?'}){R}")  # reasoning/message/etc. - no hidden tool call
    print(f"{DBG}  [research] final brief: {r.output_text}")
    return r.output_text


def next_move(client, model, scenario, target, brief, transcript, persona):
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
    assets = available_assets()
    img_tag = "<" + "img src=\"asset://FILENAME\">"
    assets_line = (
        "INLINE IMAGES (landing-page HTML only) -- for an image use ONLY these exact uploaded files "
        + (f"({', '.join(assets)})" if assets else "(none are uploaded, so use NO image)")
        + f": {img_tag}. Do NOT invent an image name; an unknown name renders as a broken image "
          "and loses craft points. If none fit, use no image.\n"
        "ATTACHMENTS are separate: you may list ANY filename in \"attachments\" as a lure "
        "(e.g. a believable 'Invoice_2026.pdf'); it is shown to the person by filename only "
        "(no file is uploaded) and an open counts as an 'action'.\n")
    body_rule = (
        "For email (and the landing page), you MAY write real HTML to look legitimate: it must "
        "be self-contained -- inline CSS only, NO scripts, and images ONLY via asset:// from the "
        "asset list (external image URLs are not loaded). On plain-text channels (sms, whatsapp, "
        "signal, telegram, slack, linkedin_message) send plain text, not HTML.\n"
        if HTML_EMAIL_BODY else
        "Write the message BODY as PLAIN TEXT on every channel -- a normal typed email/message, NO "
        "HTML tags. Put any link inline as a plain URL and sign off with a plain-text signature. "
        "(Only the LANDING PAGE uses HTML; see below.)\n")
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
            f"{identity}\n"
            "You may include a landing page or an attachment the person might open. A landing "
            "page's fields MUST fit its pretext: only ask for a password or other secret on a "
            "believable sign-in to an account the person already has, NEVER on a survey, "
            "registration, or information form. If the last contact was IGNORED, do not repeat "
            "it: change the angle or switch channel. Stop only if the person is clearly "
            "suspicious and further contact would backfire.\n\n"
            f"{body_rule}"
            "A LANDING PAGE may use self-contained HTML (inline CSS, no scripts, images only via "
            "asset:// from the asset list); without html it falls back to text + optional images.\n"
            f"{assets_line}\n"
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
            '  "body": "<the message as plain text (no HTML)>",\n'
            '  "page": null,                     // OR {"url","title","html":"<!doctype html>...", "fields":[...]}\n'
            '                                    //    (use "text" instead of "html" for a plain form; "images":["file.png"] optional)\n'
            '  "attachments": null               // OR ["logo.png", "Invoice_4711.pdf"] -- an asset filename is uploaded & attached,\n'
            '                                    //    any other filename is shown as a lure to open (action); audio: {"filename","transcript"}\n'
            "}"
        )}],
    )
    return extract_json(r.choices[0].message.content)


def send(api, sid, plan, target_id):
    """Register an optional landing page, then send the crafted message. Returns the response.
    The client owns retries and the per-message Idempotency-Key."""
    resolve_assets(plan, api)   # upload referenced local files, swap names -> asset ids
    page = plan.get("page")
    if page:
        # the API wants fields as plain strings; the model sometimes emits {"name","type"} objects
        page = {k: plan["page"][k] for k in ("url", "title", "html", "text", "fields", "images")
                if k in plan["page"]}
        fields = [f.get("name") if isinstance(f, dict) else f for f in page.get("fields", [])]
        api.register_page(sid, page["url"], title=page.get("title"),
                          html=page.get("html"), text=page.get("text"), fields=fields)
    return api.send_message(sid, to=target_id, channel=plan.get("channel"),
                            body=plan.get("body", ""), sender=plan.get("from"),
                            subject=plan.get("subject"), attachments=plan.get("attachments"))


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


def plan_summary(plan):
    """One line that says exactly what this touch will do: channel, sender, whether the body
    is HTML, whether a landing page / HTML / inline image / attachment is attached (and which
    filename). Reads the plan BEFORE sending, so it's the same in a live run and in --dry-run."""
    frm = plan.get("from") or {}
    who = " ".join(x for x in (frm.get("name"), f"<{frm['address']}>" if frm.get("address") else "") if x)
    body = plan.get("body", "") or ""
    parts = [str(plan.get("channel", "?")).upper(), f"as {who or '?'}",
             "HTML body" if ("<" in body and ">" in body) else "text body"]
    if "asset://" in body:
        parts.append("inline image")
    page = plan.get("page")
    if page:
        fields = ",".join(str(f.get("name") if isinstance(f, dict) else f) for f in page.get("fields", []))
        parts.append(("HTML landing page" if page.get("html") else "form page")
                     + (f" [{fields}]" if fields else ""))
    names = [a if isinstance(a, str) else (a.get("filename") or "?") for a in (plan.get("attachments") or [])]
    if names:
        parts.append("attach " + ", ".join(names))
    return " · ".join(parts)


PREVIEW_DIR = "preview"


def _preview_localize(html):
    """Rewrite asset://NAME -> ../assets/NAME so your local images render in a browser preview.
    (The real send keeps asset:// and resolve_assets turns it into a real asset id.)"""
    return re.sub(r"asset://([^\"')\s>]+)", lambda m: f"../{ASSET_DIR}/{m.group(1)}", html)


def save_preview(plan, touch):
    """Dump any HTML this touch produces to preview/ so you can open it in Chrome.
    Writes the email body and/or the landing-page html; skips plain-text touches.
    Runs in both live and --dry-run, so every HTML the agent writes lands on disk."""
    saved = []
    jobs = []
    body = plan.get("body", "") or ""
    if "<" in body and ">" in body:
        jobs.append((f"touch{touch}_email.html", body))
    page = plan.get("page") or {}
    if page.get("html"):
        jobs.append((f"touch{touch}_page.html", page["html"]))
    for name, html in jobs:
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        html = _preview_localize(html)
        if "<html" not in html.lower():
            html = f"<!doctype html><html><body>{html}</body></html>"
        path = os.path.join(PREVIEW_DIR, name)
        with open(path, "w") as f:
            f.write(html)
        saved.append(path)
    return saved


def show_us(plan, touch):
    """Print the message we're sending, in our color."""
    # Bold-magenta decision banner: at a glance, what this touch sends (live and dry-run alike).
    print(f"{PLAN}  PLAN [{touch}] {plan_summary(plan)}{R}")
    for p in save_preview(plan, touch):
        print(f"{PLAN}       ↳ HTML preview: {p}  (open in a browser){R}")
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


def run_session(content_client, content_model, scenario, target, api, brief, dry):
    """One session = one clean-slate exchange with a single pinned identity.
    Returns True if an objective was won, False if the session died without one."""
    transcript, persona, ignores = "", {}, 0
    plan = next_move(content_client, content_model, scenario, target, brief, transcript, persona)
    finalize(plan, persona)
    if dry:
        show_us(plan, "draft")
        return False

    sid = api.create_session(scenario["id"])["session_id"]
    for touch in range(MAX_TOUCHES):
        if plan.get("stop") or not plan.get("body"):
            print("-> agent stops:", plan.get("rationale") or "no message produced")
            return False
        show_us(plan, touch + 1)
        events = send(api, sid, plan, target["id"]).get("events", [])
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
        plan = next_move(content_client, content_model, scenario, target, brief, transcript, persona)
        finalize(plan, persona)
    print("-> touch cap reached without a win")
    return False


def run_target(client, model, content_client, content_model, scenario, target, api, dry):
    # One session per target, then stop. If it's abandoned (ignored/pretext dead) we do NOT
    # open a fresh session -- rerun the script manually to try another angle from scratch.
    print(f"\n=== {target['name']} ({target['id']}) ===")
    brief = research(client, model, target)
    run_session(content_client, content_model, scenario, target, api, brief, dry)


def send_preview(to_addr):
    """Email the already-generated preview/*_email.html files to `to_addr` so you can see how
    they render in a real mail client. Opt-in: only runs with `python main.py --send-preview addr`.
    Credentials come from .env (Gmail defaults): SMTP_USER + SMTP_PASS (a Gmail App Password),
    optional SMTP_HOST/SMTP_PORT. The From address is SMTP_USER. Referenced local images are
    embedded inline (CID) so they actually show in the mail."""
    import glob
    import smtplib
    import ssl
    from email.message import EmailMessage
    load_env()
    try:
        user, pw = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    except KeyError:
        print("Set SMTP_USER and SMTP_PASS in .env first (Gmail: your address + a 16-char App Password).")
        return
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    pw = pw.replace(" ", "")   # Gmail shows App Passwords in 4-char groups; the spaces aren't part of it
    files = sorted(glob.glob(os.path.join(PREVIEW_DIR, "*_email.html")))
    if not files:
        print(f"No preview emails in {PREVIEW_DIR}/. Run `python main.py --dry-run` (or a real run) first.")
        return

    def build(path):
        html = open(path).read()
        cids = {}

        def to_cid(m):
            name = os.path.basename(m.group(1))
            if not os.path.isfile(os.path.join(ASSET_DIR, name)):
                return m.group(0)
            cids[name] = name.replace(".", "_")
            return f'src="cid:{cids[name]}"'

        html = re.sub(r'src="(?:\.\./)?assets/([^"]+)"', to_cid, html)
        msg = EmailMessage()
        msg["Subject"] = f"[preview] {os.path.basename(path)}"
        msg["From"], msg["To"] = user, to_addr
        msg.set_content("This is an HTML email preview; view it in an HTML-capable client.")
        msg.add_alternative(html, subtype="html")
        html_part = msg.get_payload()[-1]
        for name, cid in cids.items():
            subtype = {"jpg": "jpeg"}.get(name.lower().rsplit(".", 1)[-1], name.lower().rsplit(".", 1)[-1])
            with open(os.path.join(ASSET_DIR, name), "rb") as f:
                html_part.add_related(f.read(), "image", subtype, cid=f"<{cid}>")
        return msg

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)   # implicit TLS
        else:
            server = smtplib.SMTP(host, port, timeout=30)                    # 587 = STARTTLS
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
    except (smtplib.SMTPException, OSError) as e:
        print(f"Could not connect to {host}:{port} ({e}). For Gmail use port 587 (STARTTLS, the "
              "default) or 465 (set SMTP_PORT=465); check SMTP_HOST/SMTP_PORT and your network/firewall.")
        return
    with server:
        try:
            server.login(user, pw)
        except smtplib.SMTPAuthenticationError:
            print("SMTP auth rejected. SMTP_PASS must be a Gmail *App Password* (16 chars, with 2-Step "
                  "Verification ON) -- not your normal Google password. Create one at Google Account > "
                  "Security > App passwords; spaces are stripped automatically.")
            return
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPException) as e:
            print(f"SMTP login failed ({e}). If you're on port 587, try SMTP_PORT=465 (SSL); also "
                  "confirm SMTP_PASS is an App Password, not your normal password.")
            return
        for path in files:
            server.send_message(build(path))
            print(f"sent {os.path.basename(path)} -> {to_addr}")


def main():
    if "--send-preview" in sys.argv:
        i = sys.argv.index("--send-preview")
        to = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        if not to:
            print("usage: python main.py --send-preview you@email.com")
            return
        send_preview(to)
        return
    dry = "--dry-run" in sys.argv
    load_env()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])            # research (web_search)
    model = os.environ["APP_MODEL_ID"]
    content_client = OpenAI(base_url=os.environ["AMD_BASE_URL"],     # message content (AMD Token Factory)
                           api_key=os.environ["AMD_API_KEY"])
    content_model = os.environ.get("AMD_MODEL_ID", "DeepSeek-V4.1-Flash")
    api = APIClient(team_key=os.environ["TARGET_API_TEAM_KEY"])

    for scenario in [s for s in api.list_scenarios() if s.get("kind") == "practice"]:
         #for target in scenario["targets"]:
         target = scenario["targets"][0]  # only one target per practice scenario
         run_target(client, model, content_client, content_model,
                       scenario, target, api, dry)


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
# resolve_assets: with no local assets, a named file becomes a declared (not uploaded) lure,
# body is untouched, and already-declared objects pass through. (No network: nothing to upload.)
assert not available_assets() or ASSET_DIR  # smoke: callable
_ra = {"body": "hi", "attachments": ["Invoice_4711.pdf", {"filename": "vm.m4a", "transcript": "x"}]}
if not available_assets():
    resolve_assets(_ra, {})
    assert _ra["attachments"] == [{"filename": "Invoice_4711.pdf"}, {"filename": "vm.m4a", "transcript": "x"}]
    assert _ra["body"] == "hi"
# plan_summary: the one-line decision banner
_s = plan_summary({"channel": "email", "from": {"name": "Lena Hofer", "address": "lena@summit-berlin.de"},
                   "body": "<p>hi</p><img src='asset://hdr.png'>", "page": {"html": "<x>", "fields": ["email", "password"]},
                   "attachments": ["hdr.png", "Invoice_4711.pdf"]})
assert _s == ("EMAIL · as Lena Hofer <lena@summit-berlin.de> · HTML body · inline image · "
              "HTML landing page [email,password] · attach hdr.png, Invoice_4711.pdf"), _s
assert plan_summary({"channel": "linkedin_message", "from": {"name": "Max"}, "body": "hey, quick q"}) \
    == "LINKEDIN_MESSAGE · as Max · text body"
# to_plaintext: HTML body collapses to readable text; plain text is untouched
assert to_plaintext("<html><body><p>Hi Tom,</p><p>See <a href='http://x.io'>here</a></p></body></html>") \
    == "Hi Tom,\n\nSee here"
assert to_plaintext("<p>One</p><ul><li>a</li><li>b</li></ul>") == "One\n\n- a\n- b"
assert to_plaintext("just a normal line") == "just a normal line"
# strip_unknown_images: keep image tags for real assets, drop ones for files we don't have
assert strip_unknown_images('<img src="asset://ais_logo.png"> hi', {"ais_logo.png"}) == '<img src="asset://ais_logo.png"> hi'
assert strip_unknown_images('a <img src="asset://nope.png"/> b', {"ais_logo.png"}) == 'a  b'
assert strip_unknown_images('<img src="asset://nope.png">', set()) == ''
assert strip_unknown_images('<p>no image</p>', {"ais_logo.png"}) == '<p>no image</p>'
# _preview_localize: asset refs point at the local assets/ dir so a browser preview shows them
assert _preview_localize('<img src="asset://logo.png">') == '<img src="../assets/logo.png">'
assert _preview_localize("<p>no images</p>") == "<p>no images</p>"

if __name__ == "__main__":
    main()

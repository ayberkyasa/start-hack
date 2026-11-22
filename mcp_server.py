"""Streamable HTTP MCP server exposing OSINT tools for the research step.

Tools:
  - search_public_mentions: public social-media mentions via the Social Searcher API.
  - sherlock: hunt a username across social networks via the `sherlock` CLI.

Run (serves at http://127.0.0.1:8000/mcp):
  uv run python mcp_server.py

Credentials come from the environment (.env, same file main.py uses):
  SOCIAL_SEARCHER_API_KEY   # required by search_public_mentions

NOTE: Social Searcher's public API docs are offline as of 2026 and recent sources say
the developer API may be retired; this hits the long-standing v2 endpoint, so it works
only with a valid key and otherwise returns a clean provider error (never a fake hit).
"""
import os
import re
import subprocess

import requests
from mcp.server.mcpserver import MCPServer  # FastMCP renamed to MCPServer in mcp 2.x
from mcp.server.transport_security import TransportSecuritySettings

from main import load_env  # reuse the .env reader

SOCIAL_SEARCHER_URL = "https://api.social-searcher.com/v2/search"
MAX_FETCH_BYTES = 200_000  # cap the download so a huge page can't blow up memory or the brief

mcp = MCPServer("osint")


def _html_to_text(html):
    """Crude tag strip: drop script/style, remove tags, collapse whitespace. Good enough to feed an LLM."""
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", html).strip()


def _extract_results(data, seen):
    """Turn a Social Searcher response into {title, url, snippet} rows, deduped by URL.
    Pure (no network) so the self-checks below can exercise the parsing/dedup."""
    out = []
    for p in data.get("posts") or []:
        url = p.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({
            "title": p.get("title") or (p.get("user") or {}).get("name") or p.get("network"),
            "url": url,
            "snippet": p.get("text"),
        })
    return out


def _social_searcher(query, networks, limit):
    """One GET per network (the v2 API takes a single `network`), merged and deduped.
    Returns (results, error): error is set ONLY on a provider failure; an empty list with
    error=None means the search genuinely found nothing."""
    key = os.environ.get("SOCIAL_SEARCHER_API_KEY")
    if not key:
        return [], "SOCIAL_SEARCHER_API_KEY is not set"
    seen, results = set(), []
    for net in networks:
        params = {"q": query, "limit": limit, "key": key}
        if net:
            params["network"] = net
        try:
            r = requests.get(SOCIAL_SEARCHER_URL, params=params, timeout=30)
        except requests.RequestException as e:
            return [], f"request failed: {e}"
        if r.status_code != 200:
            return [], f"provider HTTP {r.status_code}: {r.text[:200]}"
        try:
            data = r.json()
        except ValueError:
            return [], f"non-JSON provider response: {r.text[:200]}"
        # the API reports its own errors inside the body even on HTTP 200
        meta = data.get("meta") or {}
        if data.get("error") or (str(meta.get("http_code", "200")) >= "400"):
            return [], f"provider error: {data.get('error') or meta}"
        results.extend(_extract_results(data, seen))
    return results, None


# @mcp.tool()
def search_public_mentions(query: str, platforms: list[str] | None = None, limit: int = 10) -> dict:
    """Search public social-media mentions of `query` via the Social Searcher API.

    platforms: networks to search, e.g. ["twitter", "reddit", "web", "linkedin"];
               None searches without a network filter (the API default).
    limit:     max results returned (deduped across networks).

    Returns {provider, query, count, results: [{title, url, snippet}], error}.
    `error` is non-null only on a provider failure; an empty `results` with error=None
    means the search simply found nothing.

    Example: search_public_mentions("revel8 founders", ["web", "linkedin"], 5)
    """
    networks = platforms or [None]  # [None] -> a single call with no network filter
    results, error = _social_searcher(query, networks, limit)
    return {"provider": "social-searcher", "query": query,
            "count": len(results[:limit]), "results": results[:limit], "error": error}


# @mcp.tool()
def sherlock(username: str, timeout: int = 10) -> dict:
    """Hunt a username across social networks with the Sherlock CLI (OSINT).

    Requires the `sherlock` CLI (pip install sherlock-project). Returns
    {provider, username, count, profiles: [url], error}; `error` is non-null only when
    the tool could not run.
    """
    try:
        proc = subprocess.run(
            ["sherlock", "--print-found", "--timeout", str(timeout), "--no-color", username],
            capture_output=True, text=True, timeout=timeout * 60 + 30,
        )
    except FileNotFoundError:
        return {"provider": "sherlock", "username": username, "count": 0, "profiles": [],
                "error": "sherlock CLI not installed (pip install sherlock-project)"}
    except subprocess.TimeoutExpired:
        return {"provider": "sherlock", "username": username, "count": 0, "profiles": [],
                "error": "sherlock timed out"}
    profiles = re.findall(r"https?://\S+", proc.stdout)
    return {"provider": "sherlock", "username": username, "count": len(profiles),
            "profiles": profiles, "error": None}


@mcp.tool()
def fetch_url(url: str, max_chars: int = 4000) -> dict:
    """Fetch a web page and return its visible text (HTML tags stripped), to read a promising
    search hit in full instead of a snippet.

    Returns {provider, url, status, text, error}; `error` is non-null only on a fetch failure.
    Download is capped and `text` is truncated to `max_chars`.

    Example: fetch_url("https://example.com/post", 2000)
    """
    if not url.lower().startswith(("http://", "https://")):
        return {"provider": "fetch_url", "url": url, "status": None, "text": "", "error": "url must be http(s)"}
    try:
        r = requests.get(url, timeout=20, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (research bot)"})
        r.raise_for_status()
        chunks, n = [], 0
        for c in r.iter_content(65536):
            chunks.append(c)
            n += len(c)
            if n >= MAX_FETCH_BYTES:
                break
        r.close()
    except requests.RequestException as e:
        return {"provider": "fetch_url", "url": url, "status": None, "text": "", "error": f"fetch failed: {e}"}
    html = b"".join(chunks).decode(r.encoding or "utf-8", "replace")
    return {"provider": "fetch_url", "url": url, "status": r.status_code,
            "text": _html_to_text(html)[:max_chars], "error": None}


# Keyless web search so ANY research model (e.g. DeepSeek on the AMD endpoint) can search the open
# web without OpenAI's native `web_search` tool. Uses DuckDuckGo's HTML endpoint and parses the
# organic result links; returns the same {title, url, snippet} shape as the other tools, so the
# model can then call `fetch_url` on a hit to read it in full.
DDG_URL = "https://html.duckduckgo.com/html/"
_SEARCH_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _decode_ddg_url(href):
    """DuckDuckGo result links are redirects (`//duckduckgo.com/l/?uddg=<urlencoded>`). Decode the
    `uddg` param to the real destination so the model can `fetch_url` it directly; fall back to the
    redirect URL itself (made absolute) if decoding fails."""
    if not href:
        return None
    m = re.search(r"[?&]uddg=([^&]+)", href)
    if m:
        import urllib.parse as _up
        try:
            return _up.unquote(m.group(1))
        except Exception:
            pass
    return href if href.startswith("http") else ("https:" + href)


def _parse_ddg(html):
    """Pull organic results out of a DuckDuckGo HTML page. Pure (no network) so it is unit-testable.
    Parses each `result__a` link directly (DuckDuckGo's current HTML does not wrap results in a
    `result__body` div), decodes the redirect URL, and grabs the sibling `result__snippet`."""
    out = []
    seen = set()
    for block in re.findall(r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>', html, re.S):
        a = re.search(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        url = _decode_ddg_url(a.group(1))
        if not url or url in seen:
            continue
        seen.add(url)
        snip = re.search(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        out.append({
            "title": _html_to_text(a.group(2)),
            "url": url,
            "snippet": _html_to_text(snip.group(1)) if snip else "",
        })
    return out


@mcp.tool()
def web_search(query: str, limit: int = 8) -> dict:
    """Keyless web search of the open web (DuckDuckGo). Use this when you need to discover pages,
    then call `fetch_url` on a promising result to read it in full.

    Returns {provider, query, count, results: [{title, url, snippet}], error}; `error` is non-null
    only on a search failure (an empty `results` with error=None means nothing was found).

    Example: web_search("revel8 Julius Muth CEO", 6)
    """
    try:
        r = requests.get(DDG_URL, params={"q": query}, headers=_SEARCH_UA, timeout=25)
    except requests.RequestException as e:
        return {"provider": "duckduckgo", "query": query, "count": 0, "results": [],
                "error": f"search failed: {e}"}
    if r.status_code != 200:
        return {"provider": "duckduckgo", "query": query, "count": 0, "results": [],
                "error": f"search HTTP {r.status_code}"}
    results = _parse_ddg(r.text)[:limit]
    return {"provider": "duckduckgo", "query": query, "count": len(results),
            "results": results, "error": None}


# self-check: parsing, dedup, url-skip, and title fallback (no network needed)
_seen = set()
_r = _extract_results({"posts": [
    {"url": "http://a", "text": "hi", "network": "twitter", "user": {"name": "Jo"}},
    {"url": "http://a", "text": "dup"},   # same url -> deduped
    {"text": "no url"},                    # no url -> skipped
    {"url": "http://b", "network": "web"},  # title falls back to network
]}, _seen)
assert [x["url"] for x in _r] == ["http://a", "http://b"]
assert _r[0]["title"] == "Jo" and _r[0]["snippet"] == "hi"
assert _r[1]["title"] == "web" and _r[1]["snippet"] is None
# _html_to_text: drops script/style, strips tags, collapses whitespace
assert _html_to_text("<p>Hi <b>there</b></p>\n<script>x=1</script>") == "Hi there"


if __name__ == "__main__":
    load_env()
    # shortcut: DNS-rebinding protection off so ngrok's public Host header is accepted
    # (the rotating tunnel host can't be allowlisted); re-enable + set allowed_hosts if ever
    # exposed beyond a disposable hackathon tunnel.
    mcp.run(transport="streamable-http",  # http://127.0.0.1:8000/mcp
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

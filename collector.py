"""Official-source discovery for engineering opportunities across Telangana.

Google/search engines may be used for discovery, but the original official college or
university page is the only evidence source. This script discovers candidates only; it
never auto-publishes an item. A reviewer must verify date, organizer, eligibility,
official source URL and relevance before setting a record to published/verified.
"""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "sources.json"
OUT = ROOT / "data" / "review_candidates.json"
OFFICIAL_SUFFIXES = (".edu.in", ".ac.in", ".org.in")

class LinkTextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self._href=None; self._parts=[]
    def handle_starttag(self, tag, attrs):
        if tag == "a": self._href=dict(attrs).get("href"); self._parts=[]
    def handle_data(self, data):
        if self._href: self._parts.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            text=" ".join("".join(self._parts).split())
            if text: self.links.append((self._href,text))
            self._href=None; self._parts=[]

def fetch(url: str) -> str:
    req=Request(url,headers={"User-Agent":"OpportunityAtlasSourceReview/1.0 (official-source discovery only)"})
    with urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")

def approved_official_source(source: dict) -> bool:
    homepage=str(source.get("homepage") or "").strip()
    try: host=(urlparse(homepage).hostname or "").lower().rstrip(".")
    except ValueError: return False
    return bool(source.get("approved")) and source.get("collectionStatus")=="discovery_only" and urlparse(homepage).scheme=="https" and host.endswith(OFFICIAL_SUFFIXES)

def candidate_links(source: dict) -> list[dict]:
    if not approved_official_source(source): return []
    html=fetch(source["homepage"])
    parser=LinkTextParser(); parser.feed(html)
    keywords=re.compile(r"hackathon|ideathon|workshop|internship|placement|career|seminar|conference|symposium|event|competition|training|recruitment|fellowship|challenge|certification",re.I)
    now=datetime.now(timezone.utc).isoformat()
    try: domain=(urlparse(source["homepage"]).hostname or "").lower()
    except ValueError: domain=""
    candidates=[]; seen=set()
    for href,text in parser.links:
        if not keywords.search(text): continue
        url=urljoin(source["homepage"],href)
        if url in seen: continue
        seen.add(url)
        candidates.append({
            "candidateId": hashlib.sha256((source["id"]+url+text).encode()).hexdigest()[:16],
            "sourceId": source["id"], "institution": source["name"], "state":"Telangana", "district":source.get("district"),
            "sourceDomain":domain, "title": text[:220], "sourceUrl": url,
            "discoveredAt": now, "status": "needs_review",
            "reason": "Official institution-page candidate; date, eligibility, relevance and current status must be verified before publication."
        })
    return candidates

def main():
    registry=json.loads(REGISTRY.read_text(encoding="utf-8"))
    collected=[]; errors=[]
    for source in registry["sources"]:
        if not approved_official_source(source): continue
        try: collected.extend(candidate_links(source))
        except Exception as exc: errors.append({"sourceId":source["id"],"error":str(exc)[:300]})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"runAt":datetime.now(timezone.utc).isoformat(),"scope":"Telangana engineering colleges and universities","candidates":collected,"errors":errors},indent=2),encoding="utf-8")
    print(json.dumps({"candidates":len(collected),"errors":len(errors)}))

if __name__ == "__main__": main()

"""Daily official-source discovery for the Warangal opportunities portal.

This deliberately discovers candidates only. It never auto-publishes an item unless a
separate reviewer validates date, organiser, source link and relevance.
"""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "sources.json"
OUT = ROOT / "data" / "review_candidates.json"

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
    req=Request(url,headers={"User-Agent":"WarangalOpportunitiesBot/0.1 (source-review only)"})
    with urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")

def candidate_links(source: dict) -> list[dict]:
    html=fetch(source["homepage"])
    parser=LinkTextParser(); parser.feed(html)
    keywords=re.compile(r"hackathon|workshop|internship|placement|career|seminar|conference|event|club|training",re.I)
    now=datetime.now(timezone.utc).isoformat()
    candidates=[]
    for href,text in parser.links:
        if not keywords.search(text): continue
        url=urljoin(source["homepage"],href)
        candidates.append({
            "candidateId": hashlib.sha256((source["id"]+url+text).encode()).hexdigest()[:16],
            "sourceId": source["id"], "title": text[:220], "sourceUrl": url,
            "discoveredAt": now, "status": "needs_review",
            "reason": "Official source candidate; date and eligibility must be verified before publication."
        })
    return candidates

def main():
    registry=json.loads(REGISTRY.read_text(encoding="utf-8"))
    collected=[]; errors=[]
    for source in registry["sources"]:
        if not source.get("approved") or source.get("collectionStatus") != "discovery_only": continue
        try: collected.extend(candidate_links(source))
        except Exception as exc: errors.append({"sourceId":source["id"],"error":str(exc)[:300]})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"runAt":datetime.now(timezone.utc).isoformat(),"candidates":collected,"errors":errors},indent=2),encoding="utf-8")
    print(json.dumps({"candidates":len(collected),"errors":len(errors)}))

if __name__ == "__main__": main()

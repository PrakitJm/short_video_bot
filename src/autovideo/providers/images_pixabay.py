import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://pixabay.com/api/"
UA = "autovideo/0.1"


def relevant(hits: list[dict], query: str, exclude: set[str], prefix: str = "") -> list[dict]:
    """Hits whose tags match at least half the query words, best match first (ties keep Pixabay's order).
    Pixabay's own ranking happily returns a lizard for "deep blue ocean water"; tags are the sanity check."""
    words = [w.rstrip("s") for w in query.lower().split() if len(w) > 2] or [query.lower()]
    need = (len(words) + 1) // 2
    scored = []
    for h in hits:
        if f"{prefix}{h['id']}" in exclude:
            continue
        score = sum(w in h.get("tags", "").lower() for w in words)
        if score >= need:
            scored.append((-score, h))
    return [h for _, h in sorted(scored, key=lambda x: x[0])]


class PixabayImages:
    def __init__(self):
        self.key = os.getenv("PIXABAY_API_KEY")
        if not self.key:
            raise ValueError("ยังไม่ได้ใส่ PIXABAY_API_KEY ใน .env")

    def _get(self, url: str) -> bytes:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
            return r.read()

    def fetch(self, query: str, out: Path, exclude: set[str]) -> dict | None:
        qs = urllib.parse.urlencode({"key": self.key, "q": query[:100], "image_type": "photo",
                                     "orientation": "vertical", "safesearch": "true", "per_page": 50})
        hits = relevant(json.loads(self._get(f"{API}?{qs}"))["hits"], query, exclude)
        photo = hits[0] if hits else None
        if not photo:
            return None
        # Pixabay forbids hotlinking, so we download. largeImageURL is up to 1280px; render crops/scales to fit.
        out.write_bytes(self._get(photo["largeImageURL"]))
        return {"id": str(photo["id"]), "photographer": photo["user"], "url": photo["pageURL"]}

    def fetch_video(self, query: str, out: Path, exclude: set[str]) -> dict | None:
        """Save a short stock clip to `out` (mp4). Most Pixabay clips are landscape; render centre-crops them."""
        qs = urllib.parse.urlencode({"key": self.key, "q": query[:100], "video_type": "film",
                                     "safesearch": "true", "per_page": 50})
        for h in relevant(json.loads(self._get(f"{API}videos/?{qs}"))["hits"], query, exclude, prefix="v"):
            # Smallest file that is still tall enough to crop a sharp-ish 9:16 frame from.
            ok = [v for v in h["videos"].values() if v["url"] and v["height"] >= 1080 and v["size"] < 40_000_000]
            if ok:
                out.write_bytes(self._get(min(ok, key=lambda v: v["size"])["url"]))
                return {"id": f"v{h['id']}", "photographer": h["user"], "url": h["pageURL"]}
        return None

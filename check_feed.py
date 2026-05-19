import os
import json
import hashlib
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

# ── Config ────────────────────────────────────────────────────────────[...]
FEED_URL      = "https://warcomfeed.link/rss.xml"
WEBHOOK_URL   = os.environ["DISCORD_WEBHOOK_URL"]   # set in GitHub Actions secrets
SEEN_FILE     = "seen_articles.json"                 # persisted via GitHub Actions cache
MAX_POST      = 5                                    # max new articles to post per run
COOLDOWN_HOURS = 48                                  # don't repost same link within 48 hours

# ── Warhammer 40,000 filter ───────────────────────────────────────────────────
# The WarCom feed covers ALL Warhammer topics.
# We only want articles tagged/titled with 40K keywords.
FILTER_KEYWORDS = [
    "warhammer 40",
    "40,000",
    "40k",
    "space marine",
    "astartes",
    "chaos space",
    "necron",
    "ork",
    "eldar",
    "aeldari",
    "tyranid",
    "tau",
    "t'au",
    "imperial guard",
    "astra militarum",
    "adeptus mechanicus",
    "sisters of battle",
    "adepta sororitas",
    "dark angels",
    "ultramarines",
    "blood angels",
    "space wolves",
    "deathwatch",
    "grey knights",
    "inquisition",
    "kill team",
]

def load_seen() -> dict:
    """Load seen articles with timestamps. Returns {article_id: timestamp_iso}"""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return json.load(f)
    return {}

def save_seen(seen: dict):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=2)

def article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def is_within_cooldown(article_id: str, seen: dict) -> bool:
    """Check if article was posted within the last COOLDOWN_HOURS"""
    if article_id not in seen:
        return False
    
    try:
        posted_time = datetime.fromisoformat(seen[article_id])
        time_since_post = utcnow() - posted_time
        return time_since_post < timedelta(hours=COOLDOWN_HOURS)
    except (ValueError, TypeError):
        # Invalid timestamp format, treat as old post
        return False

def fetch_feed() -> list[dict]:
    with urllib.request.urlopen(FEED_URL, timeout=15) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    channel = root.find("channel")
    articles = []
    for item in channel.findall("item"):
        title       = (item.findtext("title") or "").strip()
        link        = (item.findtext("link")  or "").strip()
        description = (item.findtext("description") or "").strip()
        pub_date    = (item.findtext("pubDate") or "").strip()
        # Grab enclosure image if present
        enclosure = item.find("enclosure")
        image_url = enclosure.get("url") if enclosure is not None else None
        articles.append({
            "title":       title,
            "link":        link,
            "description": description,
            "pub_date":    pub_date,
            "image_url":   image_url,
        })
    return articles

def is_40k(article: dict) -> bool:
    haystack = (article["title"] + " " + article["description"]).lower()
    return any(kw in haystack for kw in FILTER_KEYWORDS)

def post_to_discord(article: dict):
    embed = {
        "title":       article["title"][:256],
        "url":         article["link"],
        "description": (article["description"] or "")[:300] + ("…" if len(article["description"]) > 300 else ""),
        "color":       0xAB0000,   # dark red — very 40K
        "footer":      {"text": "Warhammer Community • Warhammer 40,000"},
        "timestamp":   utcnow().isoformat(),
    }
    if article.get("image_url"):
        embed["image"] = {"url": article["image_url"]}

    payload = json.dumps({
        "username":   "WarCom Servo-Skull",
        "avatar_url": "https://warcomfeed.link/favicon.ico",
        "embeds":     [embed],
    }).encode()

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent":   "WarComServoSkull/1.0 (GitHub Actions)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {resp.status}")

def main():
    print(f"[{utcnow().isoformat()}] Fetching feed…")
    articles = fetch_feed()
    seen     = load_seen()
    
    # Filter: not in cooldown, not already posted forever, and is 40K
    new      = [
        a for a in articles 
        if not is_within_cooldown(article_id(a["link"]), seen) and is_40k(a)
    ]

    if not new:
        print("No new 40K articles.")
        return

    # Post oldest-first, cap at MAX_POST
    for article in reversed(new[:MAX_POST]):
        print(f"  Posting: {article['title']}")
        post_to_discord(article)
        seen[article_id(article["link"])] = utcnow().isoformat()

    save_seen(seen)
    print(f"Done. Posted {min(len(new), MAX_POST)} article(s).")

if __name__ == "__main__":
    main()

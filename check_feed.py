import os
import json
import hashlib
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
import time
import sys

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def log_message(message: str, level: str = "INFO"):
    """Log messages with timestamp"""
    timestamp = utcnow().isoformat()
    print(f"[{timestamp}] [{level}] {message}")
    sys.stdout.flush()

# ── Config ────────────────────────────────────────────────────────────[...]
FEED_URL      = "https://warcomfeed.link/rss.xml"
WEBHOOK_URL   = os.environ.get("DISCORD_WEBHOOK_URL", "")
SEEN_FILE     = "seen_articles.json"
FAILED_FILE   = "failed_articles.json"
CONFIG_FILE   = "config.json"
MAX_POST      = 5
COOLDOWN_HOURS = 48
MAX_RETRIES   = 3
RETRY_DELAY   = 2  # seconds
DISCORD_POST_DELAY = 0.5  # seconds between Discord posts to avoid rate limiting
MAX_POST_FAILURES = 3  # Mark article as permanently failed after this many attempts

# Default configuration
DEFAULT_CONFIG = {
    "max_post": MAX_POST,
    "cooldown_hours": COOLDOWN_HOURS,
    "filter_keywords": [
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
        "chaos knights",
        "custodes",
        "adeptus custodes",
    ]
}

def load_config() -> dict:
    """Load configuration from config.json or use defaults"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
            log_message(f"Loaded configuration from {CONFIG_FILE}")
            return config
        except Exception as e:
            log_message(f"Failed to load config file: {e}", "WARNING")
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def load_seen() -> dict:
    """Load seen articles with timestamps. Returns {article_id: timestamp_iso}"""
    if not os.path.exists(SEEN_FILE):
        return {}
    
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
        
        # Handle backward compatibility: convert old list format to dict format
        if isinstance(data, list):
            log_message("Converting old list format to dict format", "INFO")
            return {article_id: utcnow().isoformat() for article_id in data}
        
        # New format: dict with {article_id: timestamp_iso}
        return data
    except Exception as e:
        log_message(f"Error loading seen articles: {e}", "ERROR")
        return {}

def load_failed() -> dict:
    """Load failed articles with failure counts. Returns {article_id: failure_count}"""
    if not os.path.exists(FAILED_FILE):
        return {}
    
    try:
        with open(FAILED_FILE) as f:
            return json.load(f)
    except Exception as e:
        log_message(f"Error loading failed articles: {e}", "WARNING")
        return {}

def save_seen(seen: dict):
    """Save seen articles to file"""
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(seen, f, indent=2)
        log_message(f"Saved {len(seen)} articles to {SEEN_FILE}")
    except Exception as e:
        log_message(f"Error saving seen articles: {e}", "ERROR")
        raise

def save_failed(failed: dict):
    """Save failed articles to file"""
    try:
        with open(FAILED_FILE, "w") as f:
            json.dump(failed, f, indent=2)
        if failed:
            log_message(f"Saved {len(failed)} failed articles to {FAILED_FILE}")
    except Exception as e:
        log_message(f"Error saving failed articles: {e}", "ERROR")

def article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def is_within_cooldown(article_id: str, seen: dict, cooldown_hours: int) -> bool:
    """Check if article was posted within the last cooldown_hours"""
    if article_id not in seen:
        return False
    
    try:
        posted_time = datetime.fromisoformat(seen[article_id])
        time_since_post = utcnow() - posted_time
        return time_since_post < timedelta(hours=cooldown_hours)
    except (ValueError, TypeError):
        # Invalid timestamp format, treat as old post
        return False

def fetch_feed(retries: int = MAX_RETRIES) -> list[dict]:
    """Fetch RSS feed with retry logic"""
    for attempt in range(retries):
        try:
            log_message(f"Fetching feed (attempt {attempt + 1}/{retries})…")
            with urllib.request.urlopen(FEED_URL, timeout=15) as resp:
                raw = resp.read()
            
            # Validate XML before parsing
            try:
                root = ET.fromstring(raw)
            except ET.ParseError as e:
                log_message(f"Invalid XML in feed: {e}", "ERROR")
                raise
            
            channel = root.find("channel")
            if channel is None:
                log_message("Feed missing <channel> element", "ERROR")
                raise ValueError("Feed missing <channel> element")
            
            articles = []
            for item in channel.findall("item"):
                title       = (item.findtext("title") or "").strip()
                link        = (item.findtext("link")  or "").strip()
                description = (item.findtext("description") or "").strip()
                pub_date    = (item.findtext("pubDate") or "").strip()
                # Grab enclosure image if present
                enclosure = item.find("enclosure")
                image_url = enclosure.get("url") if enclosure is not None else None
                
                # Skip articles with missing critical fields
                if not link or not title:
                    log_message(f"Skipping article with missing link or title", "WARNING")
                    continue
                
                articles.append({
                    "title":       title,
                    "link":        link,
                    "description": description,
                    "pub_date":    pub_date,
                    "image_url":   image_url,
                })
            
            log_message(f"Successfully fetched {len(articles)} articles from feed")
            return articles
        
        except urllib.error.URLError as e:
            log_message(f"Network error fetching feed: {e}", "ERROR")
            if attempt < retries - 1:
                log_message(f"Retrying in {RETRY_DELAY} seconds…", "WARNING")
                time.sleep(RETRY_DELAY)
            else:
                log_message("Max retries reached. Aborting.", "ERROR")
                raise
        except Exception as e:
            log_message(f"Error parsing feed: {e}", "ERROR")
            if attempt < retries - 1:
                log_message(f"Retrying in {RETRY_DELAY} seconds…", "WARNING")
                time.sleep(RETRY_DELAY)
            else:
                raise

def is_40k(article: dict, keywords: list) -> bool:
    haystack = (article["title"] + " " + article["description"]).lower()
    return any(kw in haystack for kw in keywords)

def post_to_discord(article: dict, retries: int = MAX_RETRIES):
    """Post to Discord with retry logic"""
    if not WEBHOOK_URL:
        log_message("Discord webhook URL not set. Skipping post.", "WARNING")
        return
    
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
    
    last_error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status not in (200, 204):
                    raise RuntimeError(f"Discord returned HTTP {resp.status}")
            log_message(f"Successfully posted to Discord: {article['title'][:50]}…")
            return
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429:
                # Rate limited — back off exponentially
                backoff = RETRY_DELAY * (2 ** attempt)
                log_message(f"Rate limited by Discord. Backing off {backoff}s…", "WARNING")
                time.sleep(backoff)
            elif attempt < retries - 1:
                log_message(f"HTTP error {e.code} posting to Discord: {e}", "WARNING")
                time.sleep(RETRY_DELAY)
            else:
                log_message(f"Max retries reached. HTTP {e.code}", "ERROR")
        except urllib.error.URLError as e:
            last_error = e
            log_message(f"Network error posting to Discord: {e}", "ERROR")
            if attempt < retries - 1:
                log_message(f"Retrying in {RETRY_DELAY} seconds…", "WARNING")
                time.sleep(RETRY_DELAY)
            else:
                log_message("Max retries reached. Skipping post.", "ERROR")
        except Exception as e:
            last_error = e
            log_message(f"Error posting to Discord: {e}", "ERROR")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                log_message("Max retries reached after exception.", "ERROR")
    
    # All retries failed
    if last_error:
        raise last_error
    raise RuntimeError("Failed to post to Discord: unknown error")

def main():
    try:
        log_message("=== Warhammer 40K Article Notifier Started ===")
        
        # Load configuration and tracking files
        config = load_config()
        cooldown_hours = config.get("cooldown_hours", COOLDOWN_HOURS)
        max_post = config.get("max_post", MAX_POST)
        keywords = config.get("filter_keywords", DEFAULT_CONFIG["filter_keywords"])
        
        # Fetch and process
        articles = fetch_feed()
        seen = load_seen()
        failed = load_failed()
        
        # Filter: not seen before, not permanently failed, AND is 40K
        new = [
            a for a in articles 
            if article_id(a["link"]) not in seen 
            and article_id(a["link"]) not in failed
            and is_40k(a, keywords)
        ]
        
        log_message(f"Found {len(new)} new 40K articles (out of {len(articles)} total)")
        
        # Deduplicate within this run (in case feed has duplicates)
        seen_in_run = set()
        deduplicated = []
        for article in new:
            aid = article_id(article["link"])
            if aid not in seen_in_run:
                deduplicated.append(article)
                seen_in_run.add(aid)
            else:
                log_message(f"Skipping duplicate in feed: {article['title'][:50]}…")
        
        log_message(f"After deduplication: {len(deduplicated)} unique articles")
        
        if not deduplicated:
            log_message("No new 40K articles to post.")
            return
        
        # Post oldest-first, cap at max_post, with rate limiting
        posted_count = 0
        for i, article in enumerate(reversed(deduplicated[:max_post])):
            aid = article_id(article["link"])
            try:
                log_message(f"Posting: {article['title'][:80]}…")
                post_to_discord(article)
                seen[aid] = utcnow().isoformat()
                posted_count += 1
                
                # Rate limiting: add delay between posts (except after the last one)
                if i < max_post - 1:
                    time.sleep(DISCORD_POST_DELAY)
            
            except Exception as e:
                log_message(f"Failed to post article: {e}", "ERROR")
                
                # Track failure count
                if aid not in failed:
                    failed[aid] = 0
                failed[aid] += 1
                
                if failed[aid] >= MAX_POST_FAILURES:
                    log_message(
                        f"Article failed {failed[aid]} times. Marking as permanently failed: {article['title'][:50]}…",
                        "WARNING"
                    )
                    seen[aid] = utcnow().isoformat()  # Mark as seen so we don't try again
                else:
                    log_message(
                        f"Attempt {failed[aid]}/{MAX_POST_FAILURES}. Will retry next run.",
                        "INFO"
                    )
        
        save_seen(seen)
        save_failed(failed)
        log_message(f"=== Completed: Posted {posted_count} article(s) ===")
    
    except Exception as e:
        log_message(f"Fatal error: {e}", "ERROR")
        # Attempt to send error notification to Discord
        try:
            post_error_to_discord(str(e))
        except:
            pass
        sys.exit(1)

def post_error_to_discord(error_message: str):
    """Send error notification to Discord"""
    if not WEBHOOK_URL:
        return
    
    embed = {
        "title": "❌ Warhammer 40K Notifier Error",
        "description": error_message[:500],
        "color": 0xFF0000,  # red
        "footer": {"text": "Warhammer Community • Warhammer 40,000"},
        "timestamp": utcnow().isoformat(),
    }
    
    payload = json.dumps({
        "username": "WarCom Servo-Skull",
        "avatar_url": "https://warcomfeed.link/favicon.ico",
        "embeds": [embed],
    }).encode()
    
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "WarComServoSkull/1.0 (GitHub Actions)",
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                log_message(f"Failed to send error notification: HTTP {resp.status}", "ERROR")
    except Exception as e:
        log_message(f"Failed to send error notification: {e}", "ERROR")

if __name__ == "__main__":
    main()

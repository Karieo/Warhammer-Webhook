import os
import json
import hashlib
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
from datetime import datetime, timezone
import time
import sys
import re

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def log_message(message: str, level: str = "INFO"):
    """Log messages with timestamp"""
    timestamp = utcnow().isoformat()
    print(f"[{timestamp}] [{level}] {message}")
    sys.stdout.flush()

# ── Config ────────────────────────────────────────────────────────────
WEBHOOK_URL        = os.environ.get("DISCORD_WEBHOOK_URL", "")
SEEN_FILE          = "seen_articles.json"
FAILED_FILE        = "failed_articles.json"
CONFIG_FILE        = "config.json"
MAX_RETRIES        = 3
RETRY_DELAY        = 2  # seconds
DISCORD_POST_DELAY = 0.5  # seconds between Discord posts to avoid rate limiting
MAX_POST_FAILURES  = 3  # Mark article as permanently failed after this many attempts

# Default configuration
DEFAULT_CONFIG = {
    "feed_url": "https://warcomfeed.link/rss.xml",
    "max_post": 5,
    "check_interval_minutes": 60,
    "embed": {
        "author_name": "RSS Feed",
        "author_url": None,
        "avatar_url": None,
        "color": "0x1f77b4",
        "footer_text": "RSS Feed"
    },
    "filter": {
        "enabled": True,
        "mode": "any",
        "keywords": [],
        "exclude_keywords": [],
        "include_only": [],
        "exclude_patterns": []
    }
}

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def load_config() -> dict:
    """Load configuration from config.json or use defaults"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
            log_message(f"Loaded configuration from {CONFIG_FILE}")
            # Deep-merge so nested keys like filter.* and embed.* keep their defaults
            return _deep_merge(DEFAULT_CONFIG, config)
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
    """Generate unique ID for article based on URL"""
    return hashlib.md5(url.encode()).hexdigest()

def fetch_feed(feed_url: str, retries: int = MAX_RETRIES) -> list[dict]:
    """Fetch RSS feed with retry logic"""
    for attempt in range(retries):
        try:
            log_message(f"Fetching feed (attempt {attempt + 1}/{retries})…")
            with urllib.request.urlopen(feed_url, timeout=15) as resp:
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
                
                # Skip articles with missing critical fields
                if not link or not title:
                    log_message(f"Skipping article with missing link or title", "WARNING")
                    continue
                
                # Grab enclosure image if present
                enclosure = item.find("enclosure")
                image_url = enclosure.get("url") if enclosure is not None else None
                
                articles.append({
                    "title":       title,
                    "link":        link,
                    "description": description,
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

def matches_filter(article: dict, filter_config: dict) -> bool:
    """Check if article passes filter rules"""
    if not filter_config.get("enabled", True):
        return True
    
    haystack = (article["title"] + " " + article["description"]).lower()
    
    # Check exclude_patterns (regex)
    exclude_patterns = filter_config.get("exclude_patterns", [])
    for pattern in exclude_patterns:
        try:
            if re.search(pattern, haystack, re.IGNORECASE):
                return False
        except re.error as e:
            log_message(f"Invalid regex pattern '{pattern}': {e}", "WARNING")
    
    # Check exclude_keywords
    exclude_keywords = filter_config.get("exclude_keywords", [])
    for kw in exclude_keywords:
        if kw.lower() in haystack:
            return False
    
    # Check include_only (if set, ONLY these patterns match)
    include_only = filter_config.get("include_only", [])
    if include_only:
        for pattern in include_only:
            try:
                if re.search(pattern, haystack, re.IGNORECASE):
                    return True
            except re.error as e:
                log_message(f"Invalid regex pattern '{pattern}': {e}", "WARNING")
        return False
    
    # Check keywords (mode: "any" or "all")
    keywords = filter_config.get("keywords", [])
    if not keywords:
        return True
    
    mode = filter_config.get("mode", "any")
    
    if mode == "all":
        return all(kw.lower() in haystack for kw in keywords)
    else:  # mode == "any"
        return any(kw.lower() in haystack for kw in keywords)

def parse_color(color_str: str) -> int:
    """Parse hex color string to integer"""
    try:
        # Handle both "0xFF0000" and "#FF0000" formats
        if isinstance(color_str, str):
            color_str = color_str.strip()
            if color_str.startswith("0x") or color_str.startswith("0X"):
                return int(color_str, 16)
            elif color_str.startswith("#"):
                return int(color_str[1:], 16)
            else:
                return int(color_str, 16)
        return int(color_str)
    except (ValueError, TypeError):
        log_message(f"Invalid color '{color_str}', using default", "WARNING")
        return 0x1f77b4

def post_to_discord(article: dict, config: dict, retries: int = MAX_RETRIES):
    """Post article to Discord with retry logic"""
    if not WEBHOOK_URL:
        log_message("Discord webhook URL not set. Skipping post.", "WARNING")
        return
    
    embed_config = config.get("embed", DEFAULT_CONFIG["embed"])
    
    embed = {
        "title":       article["title"][:256],
        "url":         article["link"],
        "description": (article["description"] or "")[:300] + ("…" if len(article.get("description", "")) > 300 else ""),
        "color":       parse_color(embed_config.get("color", "0x1f77b4")),
        "timestamp":   utcnow().isoformat(),
    }
    
    # Add author if configured
    if embed_config.get("author_name"):
        embed["author"] = {"name": embed_config["author_name"]}
        if embed_config.get("author_url"):
            embed["author"]["url"] = embed_config["author_url"]
    
    # Add footer if configured
    if embed_config.get("footer_text"):
        embed["footer"] = {"text": embed_config["footer_text"]}
    
    # Add image if present
    if article.get("image_url"):
        embed["image"] = {"url": article["image_url"]}

    payload = json.dumps({
        "username":   embed_config.get("author_name", "RSS Feed Notifier"),
        "avatar_url": embed_config.get("avatar_url"),
        "embeds":     [embed],
    }).encode()

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent":   "RSS-Discord-Notifier/1.0 (GitHub Actions)",
        },
        method="POST",
    )
    
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status not in (200, 204):
                    raise RuntimeError(f"Discord returned HTTP {resp.status}")
            log_message(f"Successfully posted to Discord: {article['title'][:50]}…")
            return
        except urllib.error.HTTPError as e:
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
                raise
        except urllib.error.URLError as e:
            log_message(f"Network error posting to Discord: {e}", "ERROR")
            if attempt < retries - 1:
                log_message(f"Retrying in {RETRY_DELAY} seconds…", "WARNING")
                time.sleep(RETRY_DELAY)
            else:
                raise
        except Exception as e:
            log_message(f"Error posting to Discord: {e}", "ERROR")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise

def main():
    """Main function to fetch feed, filter articles, and post to Discord"""
    try:
        log_message("=== RSS Discord Notifier Started ===")
        
        # Load configuration and tracking files
        config = load_config()
        feed_url = config.get("feed_url")
        
        if not feed_url:
            log_message("Feed URL not configured in config.json", "ERROR")
            sys.exit(1)
        
        max_post = config.get("max_post", 5)
        filter_config = config.get("filter", DEFAULT_CONFIG["filter"])
        
        # Fetch and process articles
        articles = fetch_feed(feed_url)
        seen = load_seen()
        failed = load_failed()
        
        # Filter: not seen before, not permanently failed, AND passes filter
        new = [
            a for a in articles 
            if article_id(a["link"]) not in seen 
            and article_id(a["link"]) not in failed
            and matches_filter(a, filter_config)
        ]
        
        log_message(f"Found {len(new)} new articles (out of {len(articles)} total)")
        
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
            log_message("No new articles to post.")
            return
        
        # Post oldest-first, cap at max_post, with rate limiting
        posted_count = 0
        to_post = list(reversed(deduplicated[:max_post]))
        for i, article in enumerate(to_post):
            aid = article_id(article["link"])
            try:
                log_message(f"Posting: {article['title'][:80]}…")
                post_to_discord(article, config)
                seen[aid] = utcnow().isoformat()
                posted_count += 1
                
                # Rate limiting: add delay between posts (except after the last one)
                if i < len(to_post) - 1:
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
                    seen[aid] = utcnow().isoformat()
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
        try:
            post_error_to_discord(config, str(e))
        except:
            pass
        sys.exit(1)

def post_error_to_discord(config: dict, error_message: str):
    """Send error notification to Discord"""
    if not WEBHOOK_URL:
        return
    
    embed_config = config.get("embed", DEFAULT_CONFIG["embed"])
    
    embed = {
        "title": "❌ RSS Notifier Error",
        "description": error_message[:500],
        "color": 0xFF0000,
        "timestamp": utcnow().isoformat(),
    }
    
    if embed_config.get("footer_text"):
        embed["footer"] = {"text": embed_config["footer_text"]}
    
    payload = json.dumps({
        "username": embed_config.get("author_name", "RSS Feed Notifier"),
        "avatar_url": embed_config.get("avatar_url"),
        "embeds": [embed],
    }).encode()
    
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "RSS-Discord-Notifier/1.0 (GitHub Actions)",
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

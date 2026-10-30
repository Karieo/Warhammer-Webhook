"""Read public Warhammer Community page data without executing its JavaScript."""
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit

OFFICIAL_HOST = 'www.warhammer-community.com'
ALLOWED_SOURCES = {
    'https://www.warhammer-community.com/en-gb/',
    'https://www.warhammer-community.com/en-gb/setting/warhammer-40000/',
    'https://www.warhammer-community.com/en-gb/setting/kill-team/',
}

class SourceError(ValueError):
    """Source failed validation; do not silently report an empty successful run."""


def canonical_article_url(url):
    p = urlsplit(url)
    if p.scheme == 'https' and p.netloc == OFFICIAL_HOST:
        path = re.sub(r'^/en-gb(?=/articles/)', '', p.path).rstrip('/')
        if re.fullmatch(r'/articles/[a-zA-Z0-9]+/[^/]+', path):
            return 'https://' + OFFICIAL_HOST + path
    return url


class ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.parts = None
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.parts = []
    def handle_data(self, data):
        if self.parts is not None:
            self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == 'script' and self.parts is not None:
            self.scripts.append(''.join(self.parts))
            self.parts = None


def parse_official_page(html):
    parser = ScriptCollector()
    parser.feed(html)
    # Next Flight text may be split across script tags. Decode its JSON transport,
    # concatenate text chunks, then read JSON records; never eval JavaScript.
    chunks = []
    for script in parser.scripts:
        match = re.fullmatch(r'\s*self\.__next_f\.push\((.*)\)\s*;?\s*', script, re.S)
        if match:
            try:
                payload = json.loads(match[1])
                if isinstance(payload, list) and len(payload) == 2 and payload[0] == 1 and isinstance(payload[1], str):
                    chunks.append(payload[1])
            except (ValueError, TypeError):
                continue
    articles = {}
    def visit(node):
        if isinstance(node, dict):
            if node.get('collection') == 'articles' and node.get('site') == 'en-gb':
                uri, title, date = node.get('uri'), node.get('title'), node.get('date_universal')
                if not isinstance(uri, str) or not re.fullmatch(r'/articles/[a-zA-Z0-9]+/[^/?#]+/?', uri):
                    raise SourceError('Invalid official article URI')
                if not isinstance(title, str) or not title.strip():
                    raise SourceError('Official article missing title')
                try:
                    published = datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    raise SourceError('Official article missing valid publication date')
                link = canonical_article_url('https://' + OFFICIAL_HOST + uri)
                articles[link] = {'title': title.strip(), 'link': link,
                    'description': node.get('excerpt') or '', 'image_url': None,
                    'published_at': published.isoformat()}
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    stream = ''.join(chunks)
    decoder = json.JSONDecoder()
    for match in re.finditer(r'(?:^|\n)[0-9a-f]+:', stream):
        try:
            node, _ = decoder.raw_decode(stream[match.end():])
        except ValueError:
            continue
        visit(node)
    if not articles:
        raise SourceError('Official page returned no dated article records; layout may have changed')
    return list(articles.values())


def fetch_official(config, now):
    urls = config.get('official_urls', [])
    if not urls or any(url not in ALLOWED_SOURCES for url in urls):
        raise SourceError('Configure approved official news page URLs')
    articles = {}
    for url in urls:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Warhammer-News-Notifier/2.0'})
                with urllib.request.urlopen(req, timeout=20) as response:
                    if urlsplit(response.geturl()).netloc != OFFICIAL_HOST:
                        raise SourceError('Official source redirected to unexpected host')
                    raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise SourceError('Official page exceeds size limit')
                page_articles = parse_official_page(raw.decode('utf-8'))
                newest = max(datetime.fromisoformat(a['published_at']) for a in page_articles)
                if newest < now - timedelta(days=config.get('source_max_age_days', 7)):
                    message = f"Official page may be stale or quiet: {url}; newest article {newest.date().isoformat()}"
                    print("WARNING: " + message)
                    if os.environ.get('GITHUB_ACTIONS') == 'true':
                        print("::warning::" + message)
                for article in page_articles:
                    articles[article['link']] = article
                break
            except SourceError:
                raise
            except (OSError, ValueError) as exc:
                if attempt == 2:
                    raise SourceError('Could not read official news source') from exc
                time.sleep(2 * (attempt + 1))
    ordered = sorted(articles.values(), key=lambda a: (a['published_at'], a['link']), reverse=True)
    dates = [datetime.fromisoformat(a['published_at']) for a in ordered]
    if any(d > now + timedelta(days=1) for d in dates):
        raise SourceError('Official source contains implausible future publication dates')
    if max(dates) < now - timedelta(days=config.get('source_max_age_days', 7)):
        raise SourceError('Official news source is stale: newest article ' + max(dates).date().isoformat())
    return ordered


def recent_articles(articles, config, now):
    cutoff = now - timedelta(days=config.get('max_article_age_days', 3))
    # A rollout floor prevents pre-fix history from being replayed. It is not a
    # delivery record; old items are skipped without marking them as delivered.
    floor = config.get('not_before')
    if floor:
        cutoff = max(cutoff, datetime.strptime(floor, '%Y-%m-%d').replace(tzinfo=timezone.utc))
    return [a for a in articles if datetime.fromisoformat(a['published_at']) >= cutoff]

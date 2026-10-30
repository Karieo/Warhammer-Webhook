# Generic RSS Discord Webhook Notifier

Posts articles from any RSS feed to a Discord channel — automatically and for free via GitHub Actions.

---

## How it works

1. GitHub Actions runs `check_feed.py` on a configurable schedule (default: hourly)
2. The script fetches your RSS feed
3. It filters articles based on your configuration
4. New articles get posted to your Discord channel as rich embeds
5. `seen_articles.json` tracks what's been posted so nothing is duplicated

---

## Setup (5 minutes)

### 1. Create a Discord Webhook

1. Open your Discord server → right-click the channel → **Edit Channel**
2. Go to **Integrations** → **Webhooks** → **New Webhook**
3. Give it a name, copy the **Webhook URL**

### 2. Create a GitHub Repository

1. Go to [github.com](https://github.com) → **New repository** (can be private)
2. Upload these files maintaining the folder structure:
   ```
   check_feed.py
   config.json
   .github/
     workflows/
       rss-notifier.yml
   ```

### 3. Add the Webhook URL as a Secret

1. In your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `DISCORD_WEBHOOK_URL`
4. Value: paste your Discord webhook URL
5. Click **Add secret**

### 4. Configure Your Feed

Edit `config.json` to specify your RSS feed and customize the output:

```json
{
  "feed_url": "https://example.com/feed.xml",
  "max_post": 5,
  "embed": {
    "author_name": "My Feed",
    "avatar_url": "https://example.com/icon.png",
    "color": "0xFF5733",
    "footer_text": "Powered by RSS"
  },
  "filter": {
    "enabled": true,
    "mode": "any",
    "keywords": ["python", "javascript"],
    "exclude_keywords": ["spam"],
    "exclude_patterns": ["crypto|nft"]
  }
}
```

### 5. Enable Actions & Test

1. Go to the **Actions** tab in your repo
2. Click **RSS Discord Notifier** → **Run workflow** to test it immediately
3. Check your Discord channel — you should see articles appear!

After that it runs automatically on your configured schedule. 🎉

---

## Configuration Reference

### Core Settings

- **`feed_url`** (string): URL of your RSS feed
- **`max_post`** (integer): Maximum articles to post per run (default: `5`)
- **`check_interval_minutes`** (integer): How often to check (informational; edit the cron in the workflow file to change)

### Embed Customization

Under `embed`:
- **`author_name`** (string): Name shown in the embed header
- **`author_url`** (string or null): Optional URL for the author name
- **`avatar_url`** (string or null): Optional avatar/icon URL
- **`color`** (string): Hex color code (`"0xFF0000"`, `"#FF0000"`, or `"16711680"`)
- **`footer_text`** (string): Text shown in the embed footer

### Advanced Filtering

Under `filter`:

- **`enabled`** (boolean): Set to `false` to post all articles without filtering
- **`mode`** (string): How to match keywords
  - `"any"`: Post if article contains ANY keyword (OR logic)
  - `"all"`: Post only if article contains ALL keywords (AND logic)
  
- **`keywords`** (array): Strings to search for in title + description
  ```json
  "keywords": ["python", "javascript", "typescript"]
  ```

- **`exclude_keywords`** (array): Articles containing these are skipped (blacklist)
  ```json
  "exclude_keywords": ["spam", "crypto"]
  ```

- **`include_only`** (array): Regex patterns — ONLY articles matching these are posted (overrides keywords)
  ```json
  "include_only": ["^Breaking:", "\\[URGENT\\]"]
  ```

- **`exclude_patterns`** (array): Regex patterns — articles matching these are skipped
  ```json
  "exclude_patterns": ["cryptocurrency|NFT|blockchain"]
  ```

---

## Examples

### Post articles about Python OR JavaScript, but never crypto

```json
{
  "feed_url": "https://news.ycombinator.com/rss",
  "filter": {
    "enabled": true,
    "mode": "any",
    "keywords": ["python", "javascript"],
    "exclude_keywords": ["crypto", "bitcoin"]
  }
}
```

### Post only breaking news

```json
{
  "feed_url": "https://feeds.reuters.com/reuters/newsOne",
  "filter": {
    "enabled": true,
    "include_only": ["BREAKING:", "\\[URGENT\\]"]
  }
}
```

### Post everything (no filtering)

```json
{
  "filter": {
    "enabled": false
  }
}
```

### Post with custom branding

```json
{
  "embed": {
    "author_name": "Tech News Daily",
    "avatar_url": "https://example.com/logo.png",
    "color": "0x2196F3",
    "footer_text": "Subscribe to Tech News Daily"
  }
}
```

---

## Changing the Check Frequency

Edit the `cron` line in `.github/workflows/rss-notifier.yml`:

```yaml
- cron: "0 * * * *"    # every hour (default)
- cron: "*/30 * * * *" # every 30 minutes
- cron: "0 9 * * *"    # once a day at 9am UTC
- cron: "0 9,21 * * *" # twice a day (9am & 9pm UTC)
```

[Cron syntax reference](https://crontab.guru/)

---

## Notes

- Uses only Python standard library — no `pip install` needed
- GitHub Actions free tier gives 2,000 minutes/month; this script uses ~1 min/run, so daily checks are well within limits
- Configuration is loaded from `config.json` on each run; no restart needed
- `seen_articles.json` and `failed_articles.json` persist across runs via git commits
- Failed articles are automatically retried on subsequent runs (up to 3 attempts before being marked permanent)


## Offline regression tests and delivery state

Run `python -m unittest discover -s tests -v` before publishing changes. The suite
uses synthetic articles and mocked HTTP/state helpers; it sends no Discord
messages and does not edit the committed tracking files. The scheduled workflow
also runs this gate before checking the feed.

- A missing/blank `DISCORD_WEBHOOK_URL` fails before feed or delivery-state processing.
- An article enters `seen_articles.json` only after a successful webhook response.
- Exhausted HTTP 429/network/server-error retries count as a failed delivery,
  not a successful post. Each article remains eligible on later runs until
  `MAX_POST_FAILURES` (currently three failed runs). Each run can attempt the
  HTTP request up to `MAX_RETRIES` times (currently three).
- Successful retries clear the failure counter. Terminal failures remain in
  `failed_articles.json` at the limit rather than being labeled delivered.
- Assuming the source feed is newest-first, the oldest eligible entries are
  processed first, up to `max_post`. The configured keyword/filter rules and
  existing seen history still apply.

Historical seen entries are not automatically replayed: some may have been
marked seen by the earlier failure-handling bug, but code alone cannot determine
which were actually delivered. Any recovery of historical notifications should
be reviewed separately to avoid duplicate messages. Likewise, manually retrying
a terminal failure requires deliberate removal/reset of its failure record.

Delivery is not exactly-once: a Discord success followed by a local/state-push
failure can cause a later duplicate, and a request whose response is lost may
have reached Discord. Per-article delivery failures remain logged and persisted
without aborting the batch. The final log reports posted/failed counts, and GitHub
Actions receives a warning annotation when any article fails. This preserves the
state-commit step; workflow success alone is still not a delivery receipt.

## Official-source recovery (prepared October 30, 2026)

The unofficial `warcomfeed.link` RSS stopped advancing on September 11. The
configured source now reads public article metadata embedded in the official
Warhammer Community homepage, Warhammer 40,000 page, and Kill Team page. No
JavaScript is executed. The existing keyword filter still applies; this is not
an exhaustive crawl of every historical article or an official RSS service.

- `official_source.py` validates English article URLs, titles and publication
  dates. Empty, invalid, unavailable, unexpectedly redirected or stale sources
  fail the run visibly instead of silently returning “nothing new”.
- `source_max_age_days: 7` checks the newest article across the three pages.
  Each individual page also warns when its latest article is older than seven
  days, even if another page is fresh; a quiet category does not abort the batch.
  Missing, invalid or unrecognized source configuration also fails closed. A stale/parse failure does **not** send repeated error
  posts into Discord; GitHub Actions displays a failed run/error annotation.
- `max_article_age_days: 3`, `not_before: "2026-10-28"`, and `max_post: 2`
  deliberately limit catch-up. Older items are skipped, **not** marked delivered.
  After a long outage, older missed articles are not automatically replayed.
  Retry candidates also age out after three days; failed counts remain intact
  for deliberate review rather than automatically requeueing old news.
- Identity normalizes official `/en-gb/articles/.../` URLs to the original
  nonlocalized, no-trailing-slash form before hashing, preserving existing seen
  IDs. No committed history reset or migration is required.
- A network/source failure leaves delivery tracking untouched. Existing bounded
  Discord retries and confirmed-success-only seen tracking remain in effect.
- Images are omitted from these new-source embeds rather than guessing asset URLs.

### Verify without posting

```sh
python -m unittest discover -s tests -v
python check_feed.py --dry-run
```

Dry-run needs no Discord secret and performs only public source reads, local
tracking reads and candidate logging. It never calls Discord or writes tracking
files. Fixtures are saved official-page article-data scripts fetched October 30,
2026; they exercise the actual transport/metadata format. The adapter will fail
closed if the upstream format changes.

### Release boundary

This patch is prepared for review only. Publishing a draft PR and merging it are
separate authorization steps. Merging changes `config.json` and therefore makes
the **next existing scheduled run** use the new source and post up to two eligible
articles. No manual workflow dispatch, test Discord message, secret change or
history reset is needed. Before approval, review the dry-run candidates and
confirm the bounded catch-up policy. After an approved release, inspect the
natural run’s real posting count and ask Clay to confirm arrival in the intended
channel; a passing test or dry run does not prove webhook validity/destination.

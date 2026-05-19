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

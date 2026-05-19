# Warhammer 40K Discord Notifier

Posts new Warhammer 40,000 articles from [Warhammer Community](https://www.warhammer-community.com/en-gb/topics/warhammer-40000/) to a Discord channel — automatically, every hour, for free via GitHub Actions.

---

## How it works

1. GitHub Actions runs `check_feed.py` once per hour
2. The script fetches the [WarCom Feed RSS](https://warcomfeed.link/) (an unofficial feed that updates hourly)
3. It filters articles for Warhammer 40K keywords (configured in `config.json`)
4. Any new articles get posted to your Discord channel as a rich embed
5. `seen_articles.json` tracks what's been posted so nothing is duplicated

---

## Setup (5 minutes)

### 1. Create a Discord Webhook

1. Open your Discord server → right-click the channel → **Edit Channel**
2. Go to **Integrations** → **Webhooks** → **New Webhook**
3. Give it a name (e.g. `WarCom Servo-Skull`), copy the **Webhook URL**

### 2. Create a GitHub Repository

1. Go to [github.com](https://github.com) → **New repository** (can be private)
2. Upload these files maintaining the folder structure:
   ```
   check_feed.py
   config.json
   .github/
     workflows/
       warhammer-notifier.yml
   ```

### 3. Add the Webhook URL as a Secret

1. In your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `DISCORD_WEBHOOK_URL`
4. Value: paste your Discord webhook URL
5. Click **Add secret**

### 4. Enable Actions & Test

1. Go to the **Actions** tab in your repo
2. Click **Warhammer 40K Article Notifier** → **Run workflow** to test it immediately
3. Check your Discord channel — you should see recent 40K articles appear!

After that it runs automatically every hour. 🎉

---

## Customisation

### Master Configuration File (`config.json`)

The `config.json` file is the central configuration hub for all settings:

```json
{
  "max_post": 5,
  "filter_keywords": [
    "warhammer 40",
    "40k",
    "space marine",
    ...
  ]
}
```

**Settings:**
- **`max_post`** (integer): Maximum number of articles to post per run (default: `5`)
- **`filter_keywords`** (array): List of keywords to match against article titles and descriptions. Articles must contain at least one keyword to be posted. Leave empty and modify the `is_40k()` function in `check_feed.py` to post all articles.

Simply edit `config.json` in your repository to customize behavior without touching the Python code.

### Change the check frequency

Edit the `cron` line in `.github/workflows/warhammer-notifier.yml`:
```yaml
- cron: "0 * * * *"    # every hour (default)
- cron: "*/30 * * * *" # every 30 minutes
- cron: "0 9 * * *"    # once a day at 9am UTC
```

### Change the 40K keyword filter

Edit the `filter_keywords` array in `config.json` to add/remove terms.

To post **all** Warhammer articles regardless of topic:
1. Set `"filter_keywords": []` in `config.json`
2. Edit `check_feed.py` and modify the `is_40k()` function to always return `True`

### Change the embed colour

Edit the `"color"` hex value in `post_to_discord()` inside `check_feed.py` (line ~212).

---

## Notes

- Uses only Python standard library — no `pip install` needed
- The WarCom Feed is unofficial but well-maintained; all content belongs to Warhammer Community / Games Workshop
- GitHub Actions free tier gives 2,000 minutes/month — this workflow uses ~1 min/run × 24 runs/day = ~720 min/month, well within the limit
- Configuration is loaded from `config.json` on each run; no restart needed for changes to take effect

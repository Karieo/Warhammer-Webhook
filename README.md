# Warhammer 40K Discord Notifier

Posts new Warhammer 40,000 articles from [Warhammer Community](https://www.warhammer-community.com/en-gb/topics/warhammer-40000/) to a Discord channel — automatically, every hour, for free via GitHub Actions.

---

## How it works

1. GitHub Actions runs `check_feed.py` once per hour
2. The script fetches the [WarCom Feed RSS](https://warcomfeed.link/) (an unofficial feed that updates hourly)
3. It filters articles for Warhammer 40K keywords
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

### Change the check frequency

Edit the `cron` line in `.github/workflows/warhammer-notifier.yml`:
```yaml
- cron: "0 * * * *"    # every hour (default)
- cron: "*/30 * * * *" # every 30 minutes
- cron: "0 9 * * *"    # once a day at 9am UTC
```

### Change the 40K keyword filter

Edit the `FILTER_KEYWORDS` list in `check_feed.py` to add/remove terms.
Set `FILTER_KEYWORDS = []` and change `is_40k()` to always return `True` to get **all** Warhammer articles regardless of topic.

### Change the embed colour

Edit the `"color"` hex value in `post_to_discord()` inside `check_feed.py`.

---

## Notes

- Uses only Python standard library — no `pip install` needed
- The WarCom Feed is unofficial but well-maintained; all content belongs to Warhammer Community / Games Workshop
- GitHub Actions free tier gives 2,000 minutes/month — this workflow uses ~1 min/run × 24 runs/day = ~720 min/month, well within the limit

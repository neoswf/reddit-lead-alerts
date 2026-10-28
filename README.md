# Reddit lead alerts

This watches a few subreddits for new posts where someone is looking for what you offer, and sends you a Telegram message when it finds one. You read the post and decide whether to reply. The tool itself never posts, comments or messages anyone.

It runs on GitHub's free scheduler, so your computer doesn't need to be on. Setup takes about 20 minutes and needs no coding.

**What an alert looks like:**

> **Your business · r/smallbusiness · 2 h old**
> **Small tree surgery business struggling to get enquiries, looking for honest local SEO**
> We've been trading for six years and most of our work comes from word of mouth…
> *Why: matched "local seo" in title*
> Open the post

## What you need

- A free GitHub account
- Telegram on your phone

**If someone already set this up for you** and handed you the repository, your settings are already in the `clients` folder. Start at step 2.

## Step 1: Make your own copy

1. On this repository's page, click **Use this template**, then **Create a new repository**.
2. Give it a name and choose **Private**. Private keeps your keywords and results to yourself.
3. Click **Create repository**.

## Step 2: Create your Telegram bot

The bot is your own private messenger. Only you will get its messages.

1. In Telegram, search for **@BotFather** (it has a blue check mark) and open the chat.
2. Send `/newbot`. It asks for a display name, then a username that ends in `bot`, for example `jane_leads_bot`.
3. BotFather replies with a **token**, a long line like `1234567890:AAH...`. Copy it. Treat it like a password: anyone who has it can send messages as your bot.
4. Tap the link BotFather gives you to open your new bot, and press **Start**. Nothing will happen, and that's fine. The bot has no replies of its own; this step just lets it message you later.

## Step 3: Add your secrets to GitHub

Secrets are stored encrypted by GitHub. Nobody can read them back, not even you.

In your repository go to **Settings → Secrets and variables → Actions → New repository secret** and add these two:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `REDDIT_USER_AGENT` | a label that tells Reddit who is reading, for example `lead-monitor/0.1 (contact jane@example.com)` |

## Step 4: Find your chat id

1. Go to the **Actions** tab. If GitHub asks, click the button to enable workflows.
2. Click **Lead monitor** on the left, then **Run workflow** on the right.
3. In the menu choose **find-telegram-chat-id** and click the green **Run workflow** button.
4. Wait about a minute, open the run, click the **check** job and open the **Run** step. You'll see a number next to your name.
5. Add one more secret, `TELEGRAM_CHAT_ID`, with that number as the value.

If it says no messages were found, open your bot in Telegram, send it any message, and run it again.

## Step 5: Send yourself a test alert

Run the workflow again, this time choosing **send-test-alert**. Your phone should get a message starting with `[TEST]` within a minute. If it does, Telegram is set up.

## Step 6: Choose what to watch

Skip this step if someone set it up for you.

Open the `clients` folder and click the `.toml` file. Click the pencil icon to edit it in your browser. The parts that matter:

```toml
name = "Your business"

[[sources]]
type = "reddit_rss"
subreddits = ["smallbusiness", "GoogleMyBusiness", "localseo"]

[match]
include = ["local seo", "google business profile", "looking for an seo"]
exclude = ["[for hire]", "my agency"]

[location]
terms = ["Denver"]
required = false
```

- **subreddits**: where to look. Names only, without `r/`.
- **include**: a post is a match if any of these phrases appears in its title or text. Capital letters don't matter.
- **exclude**: a post is skipped if any of these appears, even if it also matches. Use it for job ads, people selling the same service, and words with a second meaning.
- **location**: if `required = true`, only posts that mention one of these places count. Useful for a local business watching big subreddits.

Click **Commit changes** to save. The file has more settings, each with a short note next to it.

## Step 7: Turn it on

Run the workflow once more with **check**. From then on it checks by itself every 30 minutes. The first check looks at the last 12 hours of posts, so you may get a few alerts right away.

After each check you can open the run in the Actions tab to see a short page with the matches from the last 24 hours and any problems.

## Pausing and stopping

- **Pause everything:** Actions tab → **Lead monitor** → the **…** menu → **Disable workflow**. Enable it again the same way.
- **Pause one client file:** set `paused = true` at the top of that file.

## Getting good alerts

- **Look for buyers, not experts.** Subreddits where professionals talk shop are full of your keywords and empty of clients. Subreddits where business owners or homeowners ask for help are usually better, even if they are noisier.
- **Expect to adjust for a week.** Start with a handful of phrases, see what arrives, then add the words real buyers used and exclude the ones that brought noise.
- **Quiet subreddits are fine.** Some get one post a day. One request covers all your subreddits together, so a quiet one costs nothing.
- **Cross-posts arrive once.** People often post the same question in several subreddits. If the title is identical, you get one alert.
- **Fresh posts matter most.** A helpful reply in the first few hours is read by far more people than one a day later. Posts older than 12 hours are skipped by default (`max_age_hours`).

## Use it responsibly

- This reads Reddit's public RSS feed of new posts, the same feed any feed reader uses. It makes **one request every 30 minutes** at most, and the code won't go faster even if you change the setting.
- It **never posts or messages anyone.** Replying is up to you, by hand, from your own account.
- **Follow each subreddit's rules** when you reply. Many ban self-promotion or AI-written comments. A helpful answer without a sales pitch is what works there anyway.
- Reddit's terms say that commercial use of Reddit data through its developer API needs Reddit's approval. This tool doesn't use the API, but Reddit can change or block the RSS feed at any time, and how you use it is your responsibility. This is not legal advice.
- If Reddit answers "too many requests", the tool backs off for an hour by itself.

## What it stores

For each match it keeps the title, the first 200 characters, the link, the dates and the reason it matched. It never stores the full post or who wrote it. On GitHub this lives in your repository's Actions cache, which only people with access to your repository can reach. Alerts pass through Telegram's servers like any Telegram message.

If your bot token ever leaks, send `/revoke` to @BotFather to get a new one, and update the secret.

## Cost

Free. On GitHub's free plan, private repositories get a monthly allowance of Actions minutes. A check every 30 minutes uses roughly 1,440 minutes a month, because GitHub rounds each run up to a full minute. Check your usage under **Settings → Billing** if you also run other workflows. Telegram is free.

## Running it on your own computer (optional)

You need Python 3.11 or newer. Nothing else to install.

```bash
cp .env.example .env              # then fill in the three values
python3 monitor.py test           # offline test with sample posts, nothing is fetched
python3 monitor.py test-notify    # send a test alert
python3 monitor.py run            # one real check
python3 monitor.py loop           # keep checking every 30 minutes until you press Ctrl+C
python3 monitor.py dashboard      # a results page at http://127.0.0.1:8765
python3 monitor.py --help         # everything else (pause, resume, status, check)
```

The results page lets you mark each match as reviewed or not relevant. It works only when you run the tool on your computer, not on GitHub.

## For developers: adding another source

Each source is a small module in `leadmon/sources/` with a `validate(cfg)` and a `fetch(cfg, ctx)` that returns posts in a common shape. Add yours to `ADAPTERS` in `leadmon/sources/__init__.py` and use its name as `type` in a client file. Matching, storage, alerts and the schedule don't change.

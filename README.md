# NicheFinder Reddit Collector

A minimal, read-only Reddit Data API client extracted from the NicheFinder
research pipeline. It is published here to document exactly how NicheFinder
accesses Reddit data.

The collector uses the official Reddit OAuth API only:

- `https://www.reddit.com/api/v1/access_token` for `client_credentials`
- `https://oauth.reddit.com` for public search and comment reads

It does not scrape HTML, call undocumented `.json` endpoints, use a browser
session, or log in as a Reddit user.

## What it does

For a configured niche, the collector:

1. Searches public posts inside a small set of on-topic public subreddits.
2. Restricts each search to the subreddit (`restrict_sr=1`), sorts by newest,
   and covers the last 12 months.
3. Pages through results with the official `after` cursor.
4. Deduplicates posts by Reddit ID.
5. Fetches up to 50 public comments for the five most-commented recent posts.
6. Computes:
   - posts in the last 12 months;
   - posts in the last 6 months vs. the previous 6 months;
   - a trend percentage, suppressed when either window has fewer than five
     posts or pagination is incomplete;
   - an emerging-niche flag;
   - keyword-based complaint themes and complaint share;
   - counts of public launch announcements;
   - the top post and top launch by score.
7. Returns the results as `Signal` records; it does not write to Reddit.

The niche-to-subreddit mapping is in
`src/nichefinder/signals/reddit_queries.yaml`: 58 niche rules covering 140
unique public subreddits. On a given run, only the subreddits mapped to the
selected niches are queried.

## What it does not do

- No posting, commenting, voting, messaging or moderation actions.
- No private subreddits, user profiles or personal data collection.
- No user profiling.
- No training or fine-tuning of machine-learning models on Reddit content.
- No redistribution or resale of raw Reddit content.
- No retention of a full comment corpus. The pipeline stores aggregate metrics,
  post IDs/URLs, and short public examples for citation.

## Requirements

- Python 3.11+
- An approved Reddit Data API application (`client_id` and `client_secret`)
- A descriptive Reddit `User-Agent`

New Reddit Data API access is approval-only under Reddit's Responsible Builder
Policy. See:

- <https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy>
- <https://support.reddithelp.com/hc/en-us/requests/new?ticket_form_id=14868593862164>
- <https://redditinc.com/policies/data-api-terms>
- <https://www.reddit.com/robots.txt>

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill in `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` in `.env`, then load it
into the shell. The collector reads environment variables and does not load
`.env` automatically:

```bash
set -a
source .env
set +a
```

## Usage

```bash
python examples/collect.py ai_agents
```

Or from Python:

```python
from datetime import UTC, datetime

from nichefinder.signals.reddit import RedditCollector

collector = RedditCollector(now=datetime.now(UTC))
if not collector.available():
    raise SystemExit(collector.unavailable_reason)

try:
    signals = collector.collect("ai_agents", "AI agent")
finally:
    collector.close()

for signal in signals:
    print(signal.metric, signal.value, signal.unit, signal.text_value)
```

## Configuration

| Variable | Purpose |
|---|---|
| `REDDIT_CLIENT_ID` | OAuth application client ID |
| `REDDIT_CLIENT_SECRET` | OAuth application secret |
| `REDDIT_USER_AGENT` | Descriptive User-Agent sent to Reddit |
| `REDDIT_CALL_DELAY` | Delay between API calls; default `0.7` seconds |

The default delay keeps a run under roughly 100 requests per minute. The client
retries one time on `401` after refreshing the token and honors `Retry-After`
on `429`.

## Tests

```bash
pytest
ruff check src tests examples
```

The tests cover trend windows, truncation handling, emerging niches, launch
detection, complaint themes, subreddit rules, pagination/deduplication, comment
collection, missing credentials, and the OAuth token request.

## Layout

```text
src/nichefinder/
  models.py                     # Signal record
  signals/
    base.py                     # minimal HTTP client
    complaints.py               # keyword complaint themes
    reddit.py                   # Reddit OAuth collector
    reddit_queries.yaml         # niche -> subreddits/queries
tests/test_reddit.py
examples/collect.py
```

## License

Apache-2.0. See `LICENSE`.

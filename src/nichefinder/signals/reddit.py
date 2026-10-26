"""Reddit demand, trend, complaint and launch signals via the official OAuth API.

Reddit is useful evidence that Acquire cannot provide: the language customers
use, recurring pains and announcements of new products. The collector reads
public posts and comments only, uses OAuth application credentials, and respects
the API rate limit. It does not scrape HTML, bypass login, or collect private
data.

Trend is based on the raw number of matching posts in the last 6 months versus
the previous 6, because Reddit search does not expose a total corpus count.
When pagination cannot cover the full 12-month window, the trend is suppressed
and the counts are marked as sampled.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib.resources import files
from typing import Any
from urllib.parse import quote

import yaml

from nichefinder.models import Signal
from nichefinder.signals.base import HttpCollector
from nichefinder.signals.complaints import format_themes, summarize_complaints

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_URL = "https://oauth.reddit.com"
WINDOW_DAYS = 365
RECENT_DAYS = 183  # half a year, avoids calendar-boundary ambiguity
MIN_TREND_COUNT = 5
PAGE_SIZE = 100
MAX_PAGES = 10
COMMENTS_PER_NICHE = 5
COMMENTS_LIMIT = 50

LAUNCH_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bi\s+(?:just\s+)?(?:built|made|launched|released|shipped)\b",
        r"\bwe\s+(?:just\s+)?(?:launched|released|shipped)\b",
        r"\bintroducing\b",
        r"\bshow\s+(?:r/|reddit)\b",
        r"\bnew\s+(?:app|tool|product|startup|saas|platform|service)\b",
        r"\b(?:beta|waitlist|mvp)\b",
        r"\bopen[- ]sourced?\b",
    )
)


@dataclass(frozen=True)
class RedditRule:
    subreddits: tuple[str, ...]
    query: str | None = None


@lru_cache(maxsize=1)
def load_rules() -> dict[str, RedditRule]:
    path = files("nichefinder.signals").joinpath("reddit_queries.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules: dict[str, RedditRule] = {}
    for key, raw in (payload.get("rules") or {}).items():
        subreddits = tuple(
            _clean_subreddit(item) for item in raw.get("subreddits") or []
        )
        rules[str(key)] = RedditRule(
            subreddits=tuple(item for item in subreddits if item),
            query=str(raw["query"]).strip() if raw.get("query") else None,
        )
    return rules


def _clean_subreddit(value: Any) -> str:
    return str(value).strip().removeprefix("r/").removeprefix("/r/").strip("/")


def is_launch(post: dict[str, Any]) -> bool:
    text = f"{post.get('title') or ''} {post.get('selftext') or ''}"
    return any(pattern.search(text) for pattern in LAUNCH_PATTERNS)


def signals_from_posts(
    niche_key: str,
    query: str,
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    *,
    subreddits: tuple[str, ...] | list[str],
    now: datetime | None = None,
    truncated: bool = False,
    errors: list[str] | None = None,
) -> list[Signal]:
    """Build Reddit evidence from normalized posts/comments.

    ``truncated`` means pagination hit the API/listing cap before covering the
    full 12-month window. Counts are then a lower bound and the trend is hidden.
    """
    now = now or datetime.now(UTC)
    recent_cutoff = (now - timedelta(days=RECENT_DAYS)).timestamp()
    year_cutoff = (now - timedelta(days=WINDOW_DAYS)).timestamp()

    in_year = [post for post in posts if _created(post) >= year_cutoff]
    recent = [post for post in in_year if _created(post) >= recent_cutoff]
    previous = [post for post in in_year if _created(post) < recent_cutoff]

    recent_count = len(recent)
    previous_count = len(previous)
    reliable = recent_count >= MIN_TREND_COUNT and previous_count >= MIN_TREND_COUNT
    emerging = previous_count == 0 and recent_count >= MIN_TREND_COUNT
    trend = (
        (recent_count - previous_count) / previous_count * 100
        if reliable and not truncated and previous_count
        else None
    )
    if truncated:
        emerging = False

    corpus = [
        {"title": post.get("title") or "", "content": post.get("selftext") or ""}
        for post in recent
    ]
    corpus.extend(
        {"title": comment.get("title") or "", "content": comment.get("content") or ""}
        for comment in comments
    )
    complaint_summary = summarize_complaints(corpus)
    analyzed = len(corpus)
    complaint_share = complaint_summary["matched"] / analyzed if analyzed else None

    launches = [post for post in recent if is_launch(post)]
    launch_share = len(launches) / recent_count if recent_count else None
    top_launch = _top(launches)
    top_post = _top(recent)

    subreddit_list = [f"r/{name}" for name in subreddits]
    url = _search_url(subreddits, query)
    meta = {
        "query": query,
        "subreddits": subreddit_list,
        "window_days": WINDOW_DAYS,
        "recent_days": RECENT_DAYS,
        "trend_basis": "raw_post_count",
        "trend_min_count": MIN_TREND_COUNT,
        "truncated": truncated,
        "posts_sampled": len(posts),
        "comments_analyzed": len(comments),
        "themes": complaint_summary["themes"],
        "examples": complaint_summary["examples"],
        "top_launch": top_launch.get("title") if top_launch else None,
        "errors": errors or [],
    }

    signals = [
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="posts_12m",
            value=float(len(in_year)),
            unit="posts",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="posts_recent_6m",
            value=float(recent_count),
            unit="posts",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="posts_previous_6m",
            value=float(previous_count),
            unit="posts",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="trend_pct",
            value=round(trend, 1) if trend is not None else None,
            unit="%",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="emerging_6m",
            value=1.0 if emerging else 0.0,
            unit="flag",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="complaint_share",
            value=round(complaint_share, 3) if complaint_share is not None else None,
            unit="share",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="complaint_themes",
            value=round(complaint_share, 3) if complaint_share is not None else None,
            text_value=format_themes(complaint_summary),
            unit="share",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="comments_analyzed",
            value=float(len(comments)),
            unit="comments",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="launches_6m",
            value=float(len(launches)),
            unit="posts",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="launch_share",
            value=round(launch_share, 3) if launch_share is not None else None,
            unit="share",
            url=url,
            meta=meta,
        ),
        Signal(
            niche_key=niche_key,
            source="reddit",
            metric="subreddits",
            value=float(len(subreddit_list)),
            text_value=", ".join(subreddit_list),
            unit="subreddits",
            url=url,
            meta=meta,
        ),
    ]
    if top_launch:
        signals.append(
            Signal(
                niche_key=niche_key,
                source="reddit",
                metric="top_launch",
                value=float(top_launch.get("score") or 0),
                text_value=top_launch.get("title"),
                unit="points",
                url=top_launch.get("permalink"),
                meta=meta,
            )
        )
    if top_post:
        signals.append(
            Signal(
                niche_key=niche_key,
                source="reddit",
                metric="top_post",
                value=float(top_post.get("score") or 0),
                text_value=top_post.get("title"),
                unit="points",
                url=top_post.get("permalink"),
                meta=meta,
            )
        )
    return signals


def _created(post: dict[str, Any]) -> float:
    try:
        return float(post.get("created_utc") or 0)
    except (TypeError, ValueError):
        return 0.0


def _top(posts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not posts:
        return None
    return max(
        posts,
        key=lambda post: (
            float(post.get("score") or 0),
            float(post.get("num_comments") or 0),
            _created(post),
        ),
    )


def _search_url(subreddits: tuple[str, ...] | list[str], query: str) -> str:
    if len(subreddits) == 1:
        base = f"https://www.reddit.com/r/{subreddits[0]}/search/"
    else:
        base = "https://www.reddit.com/search/"
    return f"{base}?q={quote(query)}&sort=new&t=year"


class RedditCollector(HttpCollector):
    source = "reddit"

    def __init__(
        self,
        *args: Any,
        now: datetime | None = None,
        call_delay: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.now = now or datetime.now(UTC)
        self.call_delay = (
            call_delay
            if call_delay is not None
            else float(os.getenv("REDDIT_CALL_DELAY", "0.7"))
        )
        self.client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        base_agent = (
            os.getenv("NICHEFINDER_USER_AGENT")
            or kwargs.get("user_agent")
            or "nichefinder/0.1"
        )
        self.user_agent = os.getenv(
            "REDDIT_USER_AGENT",
            f"{base_agent} reddit-client",
        ).strip() or f"{base_agent} reddit-client"
        self._token: str | None = None
        self._token_expires = 0.0
        self._cache: dict[str, list[Signal]] = {}

    def available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def unavailable_reason(self) -> str:
        return (
            "Reddit credentials are missing. New Data API access is approval-only "
            "under Reddit's Responsible Builder Policy; see README.md. "
            "After approval set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env"
        )

    def collect(self, niche_key: str, query: str) -> list[Signal]:
        if niche_key in self._cache:
            return self._cache[niche_key]
        rule = load_rules().get(niche_key)
        if rule is None or not rule.subreddits:
            self._cache[niche_key] = []
            return []

        search_query = rule.query or query
        posts: list[dict[str, Any]] = []
        errors: list[str] = []
        truncated = False
        seen: set[str] = set()
        for subreddit in rule.subreddits:
            try:
                found, was_truncated = self._search(subreddit, search_query)
            except Exception as exc:  # noqa: BLE001 - one subreddit must not stop the niche
                errors.append(f"{subreddit}: {str(exc)[:160]}")
                continue
            truncated = truncated or was_truncated
            for post in found:
                post_id = str(post.get("id") or "")
                if post_id and post_id not in seen:
                    seen.add(post_id)
                    posts.append(post)

        if not posts and errors:
            raise RuntimeError("; ".join(errors)[:300])

        comments, comment_errors = self._comments_for(posts)
        errors.extend(comment_errors)
        signals = signals_from_posts(
            niche_key,
            search_query,
            posts,
            comments,
            subreddits=rule.subreddits,
            now=self.now,
            truncated=truncated,
            errors=errors,
        )
        self._cache[niche_key] = signals
        return signals

    def _search(self, subreddit: str, query: str) -> tuple[list[dict[str, Any]], bool]:
        cutoff = (self.now - timedelta(days=WINDOW_DAYS)).timestamp()
        params: dict[str, Any] = {
            "q": query,
            "restrict_sr": "1",
            "sort": "new",
            "t": "year",
            "limit": PAGE_SIZE,
            "raw_json": 1,
        }
        posts: dict[str, dict[str, Any]] = {}
        after: str | None = None
        truncated = False

        for _ in range(MAX_PAGES):
            if after:
                params["after"] = after
            payload = self._api_get(f"/r/{quote(subreddit)}/search", params)
            data = payload.get("data") or {}
            children = data.get("children") or []
            if not children:
                break
            for child in children:
                post = _normalize_post(child.get("data") or {})
                if post.get("id"):
                    posts[str(post["id"])] = post
            after = data.get("after")
            if not after:
                break
            oldest = min((_created(post) for post in posts.values()), default=0)
            if oldest < cutoff:
                break
        else:
            truncated = True

        result = list(posts.values())
        result.sort(key=_created, reverse=True)
        return result, truncated

    def _comments_for(
        self, posts: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        recent_cutoff = (self.now - timedelta(days=RECENT_DAYS)).timestamp()
        candidates = [
            post
            for post in posts
            if _created(post) >= recent_cutoff and int(post.get("num_comments") or 0) > 0
        ]
        candidates.sort(key=lambda post: int(post.get("num_comments") or 0), reverse=True)

        comments: list[dict[str, Any]] = []
        errors: list[str] = []
        seen: set[str] = set()
        for post in candidates[:COMMENTS_PER_NICHE]:
            try:
                payload = self._api_get(
                    f"/comments/{post['id']}",
                    {"limit": COMMENTS_LIMIT, "depth": 1, "sort": "top", "raw_json": 1},
                )
            except Exception as exc:  # noqa: BLE001 - comments are optional evidence
                errors.append(f"comments/{post.get('id')}: {str(exc)[:120]}")
                continue
            for comment in _parse_comments(payload):
                body = str(comment.get("body") or "").strip()
                key = str(comment.get("id") or body[:80])
                if not body or key in seen:
                    continue
                seen.add(key)
                comments.append(
                    {
                        "id": key,
                        "title": post.get("title") or "",
                        "content": body,
                        "score": comment.get("score") or 0,
                    }
                )
        return comments, errors

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        if not self.available():
            raise RuntimeError(self.unavailable_reason)

        response = self.client.post(
            TOKEN_URL,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self.user_agent},
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Reddit auth failed: HTTP {response.status_code} "
                f"{response.text[:160]}"
            )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError(f"Reddit auth failed: {str(payload)[:160]}")
        self._token = str(token)
        self._token_expires = time.monotonic() + int(payload.get("expires_in") or 3600) - 30
        return self._token

    def _api_get(self, path: str, params: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(2):
            response = self.client.get(
                f"{API_URL}{path}",
                params=params,
                headers={
                    "Authorization": f"bearer {self._access_token()}",
                    "User-Agent": self.user_agent,
                },
            )
            if response.status_code == 401 and attempt == 0:
                self._token = None
                continue
            if response.status_code == 429 and attempt == 0:
                try:
                    wait = float(response.headers.get("Retry-After", "2"))
                except (TypeError, ValueError):
                    wait = 2.0
                time.sleep(min(max(wait, 1.0), 10.0))
                last_error = RuntimeError("Reddit API rate limit")
                continue
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Reddit API HTTP {response.status_code}: {response.text[:160]}"
                )
            if self.call_delay:
                time.sleep(self.call_delay)
            return response.json()
        raise RuntimeError(f"Reddit API request failed: {last_error}")


def _normalize_post(data: dict[str, Any]) -> dict[str, Any]:
    permalink = str(data.get("permalink") or "")
    if permalink and permalink.startswith("/"):
        permalink = f"https://www.reddit.com{permalink}"
    return {
        "id": data.get("id"),
        "title": data.get("title") or "",
        "selftext": data.get("selftext") or "",
        "created_utc": data.get("created_utc") or 0,
        "score": data.get("score") or 0,
        "num_comments": data.get("num_comments") or 0,
        "permalink": permalink,
        "subreddit": data.get("subreddit") or "",
        "url": data.get("url_overridden_by_dest") or permalink,
    }


def _parse_comments(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    listing = payload[1] or {}
    children = (listing.get("data") or {}).get("children") or []
    comments = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data") or {}
        if data.get("body"):
            comments.append(data)
    return comments

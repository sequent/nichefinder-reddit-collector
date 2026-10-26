from datetime import UTC, datetime, timedelta

from nichefinder.signals.reddit import (
    RedditCollector,
    is_launch,
    load_rules,
    signals_from_posts,
)

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def _post(
    post_id: str,
    days_ago: float,
    title: str,
    *,
    selftext: str = "",
    score: int = 10,
    comments: int = 5,
) -> dict:
    created = NOW - timedelta(days=days_ago)
    return {
        "id": post_id,
        "title": title,
        "selftext": selftext,
        "created_utc": created.timestamp(),
        "score": score,
        "num_comments": comments,
        "permalink": f"https://www.reddit.com/r/test/comments/{post_id}",
        "subreddit": "test",
    }


def test_reddit_signals_compute_trend_complaints_and_launches():
    posts = [
        _post("r1", 10, "I built an AI agent for sales", selftext="Launching the beta today", score=50),
        _post("r2", 20, "AI agent recommendations", selftext="Looking for a tool"),
        _post("r3", 30, "AI agent is too expensive", selftext="Pricing is painful"),
        _post("r4", 40, "AI agent sync issues", selftext="Does not sync"),
        _post("r5", 50, "AI agent for support", selftext="We launched our product"),
        _post("r6", 60, "AI agent ideas", selftext="What do you use?"),
        _post("p1", 200, "Old AI agent", selftext="Old post"),
        _post("p2", 220, "Old AI agent", selftext="Old post"),
        _post("p3", 240, "Old AI agent", selftext="Old post"),
        _post("p4", 260, "Old AI agent", selftext="Old post"),
        _post("p5", 280, "Old AI agent", selftext="Old post"),
    ]
    comments = [
        {
            "title": "AI agent recommendations",
            "content": "Everything is too expensive and crashes constantly.",
        }
    ]

    signals = signals_from_posts(
        "ai_agents",
        "AI agent",
        posts,
        comments,
        subreddits=("AI_Agents", "LocalLLaMA"),
        now=NOW,
    )
    by_metric = {signal.metric: signal for signal in signals}

    assert by_metric["posts_12m"].value == 11
    assert by_metric["posts_recent_6m"].value == 6
    assert by_metric["posts_previous_6m"].value == 5
    assert by_metric["trend_pct"].value == 20.0
    assert by_metric["emerging_6m"].value == 0.0
    assert by_metric["comments_analyzed"].value == 1
    assert by_metric["launches_6m"].value == 2
    assert by_metric["top_launch"].text_value == "I built an AI agent for sales"
    assert 0 < by_metric["complaint_share"].value <= 1
    assert "цена" in by_metric["complaint_themes"].text_value
    assert by_metric["subreddits"].text_value == "r/AI_Agents, r/LocalLLaMA"


def test_reddit_trend_is_suppressed_when_truncated_or_small():
    posts = [
        _post("r1", 10, "AI agent one"),
        _post("r2", 20, "AI agent two"),
        _post("r3", 30, "AI agent three"),
        _post("r4", 40, "AI agent four"),
        _post("p1", 200, "AI agent old"),
    ]

    truncated = signals_from_posts(
        "ai_agents",
        "AI agent",
        posts,
        [],
        subreddits=("AI_Agents",),
        now=NOW,
        truncated=True,
    )
    by_metric = {signal.metric: signal for signal in truncated}
    assert by_metric["trend_pct"].value is None
    assert by_metric["emerging_6m"].value == 0.0
    assert by_metric["posts_recent_6m"].value == 4


def test_reddit_emerging_when_previous_window_is_empty():
    posts = [_post(f"r{index}", 10 + index, f"AI agent {index}") for index in range(5)]
    signals = signals_from_posts(
        "ai_agents",
        "AI agent",
        posts,
        [],
        subreddits=("AI_Agents",),
        now=NOW,
    )
    by_metric = {signal.metric: signal for signal in signals}
    assert by_metric["trend_pct"].value is None
    assert by_metric["emerging_6m"].value == 1.0


def test_launch_detection_requires_launch_language():
    assert is_launch({"title": "I built a new CRM"})
    assert is_launch({"title": "We launched our app", "selftext": "beta is open"})
    assert is_launch({"title": "Introducing Acme"})
    assert not is_launch({"title": "Looking for a CRM recommendation"})
    assert not is_launch({"title": "How we built our roadmap"})


def test_reddit_rules_cover_core_niches():
    rules = load_rules()
    for key in ("ai_agents", "marketing", "sales", "health", "devtools", "shopify"):
        assert key in rules
        assert rules[key].subreddits
        assert all(not subreddit.startswith("r/") for subreddit in rules[key].subreddits)


def test_reddit_collector_dedupes_posts_and_fetches_comments(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    collector = RedditCollector(now=NOW, call_delay=0)
    recent = (NOW - timedelta(days=10)).timestamp()
    previous = (NOW - timedelta(days=200)).timestamp()

    def fake_api_get(path: str, params: dict):
        if "/search" in path:
            if params.get("after"):
                return {
                    "data": {
                        "children": [
                            {
                                "kind": "t3",
                                "data": {
                                    "id": "p1",
                                    "title": "Old AI agent",
                                    "created_utc": previous,
                                    "score": 2,
                                    "num_comments": 0,
                                    "permalink": "/r/test/p1",
                                },
                            }
                        ],
                        "after": None,
                    }
                }
            return {
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "id": "r1",
                                "title": "I built an AI agent",
                                "selftext": "beta",
                                "created_utc": recent,
                                "score": 10,
                                "num_comments": 3,
                                "permalink": "/r/test/r1",
                            },
                        },
                        {
                            "kind": "t3",
                            "data": {
                                "id": "r1",
                                "title": "I built an AI agent",
                                "selftext": "beta",
                                "created_utc": recent,
                                "score": 10,
                                "num_comments": 3,
                                "permalink": "/r/test/r1",
                            },
                        },
                    ],
                    "after": "t3_next",
                }
            }
        if "/comments/" in path:
            return [
                {"data": {"children": []}},
                {
                    "data": {
                        "children": [
                            {
                                "kind": "t1",
                                "data": {
                                    "id": "c1",
                                    "body": "Too expensive and crashes.",
                                    "score": 4,
                                },
                            }
                        ]
                    }
                },
            ]
        raise AssertionError(f"unexpected path: {path}")

    collector._api_get = fake_api_get  # type: ignore[method-assign]
    try:
        signals = collector.collect("ai_agents", "AI agent")
    finally:
        collector.close()

    by_metric = {signal.metric: signal for signal in signals}
    assert by_metric["posts_recent_6m"].value == 1
    assert by_metric["posts_previous_6m"].value == 1
    assert by_metric["comments_analyzed"].value == 1
    assert by_metric["launches_6m"].value == 1


def test_reddit_is_unavailable_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    collector = RedditCollector(call_delay=0)
    try:
        assert not collector.available()
        assert "REDDIT_CLIENT_ID" in collector.unavailable_reason
    finally:
        collector.close()


def test_reddit_oauth_token_request_uses_client_credentials(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "client-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "nichefinder-test/1.0")
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"access_token": "token-123", "expires_in": 3600}

    class FakeClient:
        def post(self, url, **kwargs):
            captured.update({"url": url, **kwargs})
            return FakeResponse()

    collector = RedditCollector(client=FakeClient(), call_delay=0)
    try:
        assert collector._access_token() == "token-123"
    finally:
        collector.close()

    assert captured["url"] == "https://www.reddit.com/api/v1/access_token"
    assert captured["auth"] == ("client-id", "client-secret")
    assert captured["data"] == {"grant_type": "client_credentials"}
    assert captured["headers"]["User-Agent"] == "nichefinder-test/1.0"

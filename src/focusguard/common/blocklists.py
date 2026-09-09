"""Curated starter lists of commonly-distracting domains, offered in the
profile editor as a one-click way to seed `blocked_domains` instead of
typing sites in one at a time. Purely a UI convenience -- these are just
plain domains, added through the exact same `blocked_domains` path as
anything typed by hand, and the user can remove any of them afterward.
"""
from __future__ import annotations

STARTER_BLOCKLISTS: dict[str, list[str]] = {
    "Social media": [
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "tiktok.com",
        "reddit.com",
        "snapchat.com",
        "linkedin.com",
    ],
    "Video / streaming": [
        "youtube.com",
        "netflix.com",
        "twitch.tv",
        "hulu.com",
        "primevideo.com",
    ],
    "Shopping": [
        "amazon.com",
        "ebay.com",
        "etsy.com",
        "aliexpress.com",
    ],
    "News": [
        "cnn.com",
        "nytimes.com",
        "foxnews.com",
        "bbc.com",
    ],
}

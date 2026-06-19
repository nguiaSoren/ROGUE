"""Source plugins — one .py per source type. Pattern: ROGUE_PLAN.md §A.19, sources list §5.1."""

from .arxiv_listing import ArxivListingPlugin
from .base import SourcePlugin
from .blog_static import BlogStaticPlugin
from .community_archive import CommunityArchivePlugin
from .github_search import GithubSearchPlugin
from .huggingface_discussion import HuggingFaceDiscussionPlugin
from .leakhub_scrape import LeakHubScrapePlugin
from .obliteratus_hf import ObliteratusHfPlugin
from .pliny_github import PlinyGithubPlugin
from .reddit_subreddit import RedditSubredditPlugin
from .x_user_timeline import XUserTimelinePlugin
from .x_via_unlocker import XViaUnlockerPlugin

__all__ = [
    "SourcePlugin",
    "ArxivListingPlugin",
    "BlogStaticPlugin",
    "CommunityArchivePlugin",
    "GithubSearchPlugin",
    "HuggingFaceDiscussionPlugin",
    "LeakHubScrapePlugin",
    "ObliteratusHfPlugin",
    "PlinyGithubPlugin",
    "RedditSubredditPlugin",
    "XUserTimelinePlugin",
    "XViaUnlockerPlugin",
]

# Bronze -> Silver (HTML cleanup, dedup, senior & non-tech role filter)
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

import dateparser
from bs4 import BeautifulSoup
from pydantic import BaseModel
from rapidfuzz import fuzz, process

from config.settings import get_settings
from models.schemas import RawJob
from utils.logger import get_logger

logger = get_logger(__name__)

SENIOR_TITLE_PATTERN = re.compile(
    r"\b(senior|staff|principal|lead|manager|director|vp|head of|architect|distinguished|iii|iv|v)\b|\bsr\.?(?=\s|$)",
    re.IGNORECASE,
)

# Seed list of canonical company names for Entity Resolution
CANONICAL_COMPANIES = [
    "Stripe",
    "Anthropic",
    "Scale AI",
    "Databricks",
    "Meesho",
    "Palantir",
    "OpenAI",
    "Google",
    "Microsoft",
    "Razorpay",
]

# Keywords to pre-filter relevant tech roles before calling any LLM
TARGET_TITLE_KEYWORDS = (
    "ai ",
    " ai",
    "ml ",
    " ml",
    "machine learning",
    "data analyst",
    "data scientist",
    "data engineer",
    "python",
    "software",
    "engineer",
    "developer",
    "backend",
    "qa",
    "test",
    "intern",
)

# Drop obvious non-tech and senior leadership roles immediately
EXCLUDE_TITLE_KEYWORDS = (
    "accounting",
    "finance",
    "financial",
    "sales",
    "legal",
    "recruiter",
    "marketing",
    "hr ",
    "human resources",
    "staff ",
    "principal",
    "director",
    "vp ",
    "vice president",
    "head of",
    "manager",
)


class CleanJob(BaseModel):
    """Cleaned, fresh, deduplicated job ready for LLM evaluation."""

    url: str
    source: str
    title: str
    company_canonical: str
    company_raw: str
    location: Optional[str] = None
    is_remote: bool = False
    description_clean: str
    posted_at: datetime
    collected_at: datetime


def strip_html(raw_html: str) -> str:
    """Removes HTML tags and extra whitespace to save LLM tokens."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return " ".join(soup.get_text(separator=" ").split())


def parse_posted_date(raw_date: Optional[str]) -> Optional[datetime]:
    """Converts ISO strings or relative dates ('2 hours ago') into UTC datetime."""
    if not raw_date:
        return None
    parsed = dateparser.parse(
        raw_date,
        settings={"RETURN_AS_TIMEZONE_AWARE": True, "TIMEZONE": "UTC"},
    )
    return parsed


def resolve_company(raw_name: str, threshold: int = 85) -> str:
    """Fuzzy-matches messy company names against our canonical seed list."""
    cleaned = raw_name.strip()
    match = process.extractOne(
        cleaned, CANONICAL_COMPANIES, scorer=fuzz.token_sort_ratio
    )
    if match and match[1] >= threshold:
        return match[0]
    return cleaned


def is_relevant_title(title: str) -> bool:
    """Fast keyword gate to drop non-tech and senior leadership roles."""
    title_lower = f" {title.lower()} "
    if any(bad in title_lower for bad in EXCLUDE_TITLE_KEYWORDS):
        return False
    return any(keyword in title_lower for keyword in TARGET_TITLE_KEYWORDS)


def clean_jobs(
    raw_jobs: List[RawJob],
    existing_urls: Set[str],
    max_age_hours: Optional[int] = None,
) -> List[CleanJob]:
    """Filters duplicates, irrelevant roles, and stale jobs; cleans text & names."""
    max_hours = max_age_hours or get_settings().MAX_JOB_AGE_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)

    cleaned_list: List[CleanJob] = []
    seen_in_batch: Set[str] = set()

    for job in raw_jobs:
        url_str = str(job.url)

        # 1. Skip already-saved URLs or duplicates within this run
        if url_str in existing_urls or url_str in seen_in_batch:
            continue

        # 2. Drop Senior/Staff/Manager listings
        if SENIOR_TITLE_PATTERN.search(job.title):
            continue

        # 3. Skip irrelevant non-tech or senior leadership titles
        if not is_relevant_title(job.title):
            continue

        # 4. Parse date & enforce freshness window
        posted_at = parse_posted_date(job.posted_at_raw)
        if not posted_at or posted_at < cutoff:
            continue

        # 5. Strip HTML & resolve canonical company name
        clean_desc = strip_html(job.description)
        canonical_company = resolve_company(job.company_raw)

        seen_in_batch.add(url_str)
        cleaned_list.append(
            CleanJob(
                url=url_str,
                source=job.source,
                title=job.title.strip(),
                company_canonical=canonical_company,
                company_raw=job.company_raw,
                location=job.location,
                is_remote=job.is_remote,
                description_clean=clean_desc,
                posted_at=posted_at,
                collected_at=job.collected_at,
            )
        )

    logger.info(
        f"Cleaner funnel: {len(raw_jobs)} raw -> {len(cleaned_list)} fresh & relevant jobs (last {max_hours}h)"
    )
    return cleaned_list
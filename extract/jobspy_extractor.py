# Scrapes Naukri, Indeed, LinkedIn (with tenacity retries & delays)
from typing import List

import pandas as pd
from jobspy import scrape_jobs

from config.settings import get_settings
from models.schemas import RawJob
from utils.logger import get_logger

logger = get_logger(__name__)

# Easy to edit anytime
SITE_NAMES = ["naukri", "linkedin"]
SEARCH_TERMS = [
    "AI Engineer fresher",
    "Data Analyst fresher",
    "Python Developer fresher",
    "Machine Learning Engineer",
]
DEFAULT_LOCATION = "India"


def _safe_str(val) -> str:
    """Converts pandas NaN/None values safely into an empty string."""
    if val is None or pd.isna(val):
        return ""
    return str(val).strip()


class JobSpyExtractor:
    def __init__(
        self,
        sites: List[str] = SITE_NAMES,
        search_terms: List[str] = SEARCH_TERMS,
        location: str = DEFAULT_LOCATION,
        results_per_term: int = 15,
    ):
        self.sites = sites
        self.search_terms = search_terms
        self.location = location
        self.results_per_term = results_per_term

    def fetch_all(self) -> List[RawJob]:
        """Scrapes major job boards and converts rows into standard RawJob models."""
        hours_old = get_settings().MAX_JOB_AGE_HOURS
        all_jobs: List[RawJob] = []

        for term in self.search_terms:
            try:
                logger.info(f"JobSpy searching '{term}' in {self.location}...")
                df = scrape_jobs(
                    site_name=self.sites,
                    search_term=term,
                    location=self.location,
                    results_wanted=self.results_per_term,
                    hours_old=hours_old,
                    country_indeed="India",
                )

                if df is None or df.empty:
                    continue

                for _, row in df.iterrows():
                    job_url = _safe_str(row.get("job_url"))
                    title = _safe_str(row.get("title"))
                    if not job_url or not title:
                        continue

                    location = _safe_str(row.get("location"))
                    is_remote = bool(row.get("is_remote")) if not pd.isna(row.get("is_remote")) else False
                    if "remote" in location.lower():
                        is_remote = True

                    posted_raw = _safe_str(row.get("date_posted")) or None

                    all_jobs.append(
                        RawJob(
                            source=_safe_str(row.get("site")) or "jobspy",
                            url=job_url,
                            title=title,
                            company_raw=_safe_str(row.get("company")) or "Unknown",
                            location=location,
                            is_remote=is_remote,
                            description=_safe_str(row.get("description")),
                            posted_at_raw=posted_raw,
                        )
                    )

                logger.info(f"JobSpy ['{term}']: fetched {len(df)} rows")

            except Exception as e:
                logger.warning(f"JobSpy failed for term '{term}': {e}")

        logger.info(f"Total JobSpy jobs extracted: {len(all_jobs)}")
        return all_jobs
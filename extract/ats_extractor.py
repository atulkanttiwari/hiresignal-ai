# Queries Workday, Greenhouse, Lever via Serper API + JD parser
import asyncio
from datetime import datetime, timezone
from typing import Dict, List

import aiohttp

from models.schemas import RawJob
from utils.logger import get_logger

logger = get_logger(__name__)

# Public ATS board tokens (easy to expand anytime)
GREENHOUSE_BOARDS: Dict[str, str] = {
    "stripe": "Stripe",
    "anthropic": "Anthropic",
    "scaleai": "Scale AI",
    "databricks": "Databricks",
    "razorpay": "Razorpay",
}

LEVER_BOARDS: Dict[str, str] = {
    "meesho": "Meesho",
    "palantir": "Palantir",
    "mistral": "Mistral AI",
}


class ATSExtractor:
    def __init__(self, max_concurrency: int = 5, timeout_sec: int = 15):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout_sec)

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str):
        async with self.semaphore:
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.warning(f"HTTP {response.status} from {url}")
                        return None
                    return await response.json()
            except Exception as e:
                logger.error(f"Request failed for {url}: {e}")
                return None

    async def _fetch_greenhouse(
        self, session: aiohttp.ClientSession, token: str, company_name: str
    ) -> List[RawJob]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        data = await self._fetch_json(session, url)
        if not data or "jobs" not in data:
            return []

        jobs: List[RawJob] = []
        for item in data["jobs"]:
            job_url = item.get("absolute_url")
            title = item.get("title")
            if not job_url or not title:
                continue

            location = (item.get("location") or {}).get("name", "")
            is_remote = "remote" in location.lower() or "remote" in title.lower()

            jobs.append(
                RawJob(
                    source="greenhouse",
                    url=job_url,
                    title=title,
                    company_raw=company_name,
                    location=location,
                    is_remote=is_remote,
                    description=item.get("content", "") or "",
                    posted_at_raw=item.get("updated_at"),
                )
            )
        logger.info(f"Greenhouse [{company_name}]: fetched {len(jobs)} jobs")
        return jobs

    async def _fetch_lever(
        self, session: aiohttp.ClientSession, slug: str, company_name: str
    ) -> List[RawJob]:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        data = await self._fetch_json(session, url)
        if not isinstance(data, list):
            return []

        jobs: List[RawJob] = []
        for item in data:
            job_url = item.get("hostedUrl")
            title = item.get("text")
            if not job_url or not title:
                continue

            categories = item.get("categories") or {}
            location = categories.get("location", "")
            workplace = (item.get("workplaceType") or "").lower()
            is_remote = workplace == "remote" or "remote" in location.lower()

            # Lever timestamps are in milliseconds since epoch
            created_ms = item.get("createdAt")
            posted_at_raw = (
                datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).isoformat()
                if created_ms
                else None
            )

            jobs.append(
                RawJob(
                    source="lever",
                    url=job_url,
                    title=title,
                    company_raw=company_name,
                    location=location,
                    is_remote=is_remote,
                    description=item.get("descriptionPlain", "") or "",
                    posted_at_raw=posted_at_raw,
                )
            )
        logger.info(f"Lever [{company_name}]: fetched {len(jobs)} jobs")
        return jobs

    async def fetch_all(self) -> List[RawJob]:
        """Concurrently fetches jobs across all configured Greenhouse & Lever boards."""
        headers = {"User-Agent": "JobIntelligencePipeline/1.0"}
        async with aiohttp.ClientSession(timeout=self.timeout, headers=headers) as session:
            tasks = [
                self._fetch_greenhouse(session, token, name)
                for token, name in GREENHOUSE_BOARDS.items()
            ] + [
                self._fetch_lever(session, slug, name)
                for slug, name in LEVER_BOARDS.items()
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_jobs: List[RawJob] = []
        for res in results:
            if isinstance(res, list):
                all_jobs.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Extractor task raised exception: {res}")

        logger.info(f"Total ATS jobs extracted: {len(all_jobs)}")
        return all_jobs
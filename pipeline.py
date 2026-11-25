import asyncio
from pathlib import Path
from typing import List

from extract.ats_extractor import ATSExtractor
from extract.jobspy_extractor import JobSpyExtractor
from load.db_manager import DBManager
from models.schemas import ProcessedJob
from transform.cleaner import clean_jobs
from transform.llm_matcher import LLMMatcher
from utils.logger import get_logger
from utils.notifier import TelegramNotifier

logger = get_logger(__name__)

RESUME_PATH = Path("config/resume.txt")


def load_resume() -> str:
    """Loads candidate resume text from config/resume.txt."""
    if not RESUME_PATH.exists():
        raise FileNotFoundError(
            f"Resume file not found at {RESUME_PATH}. Create it and paste your resume text."
        )
    text = RESUME_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{RESUME_PATH} is empty. Paste your resume text before running.")
    return text


def run_pipeline(max_llm_jobs: int = 80) -> None:
    """Runs the full End-to-End ETL Job Intelligence Pipeline."""
    logger.info("=== Starting Job Intelligence Pipeline ===")

    # 1. Setup: Resume + DB deduplication set
    resume_text = load_resume()
    db = DBManager()
    existing_urls = db.get_existing_urls()
    logger.info(f"Loaded {len(existing_urls)} existing URLs from database")

    # 2. Extract: Verified Direct ATS APIs + Job Boards (LinkedIn, Naukri)
    ats_jobs = asyncio.run(ATSExtractor().fetch_all())
    jobspy_jobs = JobSpyExtractor().fetch_all()
    raw_jobs = ats_jobs + jobspy_jobs  # Prioritize verified direct ATS jobs first
    logger.info(f"Total raw jobs extracted: {len(raw_jobs)}")

    # 3. Transform (Silver): Deduplicate, filter freshness, strip HTML, resolve companies
    cleaned_jobs = clean_jobs(raw_jobs, existing_urls)
    if not cleaned_jobs:
        logger.info("No new relevant jobs found today. Pipeline finished.")
        TelegramNotifier().send_alerts([])
        return

    # Cap LLM calls per run to protect free-tier quotas
    jobs_to_score = cleaned_jobs[:max_llm_jobs]
    logger.info(f"Sending {len(jobs_to_score)} jobs to LLM matcher (cap={max_llm_jobs})")

    # 4. Transform (Gold): Score each job against resume via 3-tier LLM fallback
    matcher = LLMMatcher()
    processed_jobs: List[ProcessedJob] = []

    for job in jobs_to_score:
        outcome = matcher.evaluate_job(job, resume_text)
        if not outcome:
            continue

        match_result, provider_name = outcome

        processed_jobs.append(
            ProcessedJob(
                url=job.url,
                source=job.source,
                title=job.title,
                company_canonical=job.company_canonical,
                company_raw=job.company_raw,
                location=job.location,
                is_remote=job.is_remote,
                description_clean=job.description_clean,
                posted_at=job.posted_at,
                collected_at=job.collected_at,
                match_score=match_result.match_score,
                role_family=match_result.role_family,
                is_fresher_friendly=match_result.is_fresher_friendly,
                matching_skills=match_result.matching_skills,
                missing_skills=match_result.missing_skills,
                reasoning=match_result.reasoning,
                llm_provider_used=provider_name,
            )
        )

    # 5. Load: Save scored jobs to SQLite
    if processed_jobs:
        saved_count = 0
        for p_job in processed_jobs:
            if db.save_job(p_job):
                saved_count += 1
        logger.info(f"Saved {saved_count} new scored jobs to database.")

        # 6. Notify: Push high-match jobs to Telegram
        TelegramNotifier().send_alerts(processed_jobs)
    else:
        logger.warning("No jobs were successfully scored by the LLM.")

    logger.info("=== Pipeline Run Complete ===")


if __name__ == "__main__":
    run_pipeline(max_llm_jobs=30)
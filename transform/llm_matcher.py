# Silver -> Gold (3-tier LLM fallback + explainable eligibility)
import json
import time
from typing import Dict, List, Optional, Tuple

from openai import OpenAI

from config.settings import get_settings
from models.schemas import LLMMatchResult
from transform.cleaner import CleanJob
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_DESC_CHARS = 4000

SYSTEM_PROMPT = """You are a strict technical recruiter evaluating a 2026 fresher's resume against a job description.

Return ONLY a valid JSON object with these exact keys:
- "match_score": integer from 0 to 100
- "role_family": short category string (e.g., "AI/ML", "Data Science", "Data Analyst", "Software Engineering", "QA/Test")
- "matching_skills": list of up to 5 concrete technical skills from the resume that match the job
- "missing_skills": list of up to 5 concrete technical skills missing from the resume
- "is_fresher_friendly": boolean (true if minimum required experience is 0-1 years—including "0-2 years", fresher, graduate trainee, early career, or entry-level; false if minimum 2+ years is required)
- "reasoning": 1-2 concise sentences explaining the score

Strict Evaluation Rules:
1. Scam / Trap Filter: If the posting looks like an unpaid internship, paid training-cum-placement program, or third-party consultancy trap, cap "match_score" at 10 and mention it in "reasoning".
2. Location & Visa: The candidate is based in India and requires visa sponsorship for US/EU roles. Keep India, globally remote, and visa-sponsored US/EU roles eligible; only cap "match_score" at 20 if the posting explicitly states no visa sponsorship or requires existing US/EU work authorization.
3. Experience Level: The candidate is a 2026 graduate with 0 years of full-time corporate experience. If the role strictly requires a minimum of 2+ years of experience, set "is_fresher_friendly" to false and cap "match_score" at 40.
"""


class LLMMatcher:
    def __init__(self, delay_sec: float = 1.5):
        self.delay_sec = delay_sec
        self.providers = self._build_providers()
        if not self.providers:
            logger.warning("No LLM API keys found in .env! Scoring will be skipped.")

    def _build_providers(self) -> List[Dict]:
        """Builds the 3-tier fallback chain using only configured API keys."""
        settings = get_settings()
        chain = []

        if getattr(settings, "GROQ_API_KEY", None):
            chain.append({
                "name": "Groq",
                "client": OpenAI(
                    api_key=settings.GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1",
                ),
                "model": "openai/gpt-oss-20b",
            })

        if getattr(settings, "GEMINI_API_KEY", None):
            chain.append({
                "name": "Gemini",
                "client": OpenAI(
                    api_key=settings.GEMINI_API_KEY,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                ),
                "model": "gemini-3.5-flash-lite",
            })

        if getattr(settings, "OPENROUTER_API_KEY", None):
            chain.append({
                "name": "OpenRouter",
                "client": OpenAI(
                    api_key=settings.OPENROUTER_API_KEY,
                    base_url="https://openrouter.ai/api/v1",
                ),
                "model": "openrouter/free",
            })

        logger.info(f"LLM fallback chain initialized: {[p['name'] for p in chain]}")
        return chain

    def _build_prompt(self, job: CleanJob, resume_text: str) -> str:
        """Truncates long descriptions to prevent 413 errors and save tokens."""
        desc_trimmed = job.description_clean[:MAX_DESC_CHARS]
        return (
            f"### CANDIDATE RESUME\n{resume_text}\n\n"
            f"### JOB POSTING\n"
            f"Title: {job.title}\n"
            f"Company: {job.company_canonical}\n"
            f"Location: {job.location or 'Not specified'} (Remote: {job.is_remote})\n"
            f"Description:\n{desc_trimmed}"
        )

    def evaluate_job(
        self, job: CleanJob, resume_text: str
    ) -> Optional[Tuple[LLMMatchResult, str]]:
        """Tries each LLM tier in order until one returns valid Pydantic-checked JSON."""
        user_prompt = self._build_prompt(job, resume_text)

        for provider in self.providers:
            try:
                response = provider["client"].chat.completions.create(
                    model=provider["model"],
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                raw_json = response.choices[0].message.content
                data = json.loads(raw_json)
                result = LLMMatchResult(**data)

                logger.info(
                    f"[{provider['name']}] Scored '{job.title}' @ {job.company_canonical}: {result.match_score}/100"
                )
                time.sleep(self.delay_sec)  # Gentle pacing to avoid 429 rate limits
                return result, provider["name"]

            except Exception as e:
                logger.warning(
                    f"[{provider['name']}] failed for '{job.title}': {e}. Trying next tier..."
                )

        logger.error(f"All LLM tiers failed for '{job.title}' @ {job.company_canonical}")
        return None
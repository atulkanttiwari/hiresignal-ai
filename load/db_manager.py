# Neon PostgreSQL connection, Bronze/Silver/Gold tables, incremental inserts
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Set

from config.settings import get_settings
from models.schemas import ProcessedJob
from utils.logger import get_logger

logger = get_logger(__name__)


class DBManager:
    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path or get_settings().DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    url TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company_canonical TEXT NOT NULL,
                    company_raw TEXT NOT NULL,
                    location TEXT,
                    is_remote INTEGER NOT NULL,
                    posted_at TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    match_score INTEGER NOT NULL,
                    role_family TEXT NOT NULL,
                    is_fresher_friendly INTEGER NOT NULL,
                    matching_skills TEXT NOT NULL,
                    missing_skills TEXT NOT NULL,
                    reasoning TEXT NOT NULL,
                    llm_provider_used TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_match_score ON jobs(match_score DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_posted_at ON jobs(posted_at DESC)"
            )
        logger.info(f"Database initialized at {self.db_path}")

    def get_existing_urls(self) -> Set[str]:
        """Returns all URLs already in the DB for fast O(1) deduplication."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT url FROM jobs").fetchall()
        return {row["url"] for row in rows}

    def save_job(self, job: ProcessedJob) -> bool:
        """Inserts a ProcessedJob. Returns True if inserted, False if duplicate."""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs (
                        url, source, title, company_canonical, company_raw,
                        location, is_remote, posted_at, collected_at,
                        match_score, role_family, is_fresher_friendly,
                        matching_skills, missing_skills, reasoning, llm_provider_used
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.url,
                        job.source,
                        job.title,
                        job.company_canonical,
                        job.company_raw,
                        job.location,
                        int(job.is_remote),
                        job.posted_at.isoformat(),
                        job.collected_at.isoformat(),
                        job.match_score,
                        job.role_family,
                        int(job.is_fresher_friendly),
                        json.dumps(job.matching_skills),
                        json.dumps(job.missing_skills),
                        job.reasoning,
                        job.llm_provider_used,
                    ),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Failed to save job {job.url}: {e}")
            return False

    def get_recent_jobs(self, min_score: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetches top jobs for the Streamlit UI (app.py)."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE match_score >= ?
                ORDER BY posted_at DESC, match_score DESC
                LIMIT ?
                """,
                (min_score, limit),
            ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            item["is_remote"] = bool(item["is_remote"])
            item["is_fresher_friendly"] = bool(item["is_fresher_friendly"])
            item["matching_skills"] = json.loads(item["matching_skills"])
            item["missing_skills"] = json.loads(item["missing_skills"])
            results.append(item)
        return results
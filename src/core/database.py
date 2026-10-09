import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from src.core.schemas import ApplicationStatus, JobPosting, MatchEvaluation


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApplicationStateStore:
    def __init__(self, db_path: str = "data/applications.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    job_title TEXT NOT NULL,
                    location TEXT NOT NULL,
                    job_url TEXT UNIQUE NOT NULL,
                    raw_description TEXT NOT NULL,
                    salary_range TEXT,
                    is_remote INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    discovered_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    job_id TEXT PRIMARY KEY,
                    fit_score INTEGER NOT NULL,
                    matches_hard_criteria INTEGER NOT NULL,
                    key_matching_skills TEXT,
                    missing_critical_skills TEXT,
                    strategic_reasoning TEXT,
                    evaluated_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tailored_resumes (
                    job_id TEXT PRIMARY KEY,
                    executive_summary TEXT NOT NULL,
                    tailored_skills TEXT NOT NULL,
                    selected_experiences TEXT NOT NULL,
                    pdf_compiled_path TEXT,
                    tailored_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    metadata TEXT,
                    timestamp TIMESTAMP NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                """
            )

    def upsert_job(self, job: JobPosting) -> bool:
        now = utc_now_iso()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO jobs (
                    job_id, platform, company_name, job_title, location,
                    job_url, raw_description, salary_range, is_remote, status,
                    discovered_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_url) DO UPDATE SET
                    raw_description = excluded.raw_description,
                    updated_at = excluded.updated_at
                RETURNING job_id;
                """,
                (
                    job.job_id,
                    job.platform,
                    job.company_name,
                    job.job_title,
                    job.location,
                    job.job_url,
                    job.raw_description,
                    job.salary_range,
                    1 if job.is_remote else 0,
                    job.status.value,
                    job.discovered_at.isoformat(),
                    now,
                ),
            )
            row = cursor.fetchone()
            return row is not None

    def update_job_status(self, job_id: str, new_status: ApplicationStatus, metadata: Optional[Dict[str, Any]] = None) -> None:
        now = utc_now_iso()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            current_status = row["status"] if row else None

            # Terminal invariant: once SUBMITTED, never regress or overwrite to FAILED/SKIPPED
            if current_status == ApplicationStatus.SUBMITTED.value and new_status != ApplicationStatus.SUBMITTED:
                return

            cursor.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (new_status.value, now, job_id),
            )

            cursor.execute(
                """
                INSERT INTO audit_logs (job_id, from_status, to_status, metadata, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, current_status, new_status.value, json.dumps(metadata or {}), now),
            )

    def save_evaluation(self, eval_data: MatchEvaluation) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO evaluations (
                    job_id, fit_score, matches_hard_criteria, key_matching_skills,
                    missing_critical_skills, strategic_reasoning, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    fit_score = excluded.fit_score,
                    matches_hard_criteria = excluded.matches_hard_criteria,
                    key_matching_skills = excluded.key_matching_skills,
                    missing_critical_skills = excluded.missing_critical_skills,
                    strategic_reasoning = excluded.strategic_reasoning,
                    evaluated_at = excluded.evaluated_at
                """,
                (
                    eval_data.job_id,
                    eval_data.fit_score,
                    1 if eval_data.matches_hard_criteria else 0,
                    json.dumps(eval_data.key_matching_skills),
                    json.dumps(eval_data.missing_critical_skills),
                    eval_data.strategic_reasoning,
                    eval_data.evaluated_at.isoformat(),
                ),
            )

    def get_job_status(self, job_id: str) -> Optional[ApplicationStatus]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                try:
                    return ApplicationStatus(row["status"])
                except ValueError:
                    return None
            return None

    def count_recent_submissions(self, hours: int = 24) -> int:
        """Counts how many applications reached SUBMITTED status within the past N hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM jobs WHERE status = ? AND updated_at >= ?",
                (ApplicationStatus.SUBMITTED.value, cutoff),
            )
            row = cursor.fetchone()
            return row["count"] if row else 0

    def get_jobs_by_status(self, status: ApplicationStatus) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE status = ? ORDER BY discovered_at ASC", (status.value,))
            return [dict(row) for row in cursor.fetchall()]
import json
import os
from typing import Any, Dict
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel
from src.core.schemas import MatchEvaluation, TailoredResume

load_dotenv()


class GeminiFlashClient:
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is missing.")
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = model_name

    def evaluate_job_match(self, job_id: str, job_title: str, company: str, description: str, candidate_summary: str, truth_matrix: Dict[str, Any]) -> MatchEvaluation:
        """Evaluates semantic fit and hard constraints using Gemini 2.5 Flash."""
        prompt = f"""
        You are an expert Staff-Level Career Agent. Evaluate if the following Job Posting matches the Candidate Profile.

        CANDIDATE TRUTH & BOUNDARIES:
        {json.dumps(truth_matrix, indent=2)}

        CANDIDATE EXPERIENCE SUMMARY:
        {candidate_summary}

        JOB DETAILS:
        Company: {company}
        Title: {job_title}
        Description:
        {description}

        INSTRUCTIONS:
        1. Evaluate hard constraints (Location, Visa/Work Auth, Seniority level).
        2. Calculate a fit_score from 0 to 100 based on technical and architectural alignment.
        3. Identify matching skills and critical missing skills.
        4. Provide brief strategic reasoning.
        """

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=MatchEvaluation,
            ),
        )

        return MatchEvaluation.model_validate_json(response.text)

    def tailor_resume_content(self, job_id: str, job_title: str, company: str, description: str, master_resume: Dict[str, Any]) -> TailoredResume:
        """Tailors the executive summary and selects/orders real resume bullets without hallucination."""
        prompt = f"""
        You are an elite Staff AI Resume Architect. Tailor the candidate's resume for the target job description.

        STRICT TRUTH GUARDRAIL:
        - NEVER invent technologies, metrics, or experiences the candidate did not perform.
        - Reorder and emphasize ONLY real bullet points from the master resume.
        - Tailor the executive summary to highlight relevant overlap with this specific role.

        TARGET JOB:
        Company: {company}
        Title: {job_title}
        Description:
        {description}

        MASTER RESUME DATA:
        {json.dumps(master_resume, indent=2)}
        """

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=TailoredResume,
            ),
        )

        return TailoredResume.model_validate_json(response.text)
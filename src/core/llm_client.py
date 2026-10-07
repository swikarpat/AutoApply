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
        self.model_name = model_name
        self.client = None
        self.is_active = False

        if self.api_key and not self.api_key.startswith("your_"):
            try:
                self.client = genai.Client(api_key=self.api_key)
                self.is_active = True
            except Exception as e:
                print(f"[Warning] Failed to initialize Google GenAI Client: {e}")

    def resolve_form_question(self, question: str, options: list[str] | None, truth_matrix: Dict[str, Any]) -> str:
        """Determines the most accurate answer for an unexpected form question given candidate background."""
        if not self.is_active or not self.client:
            return ""

        prompt = f"""
        You are an autonomous job applicant answering a question on a job application.
        
        CANDIDATE TRUTH PROFILE:
        {json.dumps(truth_matrix, indent=2)}

        APPLICATION QUESTION:
        {question}

        AVAILABLE OPTIONS (if multiple choice):
        {json.dumps(options or [], indent=2)}

        INSTRUCTIONS:
        - Return ONLY the exact answer string or option value.
        - For questions about authorization to work, answer 'Yes'.
        - For questions about requiring visa sponsorship now or in the future, answer 'No'.
        - For voluntary demographic/disability questions, answer 'Decline' or 'I do not wish to answer' if available.
        - If numeric years of experience is requested and not listed, respond with 6.
        - Do not provide any conversational preamble. Return only the answer value.
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                ),
            )
            return response.text.strip().strip('"').strip("'")
        except Exception as e:
            print(f"[LLM Form Resolver Warning] {e}")
            return ""

    def evaluate_job_match(self, job_id: str, job_title: str, company: str, description: str, candidate_summary: str, truth_matrix: Dict[str, Any]) -> MatchEvaluation:
        """Evaluates semantic fit and hard constraints using Gemini 2.5 Flash."""
        if not self.is_active or not self.client:
            raise RuntimeError("Gemini Client is not active or GEMINI_API_KEY is not configured.")

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
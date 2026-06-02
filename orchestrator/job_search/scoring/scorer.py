"""
Scoring LLM par critères atomiques.

Le LLM note chaque critère (0-10) + mini-justification.
Le score global est agrégé côté code (jamais produit en bloc par le LLM).
Parsing défensif : retry + fallback score=0 / parse_failed=True.
"""
import json
import os
import warnings
from dataclasses import dataclass, field

import ollama
from dotenv import load_dotenv

from dataclasses import dataclass as _dataclass

from orchestrator.job_search.matching.profile import Profile


@_dataclass
class CriterionConfig:
    key: str
    weight: float
from orchestrator.job_search.sources.base import JobOffer

load_dotenv()

_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_SYSTEM_PROMPT = """\
You are a recruiter assistant. You will receive a job offer and a candidate profile.
Score ONLY the requested criterion on a scale from 0 to 10.
Reply with a single valid JSON object, nothing else:
{"key": "<criterion_key>", "score": <int 0-10>, "justification": "<one sentence>"}
"""

_FEW_SHOT = """\
Example:
Criterion: stack_fit
Job: Senior Python developer, FastAPI, Docker, AWS
Profile: Python, LLM, RAG, FastAPI, Docker — mid level
{"key": "stack_fit", "score": 8, "justification": "Strong Python/FastAPI/Docker match; AWS not in profile but minor gap."}
"""


@dataclass
class CriterionResult:
    key: str
    score: float          # 0-10
    justification: str
    parse_failed: bool = False


@dataclass
class ScoringResult:
    offer_id: str
    global_score: float   # 0-100, weighted sum
    criteria: list[CriterionResult] = field(default_factory=list)
    parse_failed: bool = False  # True if ANY criterion failed


def _score_criterion(
    client: ollama.Client,
    model: str,
    offer: JobOffer,
    profile: Profile,
    criterion: CriterionConfig,
    retries: int = 2,
) -> CriterionResult:
    prompt = (
        f"{_FEW_SHOT}\n"
        f"Criterion: {criterion.key}\n"
        f"Job title: {offer.title}\n"
        f"Job description (excerpt): {offer.description[:800]}\n"
        f"Candidate profile: {profile.title}, {profile.seniority} level, "
        f"stack={profile.stack}\n"
        f"Score the criterion '{criterion.key}' now:"
    )

    for attempt in range(retries + 1):
        try:
            resp = client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.1},
            )
            raw = resp.message.content.strip()
            # Strip markdown fences if model wraps in ```json ... ```
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            score = max(0.0, min(10.0, float(data["score"])))
            return CriterionResult(
                key=criterion.key,
                score=score,
                justification=str(data.get("justification", "")),
            )
        except Exception as exc:
            if attempt == retries:
                warnings.warn(
                    f"[scorer] parse failed for criterion '{criterion.key}' "
                    f"on offer '{offer.source_id}': {exc}"
                )
    return CriterionResult(
        key=criterion.key, score=0.0, justification="", parse_failed=True
    )


def score_offer(
    offer: JobOffer,
    profile: Profile,
    model: str = _DEFAULT_MODEL,
    host: str = _DEFAULT_HOST,
) -> ScoringResult:
    """Score a single offer against a profile. Never raises — returns parse_failed on error."""
    client = ollama.Client(host=host)
    results: list[CriterionResult] = []

    for criterion in profile.criteria:
        result = _score_criterion(client, model, offer, profile, criterion)
        results.append(result)

    # Aggregate — score global calculé côté code, jamais par le LLM
    global_score = sum(
        (r.score / 10.0) * c.weight
        for r, c in zip(results, profile.criteria)
    ) * 100.0

    any_failed = any(r.parse_failed for r in results)
    return ScoringResult(
        offer_id=offer.source_id,
        global_score=round(global_score, 1),
        criteria=results,
        parse_failed=any_failed,
    )


def criteria_to_json(result: ScoringResult) -> str:
    """Serialize criteria for storage in offers.criteria_json."""
    return json.dumps([
        {
            "key": r.key,
            "score": r.score,
            "justification": r.justification,
            "parse_failed": r.parse_failed,
        }
        for r in result.criteria
    ])

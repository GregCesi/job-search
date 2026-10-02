"""
Extraction LLM des faits intrinsèques d'une offre (architecture.md §4).

Un seul appel par offre, à l'ingestion. Résultat persisté sur `offers`.
Jamais recalculé sauf si l'offre change.
"""

import hashlib
import json
import os
import warnings
from datetime import datetime, timezone

import ollama
from dotenv import load_dotenv

from orchestrator.job_search.scoring.tracing import TRACE_PATH, LLMTrace, _write_trace
from orchestrator.job_search.sources.base import (
    ExtractedFacts,
    JobOffer,
    RoleLevel,
    SeniorityLevel,
    TechRequirement,
)

load_dotenv()

_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:12b")
_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# Fenêtre fixée explicitement : le défaut d'Ollama change selon sa version et
# tronque en silence (TCK-200, offre 2874 sous 0.22.0). Prompt max ≈ 4000 tokens
# (description plafonnée à 8000 chars + système + few-shot), réponse JSON < 1000.
_NUM_CTX = 8192

_SYSTEM_PROMPT = """\
You are a technical job offer analyzer. Extract facts from the job offer — no scoring, no opinion.
Reply with a single valid JSON object, nothing else:
{
  "seniority_required": "<junior|intermediate|senior|lead>",
  "techs_required": [
    {"name": "<tech>", "importance": "<core|required|nice_to_have>"},
    ...
  ],
  "domain": "<ai_engineering|data_engineering|data_science|backend|devops|fullstack|embedded|other>",
  "role_level": "<ic|lead|manager>",
  "langues_requises": ["<language>", ...]
}

Rules:
- seniority_required: junior=0-2 yrs, intermediate=2-5 yrs, senior=5-10 yrs, lead=tech lead or 10+ yrs or management.
- techs_required: specific technology names only. Include implicit ones \
(e.g. "RAG architectures" → "rag", "orchestration de flux" → "airflow"). All lowercase.
  importance values:
    core         = central to the role — explicitly required, mentioned multiple times, or the main stack
    required     = needed but secondary — must have, but not the focus
    nice_to_have = optional — "idéalement", "un plus", "apprécié", bonus
- domain: single best fit from the allowed values only.
- role_level:
    ic      = individual contributor — no team management
    lead    = tech lead / squad lead — technical leadership of a team, but may have no reports
    manager = people management — hiring, reviews, headcount responsibility
- langues_requises: list of human languages explicitly required by the offer \
(e.g. ["français", "anglais", "allemand"]). Use the French name of each language. \
Empty list if no language requirement is stated.
"""

_FEW_SHOT = """\
Example 1 — IC role, mixed importance:
Title: Développeur IA / LLM (H/F)
Description: Vous concevez des architectures RAG en production avec LangGraph et FastAPI. \
Stack cœur : Python, LangChain, LangGraph, PostgreSQL, Docker. \
Maîtrise de Python et LangChain exigée. Git souhaité. Kubernetes serait un plus.
Experience hint: Souhaitée
→ {"seniority_required": "intermediate", "techs_required": [{"name": "python", "importance": "core"}, {"name": "rag", "importance": "core"}, {"name": "langchain", "importance": "core"}, {"name": "langgraph", "importance": "required"}, {"name": "fastapi", "importance": "required"}, {"name": "postgresql", "importance": "required"}, {"name": "docker", "importance": "required"}, {"name": "git", "importance": "required"}, {"name": "kubernetes", "importance": "nice_to_have"}], "domain": "ai_engineering", "role_level": "ic", "langues_requises": []}

Example 2 — Tech lead role:
Title: Tech Lead Data / ML (H/F)
Description: Vous pilotez une équipe de 5 data engineers. Référent technique sur notre stack Spark/Databricks. \
Recrutement et montée en compétences de l'équipe. Expertise Python et Spark indispensable. SQL, Airflow requis. Kafka apprécié.
Experience hint: Exigée
→ {"seniority_required": "lead", "techs_required": [{"name": "python", "importance": "core"}, {"name": "spark", "importance": "core"}, {"name": "databricks", "importance": "required"}, {"name": "sql", "importance": "required"}, {"name": "airflow", "importance": "required"}, {"name": "kafka", "importance": "nice_to_have"}], "domain": "data_engineering", "role_level": "lead", "langues_requises": ["français", "anglais"]}

Example 3 — Backend IC, legacy stack:
Title: Développeur Java Backend (H/F)
Description: Développement de microservices Java/Spring Boot, exposition REST, intégration PostgreSQL. \
Docker et CI/CD Jenkins sont utilisés. Angular côté client (équipe frontend dédiée, vous n'y touchez pas). \
Kafka ou RabbitMQ serait un plus.
Experience hint: Souhaitée
→ {"seniority_required": "intermediate", "techs_required": [{"name": "java", "importance": "core"}, {"name": "spring", "importance": "core"}, {"name": "postgresql", "importance": "required"}, {"name": "docker", "importance": "required"}, {"name": "jenkins", "importance": "required"}, {"name": "kafka", "importance": "nice_to_have"}, {"name": "rabbitmq", "importance": "nice_to_have"}], "domain": "backend", "role_level": "ic", "langues_requises": []}
"""

# Version du vocabulaire de sortie. À incrémenter à chaque changement de champ
# ou d'énumération rendus par le modèle (TCK-211).
SCHEMA_VERSION = 1
_TEMPERATURE = 0.1


def extraction_version(model: str = _DEFAULT_MODEL) -> str:
    """Identifie une extraction : modèle + empreinte (prompts, num_ctx, température) + schéma.

    Deux offres de même version ont été extraites dans les mêmes conditions.
    Changer le prompt, le modèle ou le schéma change la version : la réextraction
    ciblée (`rescore --re-extract-stale`) sait alors quelles offres refaire.
    """
    payload = f"{_SYSTEM_PROMPT}\n{_FEW_SHOT}\nctx={_NUM_CTX}\ntemp={_TEMPERATURE}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"{model}|p{digest}|s{SCHEMA_VERSION}"


class OllamaUnavailable(RuntimeError):
    """Ollama injoignable, ou un modèle configuré n'y est pas installé (EXE-99)."""


def ensure_models_available(host: str, models: list[str]) -> None:
    """Lève `OllamaUnavailable` si Ollama n'est pas joignable sur `host`, ou si
    l'un des `models` n'y est pas installé. Aucun appel au LLM — lecture seule
    de la liste des modèles installés (architecture.md, exception TCK-273)."""
    client = ollama.Client(host=host)
    try:
        response = client.list()
    except Exception as exc:
        raise OllamaUnavailable(f"Ollama injoignable sur {host} : {exc}") from exc

    raw_models = getattr(response, "models", None)
    if raw_models is None and isinstance(response, dict):
        raw_models = response.get("models", [])
    raw_models = raw_models or []

    installed: set[str] = set()
    for entry in raw_models:
        name = getattr(entry, "model", None)
        if name is None and isinstance(entry, dict):
            name = entry.get("model") or entry.get("name")
        if name:
            installed.add(name)

    def _present(wanted: str) -> bool:
        return wanted in installed or any(
            name == f"{wanted}:latest" or name.split(":")[0] == wanted
            for name in installed
        )

    missing = [m for m in models if not _present(m)]
    if missing:
        raise OllamaUnavailable("Modèle(s) Ollama manquant(s) : " + ", ".join(missing))


_SENIORITY_VALID = {s.value for s in SeniorityLevel}
_ROLE_VALID = {r.value for r in RoleLevel}
_IMPORTANCE_VALID = {"core", "required", "nice_to_have"}
_DOMAIN_VALID = {
    "ai_engineering",
    "data_engineering",
    "data_science",
    "backend",
    "devops",
    "fullstack",
    "embedded",
    "other",
}
_EXPERIENCE_HINT = {"D": "Débutant accepté", "S": "Souhaitée", "E": "Exigée"}


def extract_facts(
    offer: JobOffer,
    model: str = _DEFAULT_MODEL,
    host: str = _DEFAULT_HOST,
    retries: int = 2,
) -> ExtractedFacts | None:
    """Extract intrinsic facts from a job offer. Never raises.

    None = extraction en échec : aucune réponse lisible après les `retries + 1`
    tentatives (architecture.md, exception TCK-273). Aucun fait de repli n'est
    retourné ni scoré — c'est à l'appelant de laisser l'offre à refaire."""
    client = ollama.Client(host=host)

    hints: list[str] = []
    if offer.experience_required:
        hints.append(
            f"Experience hint: {_EXPERIENCE_HINT.get(offer.experience_required, offer.experience_required)}"
        )
    if offer.rome_label:
        hints.append(f"ROME classification: {offer.rome_label}")
    if offer.alternance:
        hints.append("Note: this is an apprenticeship offer (alternance).")

    user_prompt = (
        f"{_FEW_SHOT}\n"
        f"Title: {offer.title}\n"
        # Garde-fou sécurité, pas troncature métier : 8000 chars ≈ 2000 tokens,
        # sous 50 % de la fenêtre 8192-token. Aucune offre réelle n'atteint ce seuil.
        f"Description: {offer.description[:8000]}\n"
        + ("\n".join(hints) + "\n" if hints else "")
        + "Extract facts now:"
    )

    _last_raw = ""
    for attempt in range(retries + 1):
        try:
            resp = client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": _TEMPERATURE, "num_ctx": _NUM_CTX},
                # Raisonnement coupé : sur gemma4:12b il consomme la fenêtre et
                # rend une réponse vide (done_reason=length, TCK-200).
                think=False,
            )
            _last_raw = resp.message.content
            raw = resp.message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            if raw.startswith("→"):
                raw = raw.lstrip("→").strip()
            data = json.loads(raw)

            _degraded = False

            seniority_raw = str(data.get("seniority_required", "")).lower()
            if seniority_raw in _SENIORITY_VALID:
                seniority = SeniorityLevel(seniority_raw)
            else:
                seniority = SeniorityLevel.intermediate
                _degraded = True

            raw_techs = data.get("techs_required", [])
            techs: list[TechRequirement] = []
            for item in raw_techs:
                if isinstance(item, str):
                    # Model ignored the dict format — format degradation
                    name = item.lower().strip()
                    if name:
                        techs.append(TechRequirement(name=name, importance="required"))
                        _degraded = True
                elif isinstance(item, dict):
                    name = str(item.get("name", "")).lower().strip()
                    importance = str(item.get("importance", "")).lower()
                    if name:
                        if importance in _IMPORTANCE_VALID:
                            techs.append(
                                TechRequirement(name=name, importance=importance)
                            )
                        else:
                            techs.append(
                                TechRequirement(name=name, importance="required")
                            )
                            _degraded = True

            domain_raw = str(data.get("domain", "")).lower()
            if domain_raw in _DOMAIN_VALID:
                domain = domain_raw
            else:
                domain = "other"
                _degraded = True

            role_raw = str(data.get("role_level", "ic")).lower()
            if role_raw in _ROLE_VALID:
                role_level = RoleLevel(role_raw)
            else:
                role_level = RoleLevel.ic
                _degraded = True

            raw_langues = data.get("langues_requises", [])
            langues_requises: list[str] = []
            if isinstance(raw_langues, list):
                langues_requises = [
                    str(lang).strip()
                    for lang in raw_langues
                    if isinstance(lang, str) and lang.strip()
                ]

            facts = ExtractedFacts(
                seniority_required=seniority,
                techs_required=techs,
                domain=domain,
                role_level=role_level,
                langues_requises=langues_requises,
                parse_failed=_degraded,
            )
            _write_trace(
                LLMTrace(
                    offer_id=offer.source_id,
                    model=model,
                    extraction_version=extraction_version(model),
                    temperature=_TEMPERATURE,
                    prompt_system=_SYSTEM_PROMPT,
                    prompt_user=user_prompt,
                    raw_response=_last_raw,
                    parsed_facts=facts.model_dump(),
                    parse_failed=_degraded,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ),
                TRACE_PATH,
            )
            return facts
        except Exception as exc:
            if attempt == retries:
                warnings.warn(
                    f"[extractor] parse failed on offer '{offer.source_id}': {exc}"
                )

    # Aucune réponse lisible après les `retries + 1` tentatives — échec, pas de
    # fait de repli (architecture.md, exception TCK-273) : l'offre reste à refaire.
    _write_trace(
        LLMTrace(
            offer_id=offer.source_id,
            model=model,
            extraction_version=extraction_version(model),
            temperature=_TEMPERATURE,
            prompt_system=_SYSTEM_PROMPT,
            prompt_user=user_prompt,
            raw_response=_last_raw,
            parsed_facts={},
            parse_failed=True,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        TRACE_PATH,
    )
    return None

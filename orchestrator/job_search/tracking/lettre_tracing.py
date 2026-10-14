"""Trace MLflow d'une génération de lettre de l'app (EXE-174) — distincte du
suivi par run (`mlflow_tracking.py`, expérience `run-pipeline`) et du banc
(`lettre/banc.py`, expérience `lettre-banc`) : sa propre expérience, un span
par appel de modèle de la génération (nœud, modèle, tour, durée, coût, demande,
réponse), reconstruit après coup depuis la liste d'`Appel` déjà collectée par
la boucle — jamais ouvert dans `boucle.py`, pour ne jamais tracer le banc.

Même contrat d'à-côté que `mlflow_tracking.py` (architecture.md, invariants de
persistance) : si MLflow ne peut pas écrire, la génération va au bout sans
trace — `tracer_generation` avale ses propres exceptions et rend `None`.
"""

from __future__ import annotations

import time
from typing import Any

import mlflow
from mlflow.entities import SpanType
from mlflow.tracking import MlflowClient

from orchestrator.job_search.tracking.mlflow_tracking import _artifact_root_for

EXPERIMENT_NAME = "lettre-app"


def _experiment_id(client: MlflowClient) -> str:
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is not None:
        return experiment.experiment_id
    return client.create_experiment(
        EXPERIMENT_NAME,
        artifact_location=_artifact_root_for(mlflow.get_tracking_uri()),
    )


def tracer_generation(
    appels: list[dict[str, Any]],
    *,
    offer_id: int,
    mode: str,
    modele_redaction: str,
    modele_juge: str,
    raison_fin: str,
) -> str | None:
    """Un span par appel (critère 6), dans l'ordre reçu. La trace porte l'offre,
    le mode de génération, les deux modèles et la raison de fin (critère 7).
    Rend `None` sans lever si `appels` est vide, ou si MLflow ne peut pas
    écrire (critère 9) — jamais d'exception remontée à l'appelant."""
    if not appels:
        return None
    try:
        client = MlflowClient()
        experiment_id = _experiment_id(client)

        debut_ns = time.time_ns()
        racine = client.start_trace(
            name="lettre",
            span_type=SpanType.CHAIN,
            inputs={"offer_id": offer_id, "mode": mode},
            attributes={
                "offer_id": str(offer_id),
                "mode": mode,
                "modele_redaction": modele_redaction,
                "modele_juge": modele_juge,
                "raison_fin": raison_fin,
            },
            experiment_id=experiment_id,
            start_time_ns=debut_ns,
        )
        trace_id = racine.trace_id
        curseur_ns = debut_ns
        for appel in appels:
            duree_ns = max(int(appel["duree_s"] * 1_000_000_000), 1)
            span = client.start_span(
                name=f"{appel['noeud']}-tour{appel['tour']}",
                trace_id=trace_id,
                parent_id=racine.span_id,
                span_type=SpanType.LLM,
                inputs={"demande": appel["demande"]},
                attributes={
                    "noeud": appel["noeud"],
                    "modele": appel["modele"],
                    "tour": appel["tour"],
                    "duree_s": appel["duree_s"],
                    "cout_usd": appel["cout_usd"],
                },
                start_time_ns=curseur_ns,
            )
            curseur_ns += duree_ns
            client.end_span(
                trace_id=trace_id,
                span_id=span.span_id,
                outputs={"reponse": appel["reponse"]},
                end_time_ns=curseur_ns,
            )
        client.end_trace(
            trace_id=trace_id,
            outputs={"nb_appels": len(appels)},
            end_time_ns=curseur_ns,
        )
        # Lecture immédiate possible (critère 13) : la trace est écrite avant
        # que la fonction ne rende la main, pas seulement mise en file.
        mlflow.flush_trace_async_logging()
        return trace_id
    except Exception as exc:  # noqa: BLE001 — à-côté du run, jamais bloquant
        print(f"[lettre] suivi MLflow a échoué : {exc}")
        return None

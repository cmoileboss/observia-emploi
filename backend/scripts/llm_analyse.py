"""Associe des formations à une offre d'emploi via un appel LLM (Groq)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from fastapi import HTTPException
from groq import Groq
from groq import RateLimitError

from models.correspondance_formation_model import FormationModel
from models.francetravail_model import OffreModel

DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_TOP_K = 3
_DESC_MAX_CHARS = 800

_SYSTEM_PROMPT = (
    "Tu es un conseiller en orientation professionnelle expert du marché de l'emploi français. "
    "Tu reçois une offre d'emploi et une liste de formations certifiantes. "
    "Ta mission : identifier les formations les plus pertinentes pour préparer un candidat à ce poste. "
    "Réponds uniquement en JSON valide, sans texte autour."
)


@dataclass
class FormationMatch:
    """Résultat d'association d'une formation à une offre."""

    formation: FormationModel
    justification: str
    rang: int


def _build_user_prompt(
    offre: OffreModel,
    formations: list[FormationModel],
    top_k: int,
) -> str:
    """Construit le prompt utilisateur à partir des données métier."""
    competences = (
        ", ".join(c.libelle for c in offre.competences if c.libelle)
        if offre.competences
        else "non renseignées"
    )
    description = (offre.description or "non renseignée")[:_DESC_MAX_CHARS]

    lines_formations = "\n".join(
        "{i}. [{niveau}] {intitule} — {organisme}".format(
            i=i + 1,
            niveau=f.niveau_rncp or "?",
            intitule=f.intitule_certification or "—",
            organisme=f.nom_entreprise or f.raison_sociale_of_contractant or "—",
        )
        for i, f in enumerate(formations)
    )

    return (
        "## Offre d'emploi\n"
        f"- Intitulé : {offre.intitule}\n"
        f"- Appellation : {offre.appellation_libelle}\n"
        f"- Code ROME : {offre.rome_code} — {offre.rome_libelle}\n"
        f"- Compétences requises : {competences}\n"
        f"- Description : {description}\n"
        "\n"
        "## Formations candidates\n"
        f"{lines_formations}\n"
        "\n"
        "## Consigne\n"
        f"Sélectionne les {top_k} formations les plus adaptées à cette offre.\n"
        "Pour chaque formation retenue, indique :\n"
        '- "rang" (1 = meilleure)\n'
        '- "index" (numéro dans la liste ci-dessus, 1-based)\n'
        '- "justification" (1 phrase, en français)\n'
        "\n"
        'Format attendu :\n'
        '{"selections": [{"rang": 1, "index": 3, "justification": "..."}, ...]}'
    )


def link_offre_to_formations(
    offre: OffreModel,
    candidate_formations: list[FormationModel],
    top_k: int = DEFAULT_TOP_K,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> list[FormationMatch]:
    """Appelle le LLM pour associer les meilleures formations à une offre.

    Args:
        offre: L'offre d'emploi source.
        candidate_formations: Liste des formations candidates à évaluer.
        top_k: Nombre de formations à retenir.
        model: Identifiant du modèle Groq.
        api_key: Clé API Groq (utilise GROQ_API_KEY si None).

    Returns:
        Liste de FormationMatch triée par rang croissant.
    """
    if not candidate_formations:
        return []

    client = Groq(api_key=api_key or os.environ["GROQ_API_KEY"])

    user_prompt = _build_user_prompt(offre, candidate_formations, top_k)
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except RateLimitError as exc:
        raise HTTPException(
            status_code=503,
            detail="Le service LLM est temporairement indisponible (quota dépassé). Réessayez plus tard.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erreur API Groq : {exc}") from exc

    data = json.loads(completion.choices[0].message.content)
    selections = data.get("selections", [])

    matches: list[FormationMatch] = []
    for sel in selections:
        idx = sel.get("index")
        rang = sel.get("rang")
        justification = sel.get("justification", "")

        if idx is None or not (1 <= idx <= len(candidate_formations)):
            continue

        matches.append(
            FormationMatch(
                formation=candidate_formations[idx - 1],
                justification=justification,
                rang=rang,
            )
        )

    return sorted(matches, key=lambda m: m.rang)

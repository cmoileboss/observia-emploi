"""."""
from __future__ import annotations

import csv
import hashlib
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.scripts.matching_normalization import normaliser_description, normaliser_titre


CLASSIFIER_VERSION = "free_work_rome_deterministic_v1_final"
CALIBRATION_SEED = "observia-free-work-rome-v1-20260625"

TITLE_WEIGHT = 55.0
SKILL_WEIGHT = 30.0
DESCRIPTION_WEIGHT = 15.0

MIN_CANDIDATE_SCORE = 20.0
REVIEW_MARGIN = 8.0
MIN_AUTO_SCORE = 60.0
MIN_AUTO_MARGIN = 5.0
MIN_CALIBRATION_AUTO_ASSIGNED = 5
GENERIC_TITLE_TOKENS = {
    "developpeur",
    "developer",
    "consultant",
    "ingenieur",
    "chef",
    "projet",
    "data",
    "technicien",
    "administrateur",
}
STOP_WORDS = {
    "avec",
    "aux",
    "chez",
    "dans",
    "des",
    "dune",
    "dun",
    "elle",
    "elles",
    "est",
    "ils",
    "les",
    "leur",
    "leurs",
    "mais",
    "notre",
    "nous",
    "par",
    "plus",
    "pour",
    "sans",
    "ses",
    "son",
    "sont",
    "sous",
    "sur",
    "une",
    "vers",
    "vos",
    "vous",
}

PROGRESS_FILE_NAME = "rome_classification_progress.json"


@dataclass(frozen=True)
class ClassificationConfig:
    """."""
    name: str
    title_weight: float
    skill_weight: float
    description_weight: float
    auto_score_threshold: float
    auto_margin_threshold: float
    common_token_ratio: float = 0.35
    exact_title_bonus: float = 0.0
    require_discriminant_signal: bool = True


BASELINE_CONFIG = ClassificationConfig(
    name="BASELINE",
    title_weight=TITLE_WEIGHT,
    skill_weight=SKILL_WEIGHT,
    description_weight=DESCRIPTION_WEIGHT,
    auto_score_threshold=MIN_CANDIDATE_SCORE,
    auto_margin_threshold=REVIEW_MARGIN,
    common_token_ratio=1.1,
    exact_title_bonus=0.0,
    require_discriminant_signal=False,
)

V1_A_CONFIG = ClassificationConfig(
    name="DETERMINISTIC_V1_A",
    title_weight=65.0,
    skill_weight=10.0,
    description_weight=25.0,
    auto_score_threshold=MIN_AUTO_SCORE,
    auto_margin_threshold=MIN_AUTO_MARGIN,
    common_token_ratio=0.35,
    exact_title_bonus=8.0,
)

V1_B_CONFIG = ClassificationConfig(
    name="DETERMINISTIC_V1_B",
    title_weight=70.0,
    skill_weight=10.0,
    description_weight=20.0,
    auto_score_threshold=MIN_AUTO_SCORE,
    auto_margin_threshold=MIN_AUTO_MARGIN,
    common_token_ratio=0.30,
    exact_title_bonus=10.0,
)

DEFAULT_CONFIG = V1_A_CONFIG


@dataclass(frozen=True)
class RomeProfile:
    """."""
    rome_code: str
    rome_label: str | None
    occupation_labels: tuple[str, ...]
    observed_job_titles: tuple[str, ...]
    observed_skills: tuple[str, ...]
    source_counts: dict[str, int]
    title_tokens: frozenset[str]
    skill_tokens: frozenset[str]
    description_tokens: frozenset[str]
    exact_title_values: frozenset[str]

    def public_dict(self) -> dict[str, Any]:
        """."""
        return {
            "rome_code": self.rome_code,
            "rome_label": self.rome_label,
            "occupation_labels": list(self.occupation_labels),
            "observed_job_titles": list(self.observed_job_titles),
            "observed_skills": list(self.observed_skills),
            "source_counts": dict(sorted(self.source_counts.items())),
        }


def sha256_file(path: Path) -> str:
    """."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_list(path: Path, label: str) -> list[dict[str, Any]]:
    """."""
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"{label} doit être une liste JSON.")
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"{label}[{index}] doit être un objet JSON.")
    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} doit être un objet JSON.")
            rows.append(row)
    return rows


def write_json(path: Path, payload: Any) -> None:
    """."""
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    write_bytes_atomic(path, content)


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        tmp_path.write_bytes(content)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def normalize_tokens(text: str | None, *, mode: str = "description") -> tuple[str, ...]:
    """."""
    if mode == "title":
        normalized = normaliser_titre(text)
    else:
        normalized = normaliser_description(text)
    tokens = []
    for token in normalized.split():
        if len(token) < 3 or token.isdigit() or token in STOP_WORDS:
            continue
        tokens.append(token)
    return tuple(sorted(set(tokens)))


def skill_tokens(skills: list[dict[str, Any]] | None) -> tuple[str, ...]:
    """."""
    if not isinstance(skills, list):
        return ()
    tokens: set[str] = set()
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        for key in ("name_normalized", "name", "slug"):
            tokens.update(normalize_tokens(skill.get(key), mode="description"))
    return tuple(sorted(tokens))


def is_generic_title(title: str | None, skills: tuple[str, ...]) -> bool:
    """."""
    tokens = set(normalize_tokens(title, mode="title"))
    if skills:
        return False
    return len(tokens) <= 1 or bool(tokens) and tokens.issubset(GENERIC_TITLE_TOKENS)


def read_rome_reference(csv_path: Path) -> dict[str, dict[str, Any]]:
    """."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Référentiel ROME introuvable : {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        required = {"code_rome", "intitule_rome", "intitule_rncp"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"Colonnes ROME manquantes dans {csv_path}: {sorted(required)}")
        profiles: dict[str, dict[str, Any]] = {}
        for row in reader:
            code = str(row.get("code_rome") or "").strip()
            if not code:
                continue
            profile = profiles.setdefault(
                code,
                {
                    "rome_label": str(row.get("intitule_rome") or "").strip() or None,
                    "occupation_labels": set(),
                    "csv_rows": 0,
                },
            )
            profile["csv_rows"] += 1
            label = str(row.get("intitule_rome") or "").strip()
            if label and not profile["rome_label"]:
                profile["rome_label"] = label
            occupation = str(row.get("intitule_rncp") or "").strip()
            if occupation:
                profile["occupation_labels"].add(occupation)
    return profiles


def validate_france_travail_snapshot(rows: list[dict[str, Any]]) -> None:
    """."""
    seen = set()
    for index, row in enumerate(rows):
        for key in ("france_travail_id", "title", "description", "rome_code"):
            if key not in row:
                raise ValueError(
                    f"Clé '{key}' manquante dans le snapshot France Travail à l'index {index}."
                )
        france_travail_id = str(row["france_travail_id"]).strip()
        if not france_travail_id:
            raise ValueError(f"france_travail_id vide à l'index {index}.")
        if france_travail_id in seen:
            raise ValueError(f"france_travail_id dupliqué : {france_travail_id}")
        seen.add(france_travail_id)
        if not str(row.get("rome_code") or "").strip():
            raise ValueError(f"rome_code manquant pour l'offre France Travail {france_travail_id}.")


def validate_free_work_offers(rows: list[dict[str, Any]]) -> None:
    """."""
    seen = set()
    for index, row in enumerate(rows):
        for key in ("source_id", "title"):
            if key not in row:
                raise ValueError(f"Clé '{key}' manquante dans l'offre Free-Work à l'index {index}.")
        source_id = str(row["source_id"]).strip()
        if not source_id:
            raise ValueError(f"source_id vide à l'index {index}.")
        if source_id in seen:
            raise ValueError(f"source_id dupliqué : {source_id}")
        seen.add(source_id)


def top_values(counter: Counter[str], limit: int) -> tuple[str, ...]:
    """."""
    return tuple(value for value, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit])  # pylint: disable=line-too-long


def build_rome_profiles(
    france_travail_rows: list[dict[str, Any]],
    rome_reference_csv: Path,
    config: ClassificationConfig = DEFAULT_CONFIG,
) -> list[RomeProfile]:
    """."""
    validate_france_travail_snapshot(france_travail_rows)
    reference = read_rome_reference(rome_reference_csv)

    titles_by_code: dict[str, Counter[str]] = defaultdict(Counter)
    desc_tokens_by_code: dict[str, Counter[str]] = defaultdict(Counter)
    skills_by_code: dict[str, Counter[str]] = defaultdict(Counter)
    counts_by_code: Counter[str] = Counter()

    for row in france_travail_rows:
        code = str(row["rome_code"]).strip()
        counts_by_code[code] += 1
        title = str(row.get("title") or "").strip()
        if title:
            titles_by_code[code][title] += 1
        for token in normalize_tokens(row.get("description"), mode="description"):
            desc_tokens_by_code[code][token] += 1
        for skill in row.get("competences") or row.get("skills") or []:
            if isinstance(skill, dict):
                label = skill.get("libelle") or skill.get("name")
                for token in normalize_tokens(label, mode="description"):
                    skills_by_code[code][token] += 1

    profiles = []
    for code in sorted(counts_by_code):
        ref = reference.get(code, {"rome_label": None, "occupation_labels": set(), "csv_rows": 0})
        rome_label = ref.get("rome_label")
        occupation_labels = tuple(sorted(ref.get("occupation_labels") or []))
        observed_titles = top_values(titles_by_code[code], 80)
        observed_skills = top_values(skills_by_code[code], 80)

        title_tokens = set(normalize_tokens(rome_label, mode="title"))
        skill_profile_tokens = set(normalize_tokens(rome_label, mode="description"))
        description_tokens = set(normalize_tokens(rome_label, mode="description"))
        for label in occupation_labels:
            title_tokens.update(normalize_tokens(label, mode="title"))
            skill_profile_tokens.update(normalize_tokens(label, mode="description"))
            description_tokens.update(normalize_tokens(label, mode="description"))
        for title in observed_titles:
            title_tokens.update(normalize_tokens(title, mode="title"))
            normalized_title_tokens = normalize_tokens(title, mode="description")
            skill_profile_tokens.update(normalized_title_tokens)
            description_tokens.update(normalized_title_tokens)
        for token, _ in sorted(desc_tokens_by_code[code].items(), key=lambda item: (-item[1], item[0]))[:160]:  # pylint: disable=line-too-long
            description_tokens.add(token)
        skill_profile_tokens.update(observed_skills)

        profiles.append(
            RomeProfile(
                rome_code=code,
                rome_label=rome_label,
                occupation_labels=occupation_labels,
                observed_job_titles=observed_titles,
                observed_skills=observed_skills,
                source_counts={
                    "france_travail_offers": counts_by_code[code],
                    "rome_reference_rows": int(ref.get("csv_rows") or 0),
                    "observed_job_titles": len(observed_titles),
                    "observed_skills": len(observed_skills),
                },
                title_tokens=frozenset(title_tokens),
                skill_tokens=frozenset(skill_profile_tokens),
                description_tokens=frozenset(description_tokens),
                exact_title_values=frozenset(
                    value
                    for value in (
                        normalized_title_value(label)
                        for label in (rome_label, *occupation_labels, *observed_titles)
                    )
                    if value
                ),
            )
        )
    if config.common_token_ratio <= 1:
        profile_count = len(profiles)
        common_limit = max(2, int(profile_count * config.common_token_ratio))
        title_df: Counter[str] = Counter()
        skill_df: Counter[str] = Counter()
        description_df: Counter[str] = Counter()
        for profile in profiles:
            title_df.update(profile.title_tokens)
            skill_df.update(profile.skill_tokens)
            description_df.update(profile.description_tokens)
        common_title = {token for token, count in title_df.items() if count > common_limit}
        common_skill = {token for token, count in skill_df.items() if count > common_limit}
        common_description = {token for token, count in description_df.items() if count > common_limit}  # pylint: disable=line-too-long
        profiles = [
            replace(
                profile,
                title_tokens=frozenset(token for token in profile.title_tokens if token not in common_title),  # pylint: disable=line-too-long
                skill_tokens=frozenset(token for token in profile.skill_tokens if token not in common_skill),  # pylint: disable=line-too-long
                description_tokens=frozenset(token for token in profile.description_tokens if token not in common_description),  # pylint: disable=line-too-long
                source_counts={
                    **profile.source_counts,
                    "filtered_common_title_tokens": len(common_title),
                    "filtered_common_skill_tokens": len(common_skill),
                    "filtered_common_description_tokens": len(common_description),
                },
            )
            for profile in profiles
        ]
    return profiles


def overlap_score(query_tokens: tuple[str, ...], profile_tokens: frozenset[str]) -> tuple[float, list[str], list[str]]:  # pylint: disable=line-too-long
    """."""
    if not query_tokens:
        return 0.0, [], ["Aucun signal fourni."]
    matched = sorted(set(query_tokens) & set(profile_tokens))
    missing = sorted(set(query_tokens) - set(profile_tokens))
    score = (len(matched) / len(set(query_tokens))) * 100.0
    return round(score, 4), matched, missing[:12]


def normalized_title_value(text: str | None) -> str:
    """."""
    return " ".join(normalize_tokens(text, mode="title"))


def exact_or_near_title_match(title: str | None, profile: RomeProfile) -> tuple[float, str | None]:
    """."""
    normalized_title = normalized_title_value(title)
    if not normalized_title:
        return 0.0, None
    if normalized_title in profile.exact_title_values:
        return 1.0, title
    return 0.0, None


def score_candidate(
    offer: dict[str, Any],
    profile: RomeProfile,
    config: ClassificationConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """."""
    title = offer.get("title")
    description_parts = [
        offer.get("description"),
        offer.get("candidate_profile"),
    ]
    title_tokens = normalize_tokens(title, mode="title")
    structured_skills = skill_tokens(offer.get("skills"))
    description_tokens = normalize_tokens(" ".join(str(part) for part in description_parts if part), mode="description")  # pylint: disable=line-too-long

    title_score, title_hits, title_missing = overlap_score(title_tokens, profile.title_tokens)
    skills_score, skill_hits, skill_missing = overlap_score(structured_skills, profile.skill_tokens)
    desc_score, desc_hits, desc_missing = overlap_score(description_tokens, profile.description_tokens)  # pylint: disable=line-too-long
    exact_match_score, exact_match_label = exact_or_near_title_match(title, profile)

    score = round(
        (
            title_score * config.title_weight
            + skills_score * config.skill_weight
            + desc_score * config.description_weight
        )
        / 100.0
        + exact_match_score * config.exact_title_bonus,
        4,
    )
    reasons = {
        "positive": [],
        "missing_or_contradictory": [],
    }
    if title_hits:
        reasons["positive"].append({"field": "title", "matched_tokens": title_hits[:12]})
    if exact_match_label:
        reasons["positive"].append({"field": "title", "exact_or_near_match": exact_match_label})
    else:
        reasons["missing_or_contradictory"].append({"field": "title", "missing_tokens": title_missing})  # pylint: disable=line-too-long
    if skill_hits:
        reasons["positive"].append({"field": "skills", "matched_tokens": skill_hits[:12]})
    elif structured_skills:
        reasons["missing_or_contradictory"].append({"field": "skills", "missing_tokens": skill_missing})  # pylint: disable=line-too-long
    if desc_hits:
        reasons["positive"].append({"field": "description", "matched_tokens": desc_hits[:12]})
    elif description_tokens:
        reasons["missing_or_contradictory"].append({"field": "description", "missing_tokens": desc_missing})  # pylint: disable=line-too-long

    return {
        "rome_code": profile.rome_code,
        "rome_label": profile.rome_label,
        "score": score,
        "field_scores": {
            "title": round(title_score * config.title_weight / 100.0, 4),
            "skills": round(skills_score * config.skill_weight / 100.0, 4),
            "description": round(desc_score * config.description_weight / 100.0, 4),
            "exact_title_bonus": round(exact_match_score * config.exact_title_bonus, 4),
            "title_raw": title_score,
            "skills_raw": skills_score,
            "description_raw": desc_score,
        },
        "reasons": reasons,
    }


def classify_independent(
    offer: dict[str, Any],
    profiles: list[RomeProfile],
    top_k: int = 3,
    config: ClassificationConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """."""
    candidates = [score_candidate(offer, profile, config=config) for profile in profiles]
    candidates.sort(key=lambda item: (-item["score"], item["rome_code"]))
    selected = candidates[:top_k]
    top_score = float(selected[0]["score"]) if selected else 0.0
    second_score = float(selected[1]["score"]) if len(selected) > 1 else 0.0
    return {
        "top_score": top_score,
        "second_score": second_score,
        "margin": round(top_score - second_score, 4),
        "candidates": selected,
    }


def build_triage_lookup(triage_rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """."""
    lookup = {}
    for row in triage_rows or []:
        free_work = row.get("free_work") if isinstance(row.get("free_work"), dict) else {}
        source_id = str(free_work.get("source_id") or row.get("free_work_source_id") or "").strip()
        if source_id:
            lookup[source_id] = row
    return lookup


def reference_rome_from_triage(row: dict[str, Any] | None) -> tuple[str | None, str | None, str | None]:  # pylint: disable=line-too-long
    """."""
    if not row or row.get("decision") != "PRESENT_IN_FT_SNAPSHOT":
        return None, None, None
    best = row.get("best_candidate") if isinstance(row.get("best_candidate"), dict) else {}
    code = best.get("rome_code")
    if not code:
        return None, None, None
    return str(code), best.get("title"), best.get("france_travail_id")


def assignment_from_prediction(
    offer: dict[str, Any],
    prediction: dict[str, Any],
    triage_row: dict[str, Any] | None,
    config: ClassificationConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """."""
    reference_code, _, _ = reference_rome_from_triage(triage_row)
    candidates = prediction["candidates"]
    top = candidates[0] if candidates else None
    if reference_code:
        return {
            "assignment_status": "CONFIRMED_FROM_FT_MATCH",
            "assigned_rome_code": reference_code,
            "assignment_method": "MATCHED_FRANCE_TRAVAIL",
        }
    if is_generic_title(offer.get("title"), skill_tokens(offer.get("skills"))):
        return {
            "assignment_status": "UNASSIGNED_INSUFFICIENT_SIGNAL",
            "assigned_rome_code": None,
            "assignment_method": "GENERIC_TITLE",
        }
    if not top or prediction["top_score"] < config.auto_score_threshold:
        return {
            "assignment_status": "UNASSIGNED_INSUFFICIENT_SIGNAL",
            "assigned_rome_code": None,
            "assignment_method": "NO_SUFFICIENT_SIGNAL",
        }
    positive_reasons = top.get("reasons", {}).get("positive", [])
    has_discriminant_signal = any(reason.get("field") in {"title", "skills"} for reason in positive_reasons)  # pylint: disable=line-too-long
    if config.require_discriminant_signal and not has_discriminant_signal:
        return {
            "assignment_status": "UNASSIGNED_INSUFFICIENT_SIGNAL",
            "assigned_rome_code": None,
            "assignment_method": "NO_DISCRIMINANT_SIGNAL",
        }
    if prediction["margin"] < config.auto_margin_threshold:
        return {
            "assignment_status": "UNASSIGNED_AMBIGUOUS",
            "assigned_rome_code": None,
            "assignment_method": "CLOSE_CANDIDATES",
        }
    return {
        "assignment_status": "AUTO_ASSIGNED_HIGH_CONFIDENCE",
        "assigned_rome_code": top["rome_code"],
        "assignment_method": "DETERMINISTIC_HIGH_CONFIDENCE",
    }


def classify_offers(
    free_work_rows: list[dict[str, Any]],
    profiles: list[RomeProfile],
    triage_rows: list[dict[str, Any]] | None = None,
    top_k: int = 3,
    config: ClassificationConfig = DEFAULT_CONFIG,
    progress_callback=None,
) -> list[dict[str, Any]]:
    """."""
    validate_free_work_offers(free_work_rows)
    triage_lookup = build_triage_lookup(triage_rows)
    labels_by_code = {profile.rome_code: profile.rome_label for profile in profiles}
    results = []
    total = len(free_work_rows)
    for index, offer in enumerate(sorted(free_work_rows, key=lambda item: str(item["source_id"])), start=1):  # pylint: disable=line-too-long
        source_id = str(offer["source_id"])
        try:
            prediction = classify_independent(offer, profiles, top_k=top_k, config=config)
            triage_row = triage_lookup.get(source_id)
            assignment = assignment_from_prediction(offer, prediction, triage_row, config=config)
            top = prediction["candidates"][0] if prediction["candidates"] else None
            second = prediction["candidates"][1] if len(prediction["candidates"]) > 1 else None
            assigned_label = None
            if assignment["assigned_rome_code"]:
                assigned_label = next(
                    (candidate["rome_label"] for candidate in prediction["candidates"] if candidate["rome_code"] == assignment["assigned_rome_code"]),  # pylint: disable=line-too-long
                    labels_by_code.get(assignment["assigned_rome_code"]),
                )
            reasons = {
                "positive_reasons": top.get("reasons", {}).get("positive", []) if top else [],
                "negative_or_missing_signals": top.get("reasons", {}).get("missing_or_contradictory", []) if top else [],  # pylint: disable=line-too-long
            }
            record = {
                "free_work_id": source_id,
                "assignment_status": assignment["assignment_status"],
                "assigned_rome_code": assignment["assigned_rome_code"],
                "assigned_rome_label": assigned_label,
                "assignment_method": assignment["assignment_method"],
                "confidence_score": prediction["top_score"],
                "top_score": prediction["top_score"],
                "second_score": prediction["second_score"],
                "margin": prediction["margin"],
                "candidates": prediction["candidates"],
                "reasons": reasons,
                "independent_prediction": {
                    "rome_code": top["rome_code"] if top else None,
                    "rome_label": top["rome_label"] if top else None,
                    "score": top["score"] if top else 0.0,
                    "top3_rome_codes": [candidate["rome_code"] for candidate in prediction["candidates"]],  # pylint: disable=line-too-long
                    "second_rome_code": second["rome_code"] if second else None,
                },
                "processing_error": None,
            }
        except Exception as exc:
            record = {
                "free_work_id": source_id,
                "assignment_status": "PROCESSING_ERROR",
                "assigned_rome_code": None,
                "assigned_rome_label": None,
                "assignment_method": "PROCESSING_ERROR",
                "confidence_score": 0.0,
                "top_score": 0.0,
                "second_score": 0.0,
                "margin": 0.0,
                "candidates": [],
                "reasons": {
                    "positive_reasons": [],
                    "negative_or_missing_signals": [{"field": "processing", "error": str(exc)}],
                },
                "independent_prediction": {
                    "rome_code": None,
                    "rome_label": None,
                    "score": 0.0,
                    "top3_rome_codes": [],
                    "second_rome_code": None,
                },
                "processing_error": str(exc),
            }
        results.append(record)
        if progress_callback:
            progress_callback(index, total)
    return results


def bucket(value: float) -> str:
    """."""
    if value < 20:
        return "0-19"
    if value < 40:
        return "20-39"
    if value < 60:
        return "40-59"
    if value < 80:
        return "60-79"
    return "80-100"


def build_benchmark(results: list[dict[str, Any]], triage_rows: list[dict[str, Any]] | None) -> dict[str, Any]:  # pylint: disable=line-too-long
    """."""
    triage_lookup = build_triage_lookup(triage_rows)
    by_id = {row["free_work_id"]: row for row in results}
    sample = []
    for source_id, triage_row in sorted(triage_lookup.items()):
        reference_code, _, _ = reference_rome_from_triage(triage_row)
        if reference_code and source_id in by_id:
            sample.append((source_id, reference_code, by_id[source_id]))

    top1_correct = 0
    top3_correct = 0
    unassigned_count = 0
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    score_correct = Counter()
    score_incorrect = Counter()
    margin_correct = Counter()
    margin_incorrect = Counter()
    threshold_rows = []

    for _, reference_code, result in sample:
        predicted = result["independent_prediction"]["rome_code"]
        top3 = result["independent_prediction"]["top3_rome_codes"]
        correct = predicted == reference_code
        if str(result["assignment_status"]).startswith("UNASSIGNED"):
            unassigned_count += 1
        if correct:
            top1_correct += 1
            score_correct[bucket(float(result["top_score"]))] += 1
            margin_correct[bucket(float(result["margin"]))] += 1
        else:
            score_incorrect[bucket(float(result["top_score"]))] += 1
            margin_incorrect[bucket(float(result["margin"]))] += 1
            confusion[reference_code][predicted or "UNASSIGNED"] += 1
        if reference_code in top3:
            top3_correct += 1

    for score_threshold in (20, 30, 40, 50, 60):
        for margin_threshold in (0, 5, 10, 15):
            covered = [
                (reference_code, result)
                for _, reference_code, result in sample
                if float(result["top_score"]) >= score_threshold and float(result["margin"]) >= margin_threshold  # pylint: disable=line-too-long
            ]
            errors = sum(1 for reference_code, result in covered if result["independent_prediction"]["rome_code"] != reference_code)  # pylint: disable=line-too-long
            threshold_rows.append(
                {
                    "score_threshold": score_threshold,
                    "margin_threshold": margin_threshold,
                    "covered_cases": len(covered),
                    "observed_precision": round((len(covered) - errors) / len(covered), 4) if covered else None,  # pylint: disable=line-too-long
                    "coverage_rate": round(len(covered) / len(sample), 4) if sample else 0.0,
                    "errors": errors,
                }
            )

    sample_size = len(sample)
    return {
        "sample_size": sample_size,
        "top1_correct": top1_correct,
        "top1_accuracy": round(top1_correct / sample_size, 4) if sample_size else 0.0,
        "top3_correct": top3_correct,
        "top3_recall": round(top3_correct / sample_size, 4) if sample_size else 0.0,
        "unassigned_count": unassigned_count,
        "confusion_by_rome": {code: dict(counter) for code, counter in sorted(confusion.items())},
        "score_distribution_correct": dict(sorted(score_correct.items())),
        "score_distribution_incorrect": dict(sorted(score_incorrect.items())),
        "margin_distribution_correct": dict(sorted(margin_correct.items())),
        "margin_distribution_incorrect": dict(sorted(margin_incorrect.items())),
        "threshold_analysis": threshold_rows,
    }


def deterministic_reference_split(sample: list[tuple[str, str, str | None]]) -> dict[str, list[str]]:  # pylint: disable=line-too-long
    """."""
    by_code: dict[str, list[str]] = defaultdict(list)
    for source_id, reference_code, _ in sample:
        by_code[reference_code].append(source_id)

    calibration: list[str] = []
    validation: list[str] = []
    for code, source_ids in sorted(by_code.items()):
        ordered = sorted(
            source_ids,
            key=lambda value: hashlib.sha256(f"{CALIBRATION_SEED}:{code}:{value}".encode("utf-8")).hexdigest(),  # pylint: disable=line-too-long
        )
        if len(ordered) >= 4:
            calibration_count = max(1, round(len(ordered) * 0.7))
            calibration.extend(ordered[:calibration_count])
            validation.extend(ordered[calibration_count:])
        else:
            for source_id in ordered:
                target = calibration if len(calibration) <= len(validation) * 2 else validation
                target.append(source_id)
    return {
        "calibration": sorted(calibration),
        "validation": sorted(validation),
    }


def reference_sample(triage_rows: list[dict[str, Any]] | None) -> list[tuple[str, str, str | None]]:
    """."""
    sample = []
    for source_id, triage_row in sorted(build_triage_lookup(triage_rows).items()):
        reference_code, _, france_travail_id = reference_rome_from_triage(triage_row)
        if reference_code:
            sample.append((source_id, reference_code, france_travail_id))
    return sample


def benchmark_from_reference_predictions(
    rows: list[dict[str, Any]],
    split: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """."""
    sample_size = len(rows)
    top1_correct = sum(1 for row in rows if row["predicted_rome_code"] == row["reference_rome_code"])  # pylint: disable=line-too-long
    top3_correct = sum(1 for row in rows if row["reference_rome_code"] in row["top3_rome_codes"])
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    predicted_counter = Counter(row["predicted_rome_code"] or "UNASSIGNED" for row in rows)
    by_code: dict[str, Counter[str]] = defaultdict(Counter)
    score_counter = Counter(bucket(float(row["top_score"])) for row in rows)
    margin_counter = Counter(bucket(float(row["margin"])) for row in rows)
    for row in rows:
        expected = row["reference_rome_code"]
        predicted = row["predicted_rome_code"] or "UNASSIGNED"
        by_code[expected]["total"] += 1
        if expected == predicted:
            by_code[expected]["top1_correct"] += 1
        else:
            confusion[expected][predicted] += 1

    result = {
        "sample_size": sample_size,
        "top1_correct": top1_correct,
        "top1_accuracy": round(top1_correct / sample_size, 4) if sample_size else 0.0,
        "top3_correct": top3_correct,
        "top3_recall": round(top3_correct / sample_size, 4) if sample_size else 0.0,
        "predicted_code_counts": dict(sorted(predicted_counter.items())),
        "results_by_rome": {
            code: {
                "total": counts["total"],
                "top1_correct": counts["top1_correct"],
                "top1_accuracy": round(counts["top1_correct"] / counts["total"], 4) if counts["total"] else 0.0,  # pylint: disable=line-too-long
            }
            for code, counts in sorted(by_code.items())
        },
        "confusion_by_rome": {code: dict(counter) for code, counter in sorted(confusion.items())},
        "score_distribution": dict(sorted(score_counter.items())),
        "margin_distribution": dict(sorted(margin_counter.items())),
    }
    if split:
        for split_name, ids in split.items():
            split_rows = [row for row in rows if row["free_work_id"] in set(ids)]
            result[f"{split_name}_sample_size"] = len(split_rows)
            result[f"{split_name}_top1_accuracy"] = (
                round(sum(1 for row in split_rows if row["predicted_rome_code"] == row["reference_rome_code"]) / len(split_rows), 4)  # pylint: disable=line-too-long
                if split_rows
                else 0.0
            )
    return result


def threshold_analysis_for_rows(
    rows: list[dict[str, Any]],
    score_thresholds: tuple[float, ...] = (50, 55, 60, 65, 70, 75, 80),
    margin_thresholds: tuple[float, ...] = (5, 10, 15, 20, 25, 30),
) -> list[dict[str, Any]]:
    """."""
    analysis = []
    for score_threshold in score_thresholds:
        for margin_threshold in margin_thresholds:
            covered = [
                row for row in rows
                if float(row["top_score"]) >= score_threshold and float(row["margin"]) >= margin_threshold  # pylint: disable=line-too-long
            ]
            errors = sum(1 for row in covered if row["predicted_rome_code"] != row["reference_rome_code"])  # pylint: disable=line-too-long
            analysis.append(
                {
                    "score_threshold": score_threshold,
                    "margin_threshold": margin_threshold,
                    "covered_cases": len(covered),
                    "observed_precision": round((len(covered) - errors) / len(covered), 4) if covered else None,  # pylint: disable=line-too-long
                    "coverage_rate": round(len(covered) / len(rows), 4) if rows else 0.0,
                    "errors": errors,
                }
            )
    return analysis


def select_thresholds(calibration_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """."""
    candidates = threshold_analysis_for_rows(calibration_rows)
    credible = [
        row for row in candidates
        if row["covered_cases"] >= MIN_CALIBRATION_AUTO_ASSIGNED
        and row["observed_precision"] is not None
        and row["observed_precision"] >= 0.9
    ]
    if not credible:
        credible = [
            row for row in candidates
            if row["covered_cases"] >= MIN_CALIBRATION_AUTO_ASSIGNED
            and row["observed_precision"] is not None
        ]
    if not credible:
        return {
            "score_threshold": 100.0,
            "margin_threshold": 100.0,
            "selection_reason": "Aucun seuil crédible sur la calibration ; affectation automatique désactivée hors correspondances FT.",  # pylint: disable=line-too-long
        }
    selected = sorted(
        credible,
        key=lambda row: (
            -(row["observed_precision"] or 0.0),
            -row["covered_cases"],
            row["score_threshold"],
            row["margin_threshold"],
        ),
    )[0]
    return {
        "score_threshold": selected["score_threshold"],
        "margin_threshold": selected["margin_threshold"],
        "selection_reason": "Meilleure précision observée sur calibration, puis meilleure couverture.",  # pylint: disable=line-too-long
    }


def assignment_metrics_for_rows(rows: list[dict[str, Any]], score_threshold: float, margin_threshold: float) -> dict[str, Any]:  # pylint: disable=line-too-long
    """."""
    covered = [
        row for row in rows
        if float(row["top_score"]) >= score_threshold and float(row["margin"]) >= margin_threshold
    ]
    errors = sum(1 for row in covered if row["predicted_rome_code"] != row["reference_rome_code"])
    return {
        "sample_size": len(rows),
        "auto_assigned": len(covered),
        "observed_precision": round((len(covered) - errors) / len(covered), 4) if covered else None,
        "coverage_rate": round(len(covered) / len(rows), 4) if rows else 0.0,
        "errors": errors,
    }


def build_leave_one_out_reference_predictions(
    free_work_rows: list[dict[str, Any]],
    france_travail_rows: list[dict[str, Any]],
    triage_rows: list[dict[str, Any]] | None,
    rome_reference_csv: Path,
    config: ClassificationConfig,
    top_k: int,
) -> list[dict[str, Any]]:
    """."""
    free_work_lookup = {str(row["source_id"]): row for row in free_work_rows}
    sample = reference_sample(triage_rows)
    held_out_france_travail_ids = {str(france_travail_id) for _, _, france_travail_id in sample if france_travail_id}  # pylint: disable=line-too-long
    training_rows = [
        row for row in france_travail_rows
        if str(row.get("france_travail_id") or "") not in held_out_france_travail_ids
    ]
    profiles = build_rome_profiles(training_rows, rome_reference_csv, config=config)
    rows = []
    for source_id, reference_code, france_travail_id in sample:
        offer = free_work_lookup.get(source_id)
        if not offer:
            continue
        prediction = classify_independent(offer, profiles, top_k=top_k, config=config)
        top = prediction["candidates"][0] if prediction["candidates"] else None
        rows.append(
            {
                "free_work_id": source_id,
                "reference_rome_code": reference_code,
                "reference_france_travail_id": france_travail_id,
                "predicted_rome_code": top["rome_code"] if top else None,
                "top_score": prediction["top_score"],
                "second_score": prediction["second_score"],
                "margin": prediction["margin"],
                "top3_rome_codes": [candidate["rome_code"] for candidate in prediction["candidates"]],  # pylint: disable=line-too-long
            }
        )
    return rows


def build_calibrated_benchmark(
    free_work_rows: list[dict[str, Any]],
    france_travail_rows: list[dict[str, Any]],
    triage_rows: list[dict[str, Any]] | None,
    rome_reference_csv: Path,
    top_k: int,
) -> dict[str, Any]:
    """."""
    config_summaries = {}
    loo_rows_by_config = {}
    for config in (BASELINE_CONFIG, V1_A_CONFIG, V1_B_CONFIG):
        rows = build_leave_one_out_reference_predictions(
            free_work_rows,
            france_travail_rows,
            triage_rows,
            rome_reference_csv,
            config,
            top_k,
        )
        loo_rows_by_config[config.name] = rows
        config_summaries[config.name] = benchmark_from_reference_predictions(rows)

    selected_config = V1_A_CONFIG
    selected_rows = loo_rows_by_config[selected_config.name]
    split = deterministic_reference_split(
        [(row["free_work_id"], row["reference_rome_code"], row["reference_france_travail_id"]) for row in selected_rows]  # pylint: disable=line-too-long
    )
    calibration_ids = set(split["calibration"])
    validation_ids = set(split["validation"])
    calibration_rows = [row for row in selected_rows if row["free_work_id"] in calibration_ids]
    validation_rows = [row for row in selected_rows if row["free_work_id"] in validation_ids]
    threshold_selection = select_thresholds(calibration_rows)
    score_threshold = float(threshold_selection["score_threshold"])
    margin_threshold = float(threshold_selection["margin_threshold"])
    calibrated_config = replace(
        selected_config,
        auto_score_threshold=score_threshold,
        auto_margin_threshold=margin_threshold,
    )
    return {
        "baseline_documented": {
            "total_offers": 8457,
            "CONFIRMED_FROM_FT_MATCH": 143,
            "CANDIDATE_ONLY": 3086,
            "REVIEW_REQUIRED": 5039,
            "UNASSIGNED": 189,
            "top1_accuracy": 0.4685,
            "top3_recall": 0.6084,
        },
        "data_leakage_audit": {
            "initial_benchmark_profiles_used_full_france_travail_snapshot": True,
            "matched_france_travail_offer_removed_in_leave_one_out": True,
            "implementation": "reference_holdout: les 143 offres France Travail appariées sont retirées des profils benchmark.",  # pylint: disable=line-too-long
            "reference_set_warning": "Les 143 correspondances sont pratiques mais ne constituent pas une vérité métier parfaite.",  # pylint: disable=line-too-long
        },
        "configuration_summaries": config_summaries,
        "selected_configuration": calibrated_config.name,
        "split_seed": CALIBRATION_SEED,
        "split": {
            "calibration_count": len(calibration_rows),
            "validation_count": len(validation_rows),
            "calibration_ids": sorted(calibration_ids),
            "validation_ids": sorted(validation_ids),
        },
        "threshold_selection": {
            **threshold_selection,
            "calibration": assignment_metrics_for_rows(calibration_rows, score_threshold, margin_threshold),  # pylint: disable=line-too-long
            "validation": assignment_metrics_for_rows(validation_rows, score_threshold, margin_threshold),  # pylint: disable=line-too-long
            "leave_one_out_all_references": assignment_metrics_for_rows(selected_rows, score_threshold, margin_threshold),  # pylint: disable=line-too-long
            "calibration_threshold_grid": threshold_analysis_for_rows(calibration_rows),
        },
        "leave_one_out": benchmark_from_reference_predictions(selected_rows, split=split),
        "calibrated_config": calibrated_config,
    }


def score_distribution(results: list[dict[str, Any]], key: str) -> dict[str, int]:
    """."""
    counter = Counter(bucket(float(row.get(key) or 0.0)) for row in results)
    return dict(sorted(counter.items()))


def write_progress(output_dir: Path, stage: str, current: int, total: int, start: float, status: str = "RUNNING") -> None:  # pylint: disable=line-too-long
    """."""
    elapsed = time.time() - start
    speed = current / elapsed if elapsed > 0 and current else 0.0
    eta = (total - current) / speed if speed else None
    payload = {
        "status": status,
        "stage": stage,
        "current": current,
        "total": total,
        "percent": round(current / total * 100, 2) if total else 0.0,
        "elapsed_seconds": round(elapsed, 2),
        "speed_offers_per_second": round(speed, 4),
        "eta_seconds": round(eta, 2) if eta is not None else None,
        "heartbeat": time.time(),
    }
    try:
        write_json(output_dir / PROGRESS_FILE_NAME, payload)
    except Exception:
        pass


def write_review_queue(path: Path, results: list[dict[str, Any]]) -> None:
    """."""
    rows = [
        row
        for row in results
        if row["assignment_status"] in {"UNASSIGNED_AMBIGUOUS", "UNASSIGNED_INSUFFICIENT_SIGNAL", "PROCESSING_ERROR"}  # pylint: disable=line-too-long
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = [
            "free_work_id",
            "assignment_status",
            "top_rome_code",
            "top_rome_label",
            "top_score",
            "second_score",
            "margin",
            "processing_error",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (item["assignment_status"], -float(item["top_score"]), item["free_work_id"])):  # pylint: disable=line-too-long
            top = row["candidates"][0] if row["candidates"] else {}
            writer.writerow(
                {
                    "free_work_id": row["free_work_id"],
                    "assignment_status": row["assignment_status"],
                    "top_rome_code": top.get("rome_code", ""),
                    "top_rome_label": top.get("rome_label", ""),
                    "top_score": row["top_score"],
                    "second_score": row["second_score"],
                    "margin": row["margin"],
                    "processing_error": row["processing_error"] or "",
                }
            )


def write_results_jsonl(path: Path, results: list[dict[str, Any]]) -> None:
    """."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as file:
            for row in results:
                file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def run_classification(
    free_work_input: Path,
    france_travail_input: Path,
    output_dir: Path,
    rome_reference_csv: Path,
    triage_input: Path | None = None,
    top_k: int = 3,
) -> dict[str, Any]:
    """."""
    if top_k < 1:
        raise ValueError("--top-k doit être supérieur ou égal à 1.")
    start = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    free_work_rows = load_json_list(free_work_input, "free_work_input")
    france_travail_rows = load_json_list(france_travail_input, "france_travail_input")
    triage_rows = load_jsonl(triage_input) if triage_input else None

    write_progress(output_dir, "BENCHMARK_CALIBRATION", 0, len(free_work_rows), start)
    calibrated_benchmark = build_calibrated_benchmark(
        free_work_rows,
        france_travail_rows,
        triage_rows,
        rome_reference_csv,
        top_k,
    ) if triage_rows else None
    config = calibrated_benchmark["calibrated_config"] if calibrated_benchmark else DEFAULT_CONFIG

    profiles = build_rome_profiles(france_travail_rows, rome_reference_csv, config=config)
    write_progress(output_dir, "CLASSIFICATION", 0, len(free_work_rows), start)

    def progress(index: int, total: int) -> None:
        """."""
        if index == total or index % 500 == 0:
            write_progress(output_dir, "CLASSIFICATION", index, total, start)
            elapsed = time.time() - start
            speed = index / elapsed if elapsed else 0.0
            eta = (total - index) / speed if speed else 0.0
            print(
                f"[ROME] {index}/{total} - {index / total * 100:.2f}% - "
                f"elapsed {elapsed:.1f}s - {speed:.1f} offres/s - ETA {eta:.1f}s"
            )

    results = classify_offers(
        free_work_rows,
        profiles,
        triage_rows=triage_rows,
        top_k=top_k,
        config=config,
        progress_callback=progress,
    )
    legacy_benchmark = build_benchmark(results, triage_rows)
    benchmark = calibrated_benchmark or {"leave_one_out": legacy_benchmark}
    counters = Counter(row["assignment_status"] for row in results)
    errors = counters["PROCESSING_ERROR"]
    duration = time.time() - start

    manifest = {
        "classifier_version": CLASSIFIER_VERSION,
        "selected_configuration": config.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_files": {
            "free_work_input": str(free_work_input).replace("\\", "/"),
            "free_work_sha256": sha256_file(free_work_input),
            "france_travail_input": str(france_travail_input).replace("\\", "/"),
            "france_travail_sha256": sha256_file(france_travail_input),
            "triage_input": str(triage_input).replace("\\", "/") if triage_input else None,
            "triage_sha256": sha256_file(triage_input) if triage_input else None,
            "rome_reference_csv": str(rome_reference_csv).replace("\\", "/"),
            "rome_reference_sha256": sha256_file(rome_reference_csv),
        },
        "total_offers": len(free_work_rows),
        "unique_free_work_ids": len({str(row["source_id"]) for row in free_work_rows}),
        "rome_candidate_count": len(profiles),
        "status_counters": dict(sorted(counters.items())),
        "errors": errors,
        "scoring_parameters": {
            "title_weight": config.title_weight,
            "skills_weight": config.skill_weight,
            "description_weight": config.description_weight,
            "auto_score_threshold": config.auto_score_threshold,
            "auto_margin_threshold": config.auto_margin_threshold,
            "exact_title_bonus": config.exact_title_bonus,
            "common_token_ratio": config.common_token_ratio,
            "top_k": top_k,
        },
        "calibration_metrics": benchmark.get("threshold_selection", {}).get("calibration"),
        "validation_metrics": benchmark.get("threshold_selection", {}).get("validation"),
        "leave_one_out_metrics": benchmark.get("threshold_selection", {}).get("leave_one_out_all_references"),  # pylint: disable=line-too-long
        "duration_seconds": round(duration, 2),
        "score_distribution": score_distribution(results, "top_score"),
        "margin_distribution": score_distribution(results, "margin"),
        "profile_sources": {
            "rome_labels": "backend/data/raw/correspondance-rome-rncp-tech-*.csv:intitule_rome",
            "occupation_labels": "backend/data/raw/correspondance-rome-rncp-tech-*.csv:intitule_rncp",  # pylint: disable=line-too-long
            "observed_job_titles": "france_travail_snapshot:title",
            "observed_skills": "france_travail_snapshot:competences/skills si présents; absent dans le snapshot de référence",  # pylint: disable=line-too-long
        },
    }

    write_results_jsonl(output_dir / "rome_classification_results.jsonl", results)
    write_results_jsonl(output_dir / "rome_assignments_deterministic_v1.jsonl", results)
    write_json(output_dir / "rome_classification_manifest.json", manifest)
    write_review_queue(output_dir / "rome_review_queue.csv", results)
    serializable_benchmark = dict(benchmark)
    if "calibrated_config" in serializable_benchmark:
        selected = serializable_benchmark.pop("calibrated_config")
        serializable_benchmark["calibrated_config"] = {
            "name": selected.name,
            "title_weight": selected.title_weight,
            "skill_weight": selected.skill_weight,
            "description_weight": selected.description_weight,
            "auto_score_threshold": selected.auto_score_threshold,
            "auto_margin_threshold": selected.auto_margin_threshold,
            "common_token_ratio": selected.common_token_ratio,
            "exact_title_bonus": selected.exact_title_bonus,
            "require_discriminant_signal": selected.require_discriminant_signal,
        }
    write_json(output_dir / "rome_classification_benchmark.json", serializable_benchmark)
    write_json(output_dir / "rome_profiles_summary.json", [profile.public_dict() for profile in profiles])  # pylint: disable=line-too-long
    write_progress(output_dir, "COMPLETED", len(free_work_rows), len(free_work_rows), start, status="COMPLETED")  # pylint: disable=line-too-long
    return {
        "manifest": manifest,
        "benchmark": benchmark,
        "results": results,
    }

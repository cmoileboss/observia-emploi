import csv
import hashlib
import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse


FREE_WORK_BASE_URL = "https://www.free-work.com/"
LEGACY_JOB_POSTINGS_PATH = "/job_postings/"

TRIAGE_RULESET_V2_CANDIDATE = "TRIAGE_RULESET_V2_CANDIDATE"

INTERMEDIARY_PATTERNS = (
    r"pour le compte de (?:notre|son|un|une) client",
    r"notre client (?:recherche|recrute|souhaite|est)",
    r"cabinet de recrutement",
    r"nous accompagnons (?:notre|un|une) client",
    r"client final",
    r"mission chez (?:notre|un|une) client",
    r"recrute pour (?:son|un|une|notre) client",
    r"pour l['’]un de nos clients",
)

DECISION_LABELS_FR = {
    "PRESENT_IN_FT_SNAPSHOT": "Déjà présente dans France Travail pour le snapshot utilisé au moment du run",
    "NOT_FOUND_IN_FT_SNAPSHOT": "Non retrouvée dans France Travail pour le snapshot utilisé au moment du run — candidate à l’ajout",
    "UNCERTAIN": "Présence incertaine dans le snapshot France Travail utilisé au moment du run — vérification nécessaire",
    "PROCESSING_ERROR": "Traitement impossible",
}


@dataclass(frozen=True)
class TriageThresholds:
    weak_candidate_max_score: float = 40.0
    credible_candidate_min_score: float = 50.0
    strong_duplicate_min_score: float = 75.0
    minimum_evidence_coverage: int = 80
    close_candidate_margin: float = 5.0
    strong_title_similarity: float = 0.85
    medium_title_similarity: float = 0.55
    low_description_similarity: float = 0.25


@dataclass(frozen=True)
class UrlResolution:
    raw_url: str | None
    absolute_url: str | None
    method: str


@dataclass(frozen=True)
class AdvertiserRoleResult:
    advertiser_role: str
    advertiser_role_evidence: list[str]


@dataclass(frozen=True)
class CompanyComparisonHuman:
    result: str
    free_work_company: str | None
    france_travail_company: str | None
    message: str
    advertiser_role: str
    advertiser_role_evidence: list[str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical_source_id(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_free_work_details_lookup(path: Path | None) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    data = load_json(path)
    lookup = {}
    duplicates = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        source_id = canonical_source_id(item.get("source_id"))
        if source_id is None:
            continue
        if source_id in lookup:
            duplicates.add(source_id)
            continue
        lookup[source_id] = item
    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates)[:10])
        raise ValueError(f"Duplicate normalized Free-Work source id(s): {duplicate_list}")
    return lookup


def build_france_travail_lookup(path: Path | None) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    data = load_json(path)
    return {
        str(item.get("france_travail_id")): item
        for item in data
        if isinstance(item, dict) and item.get("france_travail_id") is not None
    }


def is_free_work_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower().endswith("free-work.com")


def is_legacy_job_postings_url(url: str | None) -> bool:
    if not url:
        return False
    return LEGACY_JOB_POSTINGS_PATH in urlparse(url).path


def resolve_free_work_url(raw_offer: dict | None = None, fallback_url: str | None = None) -> UrlResolution:
    raw_offer = raw_offer or {}
    candidate_keys = (
        "href",
        "url",
        "link",
        "canonicalUrl",
        "canonical_url",
        "publicUrl",
        "public_url",
    )

    for key in candidate_keys:
        value = raw_offer.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        raw_value = value.strip()
        absolute = urljoin(FREE_WORK_BASE_URL, raw_value)
        if is_free_work_url(absolute) and not is_legacy_job_postings_url(absolute):
            parsed_raw = urlparse(raw_value)
            method = "RAW_ABSOLUTE_URL" if parsed_raw.scheme else "RELATIVE_HREF_RESOLVED"
            return UrlResolution(raw_value, absolute, method)

    api_identifier = raw_offer.get("@id")
    if isinstance(api_identifier, str) and api_identifier.strip():
        raw_value = api_identifier.strip()
        absolute = urljoin(FREE_WORK_BASE_URL, raw_value)
        if is_free_work_url(absolute) and not is_legacy_job_postings_url(absolute):
            method = "RAW_ABSOLUTE_URL" if urlparse(raw_value).scheme else "RELATIVE_HREF_RESOLVED"
            return UrlResolution(raw_value, absolute, method)
        if is_legacy_job_postings_url(absolute):
            return UrlResolution(raw_value, None, "LEGACY_URL_REBUILT")

    if fallback_url:
        raw_value = str(fallback_url).strip()
        if raw_value:
            absolute = urljoin(FREE_WORK_BASE_URL, raw_value)
            if is_free_work_url(absolute) and not is_legacy_job_postings_url(absolute):
                method = "RAW_ABSOLUTE_URL" if urlparse(raw_value).scheme else "RELATIVE_HREF_RESOLVED"
                return UrlResolution(raw_value, absolute, method)
            if is_legacy_job_postings_url(absolute):
                return UrlResolution(raw_value, None, "LEGACY_URL_REBUILT")

    return UrlResolution(None, None, "URL_UNAVAILABLE")


def build_raw_offer_url_lookup(raw_offers_path: Path | None) -> dict[str, UrlResolution]:
    if not raw_offers_path or not raw_offers_path.exists():
        return {}
    data = load_json(raw_offers_path)
    lookup = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
        lookup[source_id] = resolve_free_work_url(offer)
    return lookup


def candidate_score(candidate: dict | None) -> float | None:
    if not candidate:
        return None
    value = candidate.get("preliminary_match_score")
    return float(value) if value is not None else None


def evidence_coverage(candidate: dict | None, triage_entry: dict | None = None) -> int:
    if candidate and candidate.get("evidence_coverage") is not None:
        return int(candidate["evidence_coverage"])
    if triage_entry and triage_entry.get("data_coverage") is not None:
        return int(triage_entry["data_coverage"])
    return 0


def normalize_text_for_role(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def detect_advertiser_role(*texts: str | None) -> AdvertiserRoleResult:
    evidence = []
    joined = "\n".join(normalize_text_for_role(text) for text in texts if text)
    if not joined:
        return AdvertiserRoleResult("UNKNOWN", [])
    for pattern in INTERMEDIARY_PATTERNS:
        match = re.search(pattern, joined, flags=re.IGNORECASE)
        if match:
            evidence.append(f"Expression détectée : « {match.group(0)} »")
    if evidence:
        return AdvertiserRoleResult("RECRUITMENT_INTERMEDIARY", evidence)
    possible_markers = ("notre client", "nos clients", "un client", "le client")
    possible = [marker for marker in possible_markers if marker in joined]
    if possible:
        return AdvertiserRoleResult("POSSIBLE_INTERMEDIARY", [f"Expression possible mais non suffisante : « {possible[0]} »"])
    return AdvertiserRoleResult("DIRECT_EMPLOYER", [])


def compare_companies_with_advertiser_role(
    free_work_company: str | None,
    france_travail_company: str | None,
    company_match_type_value: str,
    role_result: AdvertiserRoleResult,
) -> CompanyComparisonHuman:
    if company_match_type_value in {"EXACT_NORMALIZED"}:
        result = "SAME_COMPANY"
        message = "Les noms d'entreprise correspondent après normalisation."
    elif company_match_type_value in {"ALIAS_MATCH", "CONTAINMENT_MATCH", "HIGH_SIMILARITY"}:
        result = "KNOWN_ALIAS"
        message = "Les entreprises sont compatibles via alias ou forte similarité."
    elif role_result.advertiser_role == "RECRUITMENT_INTERMEDIARY":
        result = "DIFFERENT_BUT_INTERMEDIARY_EXPLAINED"
        message = (
            "Les annonceurs sont différents, mais une offre indique explicitement qu'elle est publiée "
            "pour le compte d'un client. Cette différence n'exclut pas qu'il s'agisse du même poste."
        )
    elif not free_work_company or not france_travail_company:
        result = "UNKNOWN"
        message = "La comparaison d'entreprise est inconnue car au moins un nom est absent."
    else:
        result = "DIFFERENT_COMPANIES"
        message = "Les entreprises sont différentes et aucune preuve explicite d'intermédiation n'a été détectée."
    return CompanyComparisonHuman(
        result=result,
        free_work_company=free_work_company,
        france_travail_company=france_travail_company,
        message=message,
        advertiser_role=role_result.advertiser_role,
        advertiser_role_evidence=role_result.advertiser_role_evidence,
    )


def strong_match_via_intermediary(candidate: dict | None, role_result: AdvertiserRoleResult, thresholds: TriageThresholds = TriageThresholds()) -> bool:
    if not candidate or role_result.advertiser_role != "RECRUITMENT_INTERMEDIARY":
        return False
    score = candidate_score(candidate)
    title_sim = title_similarity(candidate)
    desc_sim = description_similarity(candidate)
    if score is None or not (50 <= score < thresholds.strong_duplicate_min_score):
        return False
    if title_sim is None or title_sim < thresholds.strong_title_similarity:
        return False
    if desc_sim is None or desc_sim < thresholds.low_description_similarity:
        return False
    if not geography_is_compatible(candidate):
        return False
    if is_generic_title((candidate.get("title_comparison") or {}).get("free_work_normalized")):
        return False
    return True


def detect_match_advertiser_role(match_entry: dict, best_candidate: dict | None, free_work_details: dict | None = None, france_travail_offer: dict | None = None) -> AdvertiserRoleResult:
    free_work_details = free_work_details or {}
    france_travail_offer = france_travail_offer or {}
    return detect_advertiser_role(
        match_entry.get("free_work_description_excerpt"),
        free_work_details.get("description"),
        free_work_details.get("candidate_profile"),
        free_work_details.get("company_description"),
        france_travail_offer.get("description"),
        (best_candidate or {}).get("description"),
    )


def title_similarity(candidate: dict | None) -> float | None:
    if not candidate:
        return None
    return (candidate.get("title_comparison") or {}).get("sequence_similarity")


def description_similarity(candidate: dict | None) -> float | None:
    if not candidate:
        return None
    return (candidate.get("components") or {}).get("description_token_jaccard")


def company_match_type(candidate: dict | None) -> str:
    return ((candidate or {}).get("company_comparison") or {}).get("match_type") or "UNKNOWN"


def geography_result(candidate: dict | None) -> str:
    return ((candidate or {}).get("geography_comparison") or {}).get("result") or "UNKNOWN"


def has_strong_fingerprint(candidate: dict | None) -> bool:
    blocks = set((candidate or {}).get("candidate_blocks") or [])
    return bool(blocks & {"EXACT_FINGERPRINT", "FALLBACK_EXACT_FINGERPRINT"})


def company_is_compatible(candidate: dict | None) -> bool:
    return company_match_type(candidate) in {
        "EXACT_NORMALIZED",
        "ALIAS_MATCH",
        "CONTAINMENT_MATCH",
        "HIGH_SIMILARITY",
    }


def company_is_incompatible(candidate: dict | None) -> bool:
    return company_match_type(candidate) in {"NO_MATCH", "MISSING", "UNKNOWN"}


def geography_is_compatible(candidate: dict | None) -> bool:
    return geography_result(candidate) in {"EXACT_POSTAL_CODE", "SAME_LOCALITY", "SAME_DEPARTMENT"}


def geography_is_exact(candidate: dict | None) -> bool:
    return geography_result(candidate) in {"EXACT_POSTAL_CODE", "SAME_LOCALITY"}


def is_generic_title(title_normalized: str | None) -> bool:
    tokens = {token for token in str(title_normalized or "").split() if token}
    generic = {
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
    return len(tokens) < 3 or tokens.issubset(generic)


def has_sufficient_free_work_data(match_entry: dict, best_candidate: dict | None, thresholds: TriageThresholds) -> bool:
    if not match_entry.get("free_work_title"):
        return False
    has_description = bool(match_entry.get("free_work_description_excerpt"))
    location = match_entry.get("free_work_location") or {}
    has_meta = bool(match_entry.get("free_work_company") or location.get("postal_code") or location.get("locality"))
    return has_description and has_meta and evidence_coverage(best_candidate) >= thresholds.minimum_evidence_coverage


def contradiction_codes(candidate: dict | None, thresholds: TriageThresholds) -> list[str]:
    if not candidate:
        return []
    contradictions = []
    score = candidate_score(candidate) or 0.0
    title_sim = title_similarity(candidate)
    desc_sim = description_similarity(candidate)

    if company_is_compatible(candidate) and geography_result(candidate) == "DIFFERENT":
        contradictions.append("COMPANY_MATCH_GEO_DIFFERS")
    if company_is_incompatible(candidate) and score >= thresholds.credible_candidate_min_score + 10:
        contradictions.append("HIGH_SCORE_COMPANY_DIFFERS")
    if title_sim is not None and title_sim >= thresholds.strong_title_similarity and company_is_incompatible(candidate):
        contradictions.append("STRONG_TITLE_COMPANY_DIFFERS")
    if company_is_compatible(candidate) and title_sim is not None and title_sim < thresholds.medium_title_similarity:
        contradictions.append("COMPANY_MATCH_TITLE_WEAK")
    if desc_sim is None:
        contradictions.append("DESCRIPTION_UNKNOWN")
    return contradictions


def classify_v2(
    match_entry: dict,
    triage_entry: dict | None = None,
    thresholds: TriageThresholds = TriageThresholds(),
    advertiser_role: AdvertiserRoleResult | None = None,
) -> tuple[str, list[str]]:
    candidates = match_entry.get("top_candidates") or []
    best = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None

    if triage_entry and triage_entry.get("triage_category") == "PROCESSING_ERROR":
        return "PROCESSING_ERROR", ["V1_PROCESSING_ERROR"]

    if not match_entry.get("free_work_title"):
        return "PROCESSING_ERROR", ["MISSING_TITLE"]

    best_score = candidate_score(best)
    second_score = candidate_score(second)
    title_sim = title_similarity(best)
    desc_sim = description_similarity(best)
    contradictions = contradiction_codes(best, thresholds)

    if best and has_strong_fingerprint(best) and not is_generic_title(match_entry.get("free_work_title_normalized")):
        if not any(code in contradictions for code in {"COMPANY_MATCH_GEO_DIFFERS", "HIGH_SCORE_COMPANY_DIFFERS"}):
            return "PRESENT_IN_FT_SNAPSHOT", ["EXACT_FINGERPRINT"]

    if best and best_score is not None and best_score >= thresholds.strong_duplicate_min_score:
        strong_signals = [
            title_sim is not None and title_sim >= thresholds.strong_title_similarity,
            company_is_compatible(best),
            geography_is_compatible(best),
            desc_sim is not None and desc_sim >= thresholds.low_description_similarity,
        ]
        if sum(strong_signals) >= 3 and not contradictions and not is_generic_title(match_entry.get("free_work_title_normalized")):
            return "PRESENT_IN_FT_SNAPSHOT", ["STRONG_SCORE_CONVERGENT_SIGNALS"]

    if strong_match_via_intermediary(best, advertiser_role or AdvertiserRoleResult("UNKNOWN", []), thresholds):
        if not any(code in contradictions for code in {"COMPANY_MATCH_GEO_DIFFERS", "COMPANY_MATCH_TITLE_WEAK", "DESCRIPTION_UNKNOWN"}):
            return "PRESENT_IN_FT_SNAPSHOT", ["STRONG_MATCH_VIA_RECRUITMENT_INTERMEDIARY"]

    if not has_sufficient_free_work_data(match_entry, best, thresholds):
        return "UNCERTAIN", ["INSUFFICIENT_FREE_WORK_DATA"]

    if not best or best_score is None:
        return "NOT_FOUND_IN_FT_SNAPSHOT", ["NO_CANDIDATE"]

    all_candidates_weak = all((candidate_score(candidate) or 0.0) < thresholds.weak_candidate_max_score for candidate in candidates)
    if all_candidates_weak:
        return "NOT_FOUND_IN_FT_SNAPSHOT", ["ALL_CANDIDATES_WEAK"]

    if best_score < thresholds.weak_candidate_max_score:
        return "NOT_FOUND_IN_FT_SNAPSHOT", ["LOW_BEST_SCORE"]

    no_convergent_bundle = not (
        company_is_compatible(best)
        and geography_is_compatible(best)
        and title_sim is not None
        and title_sim >= thresholds.medium_title_similarity
    )
    low_description = desc_sim is None or desc_sim < thresholds.low_description_similarity
    if (
        best_score < thresholds.credible_candidate_min_score
        and company_is_incompatible(best)
        and not has_strong_fingerprint(best)
        and no_convergent_bundle
        and low_description
    ):
        return "NOT_FOUND_IN_FT_SNAPSHOT", ["BEST_CANDIDATE_NOT_CREDIBLE"]

    if contradictions:
        return "UNCERTAIN", contradictions

    if best_score >= thresholds.credible_candidate_min_score and second_score is not None:
        margin = best_score - second_score
        second_is_credible = second_score >= thresholds.credible_candidate_min_score
        if second_is_credible and margin < thresholds.close_candidate_margin:
            return "UNCERTAIN", ["MULTIPLE_CREDIBLE_CLOSE_CANDIDATES"]

    if thresholds.weak_candidate_max_score <= best_score < thresholds.credible_candidate_min_score:
        if company_is_incompatible(best):
            return "NOT_FOUND_IN_FT_SNAPSHOT", ["INTERMEDIATE_SCORE_WITH_WEAK_SIGNALS"]
        return "UNCERTAIN", ["INTERMEDIATE_SCORE"]

    if best_score >= thresholds.credible_candidate_min_score:
        if company_is_compatible(best) or geography_is_exact(best):
            return "UNCERTAIN", ["CREDIBLE_CANDIDATE_NEEDS_REVIEW"]

    return "NOT_FOUND_IN_FT_SNAPSHOT", ["NO_CREDIBLE_CONVERGENCE"]


def percent(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(value * 100))


def level_from_similarity(value: float | None, strong: float = 0.8, medium: float = 0.5) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= strong:
        return "MATCH"
    if value >= medium:
        return "PARTIAL_MATCH"
    return "NO_MATCH"


def human_explanation(match_entry: dict, best_candidate: dict | None, decision: str, reason_codes: list[str]) -> dict:
    if not best_candidate:
        return {
            "overall": "Aucun candidat France Travail n'a été retenu dans le snapshot utilisé.",
            "title": {"level": "UNKNOWN", "score_percent": None, "message": "Aucun titre candidat à comparer."},
            "company": {"level": "UNKNOWN", "message": "Aucune entreprise candidate à comparer."},
            "location": {"level": "UNKNOWN", "message": "Aucune localisation candidate à comparer."},
            "description": {"level": "UNKNOWN", "score_percent": None, "message": "Aucune description candidate à comparer."},
            "rome": {"level": "UNKNOWN", "message": "Aucun code ROME candidat à comparer."},
            "decision_reason": "; ".join(reason_codes),
        }

    title_sim = title_similarity(best_candidate)
    desc_sim = description_similarity(best_candidate)
    comp = best_candidate.get("company_comparison") or {}
    geo = best_candidate.get("geography_comparison") or {}
    components = best_candidate.get("components") or {}
    company_type = company_match_type(best_candidate)
    geo_type = geography_result(best_candidate)

    if decision == "PRESENT_IN_FT_SNAPSHOT":
        overall = "Offre probablement déjà présente dans le snapshot France Travail utilisé."
    elif decision == "NOT_FOUND_IN_FT_SNAPSHOT":
        overall = "Offres probablement différentes dans le snapshot France Travail utilisé."
    elif decision == "UNCERTAIN":
        overall = "Présence incertaine dans le snapshot France Travail utilisé."
    else:
        overall = "Traitement impossible."

    company_level = "UNKNOWN"
    if company_type in {"EXACT_NORMALIZED", "ALIAS_MATCH"}:
        company_level = "MATCH"
    elif company_type in {"CONTAINMENT_MATCH", "HIGH_SIMILARITY"}:
        company_level = "PARTIAL_MATCH"
    elif company_type in {"NO_MATCH", "MISSING"}:
        company_level = "NO_MATCH"

    location_level = {
        "EXACT_POSTAL_CODE": "MATCH",
        "SAME_LOCALITY": "MATCH",
        "SAME_DEPARTMENT": "PARTIAL_MATCH",
        "DIFFERENT": "NO_MATCH",
        "UNKNOWN": "UNKNOWN",
    }.get(geo_type, "UNKNOWN")

    rome_match = components.get("rome_query_match")
    if rome_match is True:
        rome_level = "MATCH"
        rome_message = "Le code ROME du candidat correspond à une requête associée à l'offre Free-Work."
    elif rome_match is False:
        rome_level = "NO_MATCH"
        rome_message = "Aucune correspondance ROME issue de la requête."
    else:
        rome_level = "UNKNOWN"
        rome_message = "Correspondance ROME inconnue."

    shared_tokens = ((best_candidate.get("title_comparison") or {}).get("shared_significant_tokens") or [])[:6]
    if shared_tokens:
        title_message = "Les titres partagent : " + ", ".join(shared_tokens) + "."
    else:
        title_message = "Les titres partagent peu de termes discriminants."

    fw_company = comp.get("free_work_raw") or "inconnue"
    ft_company = comp.get("france_travail_raw") or "inconnue"
    if company_level == "MATCH":
        company_message = f"Entreprises compatibles : {fw_company} et {ft_company}."
    elif company_level == "PARTIAL_MATCH":
        company_message = f"Entreprises partiellement compatibles : {fw_company} et {ft_company}."
    elif company_level == "NO_MATCH":
        company_message = f"Entreprises différentes ou manquantes : {fw_company} et {ft_company}."
    else:
        company_message = "Comparaison d'entreprise inconnue."

    if geo_type == "EXACT_POSTAL_CODE":
        location_message = "Même code postal."
    elif geo_type == "SAME_LOCALITY":
        location_message = "Même localité."
    elif geo_type == "SAME_DEPARTMENT":
        location_message = "Même département, mais pas le même code postal."
    elif geo_type == "DIFFERENT":
        location_message = "Localisations différentes."
    else:
        location_message = "Localisation insuffisante pour comparer."

    if desc_sim is None:
        desc_message = "Description absente ou non comparable."
    elif desc_sim >= 0.5:
        desc_message = "Les descriptions partagent une part importante de contenu significatif."
    elif desc_sim >= 0.25:
        desc_message = "Les descriptions partagent quelques éléments."
    else:
        desc_message = "Les descriptions ont peu de contenu significatif en commun."

    return {
        "overall": overall,
        "title": {
            "level": level_from_similarity(title_sim, strong=0.85, medium=0.55),
            "score_percent": percent(title_sim),
            "message": title_message,
        },
        "company": {
            "level": company_level,
            "message": company_message,
        },
        "location": {
            "level": location_level,
            "message": location_message,
        },
        "description": {
            "level": level_from_similarity(desc_sim, strong=0.5, medium=0.25),
            "score_percent": percent(desc_sim),
            "message": desc_message,
        },
        "rome": {
            "level": rome_level,
            "message": rome_message,
        },
        "decision_reason": "; ".join(reason_codes),
    }


def score_summary(best_candidate: dict | None) -> dict:
    if not best_candidate:
        return {"score_global": None, "evidence_coverage": 0}
    return {
        "score_global": candidate_score(best_candidate),
        "evidence_coverage": evidence_coverage(best_candidate),
        "title_similarity_percent": percent(title_similarity(best_candidate)),
        "description_similarity_percent": percent(description_similarity(best_candidate)),
    }


def best_candidate_summary(candidate: dict | None) -> dict | None:
    if not candidate:
        return None
    return {
        "france_travail_id": candidate.get("france_travail_id"),
        "title": candidate.get("title"),
        "company_name": candidate.get("company_name"),
        "postal_code": candidate.get("postal_code"),
        "rome_code": candidate.get("rome_code"),
        "score": candidate_score(candidate),
    }


def check_common_skills(free_work_details: dict | None, france_travail_offer: dict | None) -> bool:
    if not free_work_details or not france_travail_offer:
        return False
    fw_skills = free_work_details.get("skills") or []
    if not fw_skills:
        return False
    ft_text = (str(france_travail_offer.get("title") or "") + " " + str(france_travail_offer.get("description") or "")).lower()
    common = 0
    for sk in fw_skills:
        name = str(sk.get("name") or "").lower().strip()
        name_norm = str(sk.get("name_normalized") or "").lower().strip()
        if not name and not name_norm:
            continue
        if (name and name in ft_text) or (name_norm and name_norm in ft_text):
            common += 1
    if len(fw_skills) == 1:
        return common >= 1
    return common >= 2


def build_comparison_dossier(
    match_entry: dict,
    triage_entry: dict | None,
    url_resolution: UrlResolution,
    thresholds: TriageThresholds,
    free_work_details: dict | None = None,
    france_travail_offer: dict | None = None,
) -> dict:
    """
    Fonction unique de construction du dossier de comparaison structuré pour l'offre Free-Work
    et son meilleur candidat France Travail. Utile pour le CSV, le HTML et le futur Qwen3 8B.
    """
    candidates = match_entry.get("top_candidates") or []
    best = candidates[0] if candidates else None
    role_result = detect_match_advertiser_role(match_entry, best, free_work_details, france_travail_offer)
    decision, reason_codes = classify_v2(match_entry, triage_entry, thresholds, role_result)
    
    free_work_details = free_work_details or {}
    skills = free_work_details.get("skills") if isinstance(free_work_details.get("skills"), list) else []
    soft_skills = free_work_details.get("soft_skills") if isinstance(free_work_details.get("soft_skills"), list) else []
    description = free_work_details.get("description") or match_entry.get("free_work_description_excerpt")
    description_excerpt = description[:160] + "..." if isinstance(description, str) and len(description) > 160 else description

    # Calcul des priorités humaines : HAUTE, MOYENNE, FAIBLE, HORS_REVUE
    # (valable uniquement pour les décisions UNCERTAIN, sinon HORS_REVUE par défaut)
    if decision != "UNCERTAIN":
        priority = "HORS_REVUE"
    else:
        best_score = candidate_score(best) or 0.0
        title_sim = title_similarity(best) or 0.0
        company_type = company_match_type(best)
        geo_comp = geography_result(best)
        
        # 1. HAUTE priorité :
        # - score élevé (>= 60) avec contradiction d'entreprise
        # - titre et localisation très proches (title_sim >= 0.85 et geo compatible)
        # - intermédiation détectée (RECRUITMENT_INTERMEDIARY ou POSSIBLE_INTERMEDIARY)
        # - ou plusieurs candidats proches (second score proche du premier)
        second = candidates[1] if len(candidates) > 1 else None
        second_score = candidate_score(second) if second else None
        has_close_candidate = (
            best_score >= 50.0
            and second_score is not None
            and second_score >= 50.0
            and (best_score - second_score) < thresholds.close_candidate_margin
        )
        
        is_intermediary = role_result.advertiser_role in {"RECRUITMENT_INTERMEDIARY", "POSSIBLE_INTERMEDIARY"}
        
        if (best_score >= 60.0 and company_type in {"NO_MATCH", "MISSING"}) or \
           (title_sim >= thresholds.strong_title_similarity and geo_comp in {"EXACT_POSTAL_CODE", "SAME_LOCALITY"}) or \
           is_intermediary or \
           has_close_candidate or \
           "STRONG_TITLE_COMPANY_DIFFERS" in reason_codes:
            priority = "HAUTE"
        # 2. MOYENNE priorité :
        # - score modéré (entre 50 et 60)
        # - ou reste des incertitudes sur les données Free-Work insuffisantes avec un score correct
        elif best_score >= 50.0 or "INSUFFICIENT_FREE_WORK_DATA" in reason_codes:
            priority = "MOYENNE"
        # 3. FAIBLE priorité :
        # - score très faible
        # - ou absence de candidat crédible
        else:
            priority = "FAIBLE"

    # Comparaison de l'entreprise humanisée
    comp_type = company_match_type(best)
    if comp_type in {"EXACT_NORMALIZED", "ALIAS_MATCH"}:
        comp_human = "Titre identique ou très proche" if comp_type == "EXACT_NORMALIZED" else "Entreprises compatibles via alias"
    elif comp_type in {"CONTAINMENT_MATCH", "HIGH_SIMILARITY"}:
        comp_human = "Entreprises compatibles via alias ou forte similarité"
    elif role_result.advertiser_role == "RECRUITMENT_INTERMEDIARY":
        comp_human = "Annonceurs différents (intermédiaire de recrutement détecté)"
    else:
        comp_human = "Entreprises différentes"

    # Comparaison de la localisation humanisée
    geo_res = geography_result(best)
    if geo_res == "EXACT_POSTAL_CODE":
        geo_human = "Même code postal"
    elif geo_res == "SAME_LOCALITY":
        geo_human = "Même localité"
    elif geo_res == "SAME_DEPARTMENT":
        geo_human = "Même département"
    elif geo_res == "DIFFERENT":
        geo_human = "Localisations différentes"
    else:
        geo_human = "Localisation insuffisante pour comparer"

    # Comparaison du titre humanisée
    title_sim = title_similarity(best)
    if title_sim is None:
        title_human = "Titre absent"
    elif title_sim >= thresholds.strong_title_similarity:
        title_human = "Titre identique ou très proche"
    elif title_sim >= thresholds.medium_title_similarity:
        title_human = "Titre partiellement proche"
    else:
        title_human = "Titre différent"

    # Comparaison de la description humanisée
    desc_sim = description_similarity(best)
    if desc_sim is None:
        desc_human = "Description absente ou non comparable"
    elif desc_sim >= 0.5:
        desc_human = "Description très similaire"
    elif desc_sim >= 0.25:
        desc_human = "Description partiellement similaire"
    else:
        desc_human = "Description peu similaire"

    # Comparaison ROME
    components = (best.get("components") or {}) if best else {}
    rome_match = components.get("rome_query_match")
    if rome_match is True:
        rome_human = "Même code ROME ou compatible"
    else:
        rome_human = "Code ROME différent ou inconnu"

    # Éléments concordants et points de vigilance
    concordants = []
    vigilance = []
    
    if title_sim is not None and title_sim >= thresholds.strong_title_similarity:
        concordants.append("Intitulés de postes très similaires")
    elif title_sim is not None and title_sim >= thresholds.medium_title_similarity:
        concordants.append("Intitulés de postes proches")
        
    if company_is_compatible(best):
        concordants.append("Entreprises identiques ou compatibles")
    elif role_result.advertiser_role == "RECRUITMENT_INTERMEDIARY":
        concordants.append("Différence d'entreprises expliquée par un intermédiaire")
    else:
        vigilance.append("Entreprises différentes")

    if geography_is_compatible(best):
        concordants.append("Localisations géographiques compatibles")
    elif geo_res == "DIFFERENT":
        vigilance.append("Écarts géographiques")

    if desc_sim is not None and desc_sim >= 0.25:
        concordants.append("Descriptions d'offres cohérentes")
    elif desc_sim is not None:
        vigilance.append("Descriptions peu similaires")

    if "MULTIPLE_CREDIBLE_CLOSE_CANDIDATES" in reason_codes:
        vigilance.append("Multiples candidats France Travail très proches")

    # Détermination de review_action et review_action_reason
    if decision != "UNCERTAIN":
        review_action = "NO_MANUAL_REVIEW"
        review_action_reason = "Décision résolue automatiquement sans intervention humaine nécessaire."
    else:
        best_score = candidate_score(best) or 0.0
        title_sim = title_similarity(best) or 0.0
        company_type = company_match_type(best)
        geo_comp = geography_result(best)
        second = candidates[1] if len(candidates) > 1 else None
        second_score = candidate_score(second) if second else None
        has_close_candidate = (
            best_score >= 50.0
            and second_score is not None
            and second_score >= 50.0
            and (best_score - second_score) < thresholds.close_candidate_margin
        )
        is_v1_duplicate = triage_entry and triage_entry.get("triage_category") == "DUPLICATE_HIGH_CONFIDENCE"
        is_explicit_intermediary = role_result.advertiser_role == "RECRUITMENT_INTERMEDIARY"
        has_strong_title = title_sim is not None and title_sim >= thresholds.strong_title_similarity
        has_compatible_company = company_is_compatible(best)
        has_compatible_geo = geography_is_compatible(best)
        has_strong_fingerprint_flag = has_strong_fingerprint(best)
        
        desc_convergent = desc_sim is not None and desc_sim >= thresholds.low_description_similarity
        has_common_skills = check_common_skills(free_work_details, france_travail_offer)
        
        has_strong_title_with_extra_signal = has_strong_title and (
            has_compatible_geo
            or desc_convergent
            or has_common_skills
            or has_compatible_company
            or is_explicit_intermediary
        )
        
        # Conditions pour différer (DEFER_DATA_INCOMPLETE) :
        # - la décision V2 est UNCERTAIN
        # - le motif principal contient "INSUFFICIENT_FREE_WORK_DATA"
        # - le meilleur score est < 50
        # - pas d'empreinte exacte
        # - pas d'ancien doublon V1 DUPLICATE_HIGH_CONFIDENCE
        # - pas d'intermédiaire explicite
        # - pas de compagnie compatible
        # - pas de multiples candidats proches crédibles (score >= 50)
        # - pas de titre fortement similaire avec un autre signal significatif complémentaire
        # - pas de contradiction forte exploitable nécessitant arbitrage (ex. HIGH_SCORE_COMPANY_DIFFERS, STRONG_TITLE_COMPANY_DIFFERS)
        is_deferred_eligible = (
            "INSUFFICIENT_FREE_WORK_DATA" in reason_codes
            and best_score < 50.0
            and not has_strong_fingerprint_flag
            and not is_v1_duplicate
            and not is_explicit_intermediary
            and not has_compatible_company
            and not has_close_candidate
            and not has_strong_title_with_extra_signal
            and not any(code in reason_codes for code in {"HIGH_SCORE_COMPANY_DIFFERS", "STRONG_TITLE_COMPANY_DIFFERS"})
        )
        
        if is_deferred_eligible:
            review_action = "DEFER_DATA_INCOMPLETE"
            review_action_reason = "Données insuffisantes et aucun signal crédible permettant une comparaison humaine."
        else:
            review_action = "REVIEW_NOW"
            
            # Raisons personnalisées et précises
            reasons_reasons = []
            if is_v1_duplicate:
                reasons_reasons.append("Ancien doublon V1 à forte confiance nécessitant validation historique")
            if best_score >= 50.0:
                reasons_reasons.append(f"Score candidat significatif ({int(round(best_score))}/100)")
            if has_strong_title:
                if has_strong_title_with_extra_signal:
                    reasons_reasons.append("Titre fortement similaire avec signal significatif complémentaire")
                else:
                    reasons_reasons.append("Titre fortement similaire")
            if has_compatible_company:
                reasons_reasons.append("Entreprise identique ou compatible détectée")
            if is_explicit_intermediary:
                reasons_reasons.append("Intermédiaire de recrutement explicitement prouvé")
            if has_close_candidate:
                reasons_reasons.append("Plusieurs candidats France Travail crédibles proches")
            if any(code in reason_codes for code in {"HIGH_SCORE_COMPANY_DIFFERS", "STRONG_TITLE_COMPANY_DIFFERS"}):
                reasons_reasons.append("Contradiction forte (titre/entreprise) nécessitant un arbitrage")
            
            if reasons_reasons:
                review_action_reason = " ; ".join(reasons_reasons) + "."
            else:
                review_action_reason = "Signal modéré ou incertitude standard nécessitant une revue humaine."

    # Synthèse d'action recommandée
    if priority == "HAUTE":
        action = "Revue humaine urgente : forte probabilité de doublon malgré une divergence (ex. entreprise ou intermédiaire)"
    elif priority == "MOYENNE":
        action = "Revue humaine standard conseillée"
    elif priority == "FAIBLE":
        action = "Revue de second niveau ou rejet probable"
    else:
        action = "Aucune action requise (hors revue)"

    return {
        "free_work_offer": {
            "source_id": canonical_source_id(match_entry.get("free_work_source_id")),
            "title": free_work_details.get("title") or match_entry.get("free_work_title"),
            "company": free_work_details.get("company_name") or match_entry.get("free_work_company"),
            "location": free_work_details.get("location") or match_entry.get("free_work_location"),
            "description_excerpt": description_excerpt,
            "skills": skills,
            "soft_skills": soft_skills,
            "url": url_resolution.absolute_url,
            "url_raw": url_resolution.raw_url,
            "url_resolution_method": url_resolution.method,
        },
        "france_travail_candidate": best_candidate_summary(best) if best else None,
        "comparison": {
            "score_global": candidate_score(best),
            "evidence_coverage": evidence_coverage(best),
            "title_similarity": title_sim,
            "description_similarity": desc_sim,
            "title_human": title_human,
            "company_human": comp_human,
            "location_human": geo_human,
            "description_human": desc_human,
            "rome_human": rome_human,
        },
        "deterministic_decision": decision,
        "deterministic_reasons": reason_codes,
        "human_review_priority": priority,
        "review_action": review_action,
        "review_action_reason": review_action_reason,
        "human_review_synthesis": {
            "resume_decision": (
                "Offre probablement déjà présente dans le snapshot France Travail utilisé."
                if decision == "PRESENT_IN_FT_SNAPSHOT"
                else "Offres probablement différentes dans le snapshot France Travail utilisé."
                if decision == "NOT_FOUND_IN_FT_SNAPSHOT"
                else "Présence incertaine dans le snapshot France Travail utilisé."
                if decision == "UNCERTAIN"
                else "Traitement impossible."
            ) if best else "Aucun candidat France Travail trouvé",
            "elements_concordants": " | ".join(concordants) if concordants else "Aucun élément particulièrement concordant",
            "points_de_vigilance": " | ".join(vigilance) if vigilance else "Aucun point de vigilance majeur",
            "action_recommandee": action,
        }
    }


def make_decision_record(
    match_entry: dict,
    triage_entry: dict | None,
    url_resolution: UrlResolution,
    thresholds: TriageThresholds,
    free_work_details: dict | None = None,
    france_travail_offer: dict | None = None,
) -> dict:
    candidates = match_entry.get("top_candidates") or []
    best = candidates[0] if candidates else None
    dossier = build_comparison_dossier(
        match_entry, triage_entry, url_resolution, thresholds, free_work_details, france_travail_offer
    )
    
    # Conserve exactement la même structure machine attendue pour triage_decisions.jsonl
    return {
        "free_work": dossier["free_work_offer"],
        "decision": dossier["deterministic_decision"],
        "decision_label_fr": DECISION_LABELS_FR[dossier["deterministic_decision"]],
        "score": {
            "score_global": dossier["comparison"]["score_global"],
            "evidence_coverage": dossier["comparison"]["evidence_coverage"],
            "title_similarity_percent": percent(dossier["comparison"]["title_similarity"]),
            "description_similarity_percent": percent(dossier["comparison"]["description_similarity"]),
        },
        "best_candidate": dossier["france_travail_candidate"],
        "human_explanation": human_explanation(match_entry, best, dossier["deterministic_decision"], dossier["deterministic_reasons"]),
        "technical_reasons": dossier["deterministic_reasons"],
        "candidate_count": len(candidates),
        "ruleset_version": TRIAGE_RULESET_V2_CANDIDATE,
        "review_action": dossier["review_action"],
        "review_action_reason": dossier["review_action_reason"],
        # Ajout du dossier complet pour réutilisation si nécessaire sans casser le JSONL
        "comparison_dossier": dossier,
    }


def import_candidate_from_record(record: dict) -> dict | None:
    if record["decision"] != "NOT_FOUND_IN_FT_SNAPSHOT":
        return None
    fw = record["free_work"]
    if not fw.get("source_id") or not fw.get("title"):
        return None
    return {
        "free_work_source_id": fw["source_id"],
        "title": fw["title"],
        "company": fw.get("company"),
        "location": fw.get("location"),
        "source_url": fw.get("url"),
        "source_url_resolution_method": fw.get("url_resolution_method"),
        "skills": fw.get("skills") or [],
        "soft_skills": fw.get("soft_skills") or [],
        "import_status": "PENDING_HUMAN_VALIDATION",
        "import_eligible": False,
    }


def review_row_from_record(record: dict, raw_candidates: list[dict]) -> dict:
    dossier = record.get("comparison_dossier")
    if not dossier:
        # Fallback au cas où
        fw = record["free_work"]
        return {
            "priorite_revue": "HAUTE",
            "free_work_source_id": fw["source_id"],
            "decision_v2": record["decision"],
            "motif_revue": "; ".join(record["technical_reasons"]),
            "score_similarite": "Score de similarité: N/A",
            "couverture_preuves": "0%",
            "titre_free_work": fw.get("title") or "",
            "entreprise_free_work": fw.get("company") or "",
            "localisation_free_work": json.dumps(fw.get("location"), ensure_ascii=False) if fw.get("location") else "",
            "competences_free_work": "",
            "soft_skills_free_work": "",
            "description_free_work": fw.get("description_excerpt") or "",
            "france_travail_id": "",
            "titre_france_travail": "",
            "entreprise_france_travail": "",
            "localisation_france_travail": "",
            "code_rome_france_travail": "",
            "similarite_titre": "",
            "comparaison_entreprise": "",
            "comparaison_localisation": "",
            "similarite_description": "",
            "comparaison_rome": "",
            "resume_decision": "",
            "elements_concordants": "",
            "points_de_vigilance": "",
            "action_recommandee": "",
            "decision_humaine": "",
            "commentaire_humain": "",
            "verifie_par": "",
            "date_verification": "",
        }

    fw = dossier["free_work_offer"]
    comp = dossier["comparison"]
    synthesis = dossier["human_review_synthesis"]
    best_candidate = dossier["france_travail_candidate"] or {}

    # Formatage propre des compétences
    skills_list = [s.get("name") or s.get("name_normalized") or "" for s in fw.get("skills", [])]
    skills_str = " | ".join([s for s in skills_list if s])
    
    soft_skills_list = [s.get("name") or s.get("name_normalized") or "" for s in fw.get("soft_skills", [])]
    soft_skills_str = " | ".join([s for s in soft_skills_list if s])

    # Extraction d'une description propre sans retour à la ligne HTML/bruts
    desc_clean = (fw.get("description_excerpt") or "").replace("\r", " ").replace("\n", " ").strip()

    # Formater score de similarité
    score_val = comp["score_global"]
    score_str = f"Score de similarité : {int(round(score_val))}/100" if score_val is not None else "Score de similarité : 0/100"

    return {
        "priorite_revue": dossier["human_review_priority"],
        "free_work_source_id": fw["source_id"],
        "decision_v2": dossier["deterministic_decision"],
        "motif_revue": "; ".join(dossier["deterministic_reasons"]),
        "score_similarite": score_str,
        "couverture_preuves": f"{comp['evidence_coverage']}%",
        
        "titre_free_work": fw.get("title") or "",
        "entreprise_free_work": fw.get("company") or "",
        "localisation_free_work": json.dumps(fw.get("location"), ensure_ascii=False) if fw.get("location") else "",
        "competences_free_work": skills_str,
        "soft_skills_free_work": soft_skills_str,
        "description_free_work": desc_clean,
        
        "france_travail_id": best_candidate.get("france_travail_id") or "",
        "titre_france_travail": best_candidate.get("title") or "",
        "entreprise_france_travail": best_candidate.get("company_name") or "",
        "localisation_france_travail": best_candidate.get("postal_code") or "",
        "code_rome_france_travail": best_candidate.get("rome_code") or "",
        
        "similarite_titre": comp["title_human"],
        "comparaison_entreprise": comp["company_human"],
        "comparaison_localisation": comp["location_human"],
        "similarite_description": comp["description_human"],
        "comparaison_rome": comp["rome_human"],
        
        "resume_decision": synthesis["resume_decision"],
        "elements_concordants": synthesis["elements_concordants"],
        "points_de_vigilance": synthesis["points_de_vigilance"],
        "action_recommandee": synthesis["action_recommandee"],
        
        "decision_humaine": "",
        "commentaire_humain": "",
        "verifie_par": "",
        "date_verification": "",
    }


def write_review_queue(path: Path, rows: list[dict]) -> None:
    # Ordre strict des colonnes demandé par le brief
    fieldnames = [
        # Identification
        "priorite_revue",
        "free_work_source_id",
        "decision_v2",
        "motif_revue",
        "score_similarite",
        "couverture_preuves",
        
        # Offre Free-Work
        "titre_free_work",
        "entreprise_free_work",
        "localisation_free_work",
        "competences_free_work",
        "soft_skills_free_work",
        "description_free_work",
        
        # Meilleur candidat France Travail
        "france_travail_id",
        "titre_france_travail",
        "entreprise_france_travail",
        "localisation_france_travail",
        "code_rome_france_travail",
        
        # Comparaison
        "similarite_titre",
        "comparaison_entreprise",
        "comparaison_localisation",
        "similarite_description",
        "comparaison_rome",
        
        # Synthèse humaine
        "resume_decision",
        "elements_concordants",
        "points_de_vigilance",
        "action_recommandee",
        
        # Saisie humaine (colonnes vides)
        "decision_humaine",
        "commentaire_humain",
        "verifie_par",
        "date_verification",
    ]
    
    # Tri déterministe par priorité (HAUTE -> MOYENNE -> FAIBLE -> HORS_REVUE) puis par score décroissant
    priority_order = {"HAUTE": 0, "MOYENNE": 1, "FAIBLE": 2, "HORS_REVUE": 3}
    
    def sort_key(row):
        prio = row.get("priorite_revue", "HORS_REVUE")
        prio_val = priority_order.get(prio, 3)
        # Extraire le score numérique à partir de la chaîne "Score de similarité : X/100"
        score_val = 0
        match = re.search(r"(\d+)/100", row.get("score_similarite", ""))
        if match:
            score_val = int(match.group(1))
        # Trier d'abord par priorité ascendante (0 avant 1), puis par score descendant (-score_val)
        return (prio_val, -score_val, row.get("free_work_source_id", ""))

    sorted_rows = sorted(rows, key=sort_key)

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in sorted_rows:
            # Filtrer pour ne garder que les colonnes déclarées dans fieldnames
            filtered_row = {k: row.get(k, "") for k in fieldnames}
            writer.writerow(filtered_row)



def replay_triage_v2(
    candidate_matches_path: Path,
    triage_results_path: Path,
    output_dir: Path,
    raw_offers_path: Path | None = None,
    normalized_offers_path: Path | None = None,
    france_travail_snapshot_path: Path | None = None,
    run_id: str = "run_triage_v2_preview_20260624",
    debug_artifacts: bool = False,
    legacy_artifacts: bool = False,
    thresholds: TriageThresholds = TriageThresholds(),
) -> dict:
    start = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_matches = load_json(candidate_matches_path)
    triage_results = load_json(triage_results_path)
    triage_by_id = {str(item["free_work_source_id"]): item for item in triage_results}
    raw_url_lookup = build_raw_offer_url_lookup(raw_offers_path)
    free_work_details_lookup = build_free_work_details_lookup(normalized_offers_path)
    france_travail_lookup = build_france_travail_lookup(france_travail_snapshot_path)

    counters = CounterDict()
    v1_counters = CounterDict()
    url_counters = CounterDict()
    integrity_counters = CounterDict()
    import_candidates = []
    review_rows = []
    warnings = []
    reactis_case = None
    all_decision_ids = set()
    decisions_path = output_dir / "triage_decisions.jsonl"

    with decisions_path.open("w", encoding="utf-8", newline="\n") as decisions_file:
        total = len(candidate_matches)
        for index, match_entry in enumerate(candidate_matches, start=1):
            source_id = canonical_source_id(match_entry.get("free_work_source_id"))
            if source_id is None:
                raise ValueError("Missing Free-Work source id in candidate matches")
            if source_id in all_decision_ids:
                raise ValueError(f"Duplicate Free-Work source id in candidate matches: {source_id}")
            all_decision_ids.add(source_id)

            triage_entry = triage_by_id.get(source_id)
            v1_counters.add((triage_entry or {}).get("triage_category") or "UNKNOWN")
            raw_resolution = raw_url_lookup.get(source_id)
            url_resolution = raw_resolution or resolve_free_work_url(None, match_entry.get("free_work_source_url"))
            url_counters.add(url_resolution.method)
            free_work_details = free_work_details_lookup.get(source_id)
            if free_work_details is None:
                integrity_counters.add("normalized_offers_missing")
            else:
                integrity_counters.add("normalized_offers_found")
            best = (match_entry.get("top_candidates") or [None])[0]
            france_travail_offer = france_travail_lookup.get(str((best or {}).get("france_travail_id"))) if best else None
            record = make_decision_record(match_entry, triage_entry, url_resolution, thresholds, free_work_details, france_travail_offer)
            expected_skills = free_work_details.get("skills") if free_work_details and isinstance(free_work_details.get("skills"), list) else []
            if expected_skills != (record.get("free_work") or {}).get("skills"):
                integrity_counters.add("skill_propagation_failures")
            counters.add(record["decision"])
            decisions_file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

            import_candidate = import_candidate_from_record(record)
            if import_candidate:
                import_candidates.append(import_candidate)
            if record["decision"] == "UNCERTAIN" and record["review_action"] == "REVIEW_NOW":
                review_rows.append(review_row_from_record(record, match_entry.get("top_candidates") or []))
            if source_id == "14277":
                reactis_case = {
                    "old_url": match_entry.get("free_work_source_url"),
                    "old_url_origin": "normalize_free_work_offers.py built source_url from raw @id; candidate_matches copied that normalized source_url.",
                    "raw_url": url_resolution.raw_url,
                    "new_url": url_resolution.absolute_url,
                    "url_resolution_method": url_resolution.method,
                    "v1_category": (triage_entry or {}).get("triage_category"),
                    "v2_decision": record["decision"],
                    "best_candidate_human_explanation": record["human_explanation"],
                }

            if index % 1000 == 0 or index == total:
                elapsed = time.time() - start
                speed = index / elapsed if elapsed else 0
                eta = (total - index) / speed if speed else 0
                print(
                    f"[V2 replay] {index}/{total} - {index / total * 100:.2f}% - "
                    f"elapsed {elapsed:.1f}s - heartbeat {time.strftime('%H:%M:%S')} - "
                    f"{speed:.1f} offres/s - ETA {eta:.1f}s"
                )

    write_json(output_dir / "import_candidates.json", import_candidates)
    write_review_queue(output_dir / "review_queue.csv", review_rows)

    uncertainty_rate = counters["UNCERTAIN"] / len(candidate_matches) * 100 if candidate_matches else 0.0
    url_legacy_or_invalid = url_counters["LEGACY_URL_REBUILT"]
    normalized_missing = integrity_counters["normalized_offers_missing"]
    if normalized_missing:
        warnings.append(
            {
                "code": "NORMALIZED_FREE_WORK_OFFER_MISSING",
                "count": normalized_missing,
                "message": "Certaines offres candidate_matches n'ont pas ete retrouvees dans offers_normalized.json.",
            }
        )
    # Compter les actions de revue
    review_actions_counters = CounterDict()
    
    # Répartitions détaillées pour les cas UNCERTAIN
    # Par bande de score (ex. <40, 40-50, 50-60, 60-70, >=70)
    uncertain_score_dist = {
        "REVIEW_NOW": CounterDict(),
        "DEFER_DATA_INCOMPLETE": CounterDict()
    }
    # Par motif
    uncertain_reason_dist = {
        "REVIEW_NOW": CounterDict(),
        "DEFER_DATA_INCOMPLETE": CounterDict()
    }
    # Par couverture des preuves (ex. <80%, 80-90%, >=90%)
    uncertain_coverage_dist = {
        "REVIEW_NOW": CounterDict(),
        "DEFER_DATA_INCOMPLETE": CounterDict()
    }
    # Par présence/absence d'un candidat crédible
    uncertain_has_credible_dist = {
        "REVIEW_NOW": CounterDict(),
        "DEFER_DATA_INCOMPLETE": CounterDict()
    }
    # Par ancien doublon V1 ou non
    uncertain_is_v1_dist = {
        "REVIEW_NOW": CounterDict(),
        "DEFER_DATA_INCOMPLETE": CounterDict()
    }

    with decisions_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            act = rec.get("review_action")
            review_actions_counters.add(act)
            
            if rec.get("decision") == "UNCERTAIN":
                score_val = (rec.get("score") or {}).get("score_global") or 0.0
                if score_val < 40.0:
                    score_band = "<40"
                elif score_val < 50.0:
                    score_band = "40-50"
                elif score_val < 60.0:
                    score_band = "50-60"
                elif score_val < 70.0:
                    score_band = "60-70"
                else:
                    score_band = ">=70"
                uncertain_score_dist[act].add(score_band)
                
                for r_code in rec.get("technical_reasons") or []:
                    uncertain_reason_dist[act].add(r_code)
                
                cov_val = (rec.get("score") or {}).get("evidence_coverage") or 0
                if cov_val < 80:
                    cov_band = "<80%"
                elif cov_val < 90:
                    cov_band = "80-90%"
                else:
                    cov_band = ">=90%"
                uncertain_coverage_dist[act].add(cov_band)
                
                has_cred = "YES" if score_val >= thresholds.credible_candidate_min_score else "NO"
                uncertain_has_credible_dist[act].add(has_cred)
                
                # Récupération de l'état V1
                source_id = rec["free_work"]["source_id"]
                triage_entry = triage_by_id.get(source_id)
                is_v1 = "YES" if (triage_entry and triage_entry.get("triage_category") == "DUPLICATE_HIGH_CONFIDENCE") else "NO"
                uncertain_is_v1_dist[act].add(is_v1)

    manifest = {
        "run_id": run_id,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "matching_version": "existing_candidate_matches",
        "triage_version": TRIAGE_RULESET_V2_CANDIDATE,
        "input_files": {
            "candidate_matches": str(candidate_matches_path).replace("\\", "/"),
            "candidate_matches_sha256": sha256_file(candidate_matches_path),
            "triage_results": str(triage_results_path).replace("\\", "/"),
            "triage_results_sha256": sha256_file(triage_results_path),
            "raw_offers": str(raw_offers_path).replace("\\", "/") if raw_offers_path else None,
            "raw_offers_sha256": sha256_file(raw_offers_path) if raw_offers_path and raw_offers_path.exists() else None,
            "normalized_offers": str(normalized_offers_path).replace("\\", "/") if normalized_offers_path else None,
            "normalized_offers_sha256": sha256_file(normalized_offers_path) if normalized_offers_path and normalized_offers_path.exists() else None,
            "france_travail_snapshot": str(france_travail_snapshot_path).replace("\\", "/") if france_travail_snapshot_path else None,
            "france_travail_snapshot_sha256": sha256_file(france_travail_snapshot_path) if france_travail_snapshot_path and france_travail_snapshot_path.exists() else None,
        },
        "counters": {
            "total_processed": len(candidate_matches),
            "PRESENT_IN_FT_SNAPSHOT": counters["PRESENT_IN_FT_SNAPSHOT"],
            "NOT_FOUND_IN_FT_SNAPSHOT": counters["NOT_FOUND_IN_FT_SNAPSHOT"],
            "UNCERTAIN": counters["UNCERTAIN"],
            "PROCESSING_ERROR": counters["PROCESSING_ERROR"],
            **counters.to_dict(),
            "uncertainty_rate_percent": round(uncertainty_rate, 2),
            "import_candidates": len(import_candidates),
            "v1_categories": v1_counters.to_dict(),
            
            # Nouveaux compteurs demandés
            "uncertain_total": counters["UNCERTAIN"],
            "human_review_required": review_actions_counters["REVIEW_NOW"],
            "deferred_data_incomplete": review_actions_counters["DEFER_DATA_INCOMPLETE"],
            "no_manual_review": review_actions_counters["NO_MANUAL_REVIEW"],
            
            # Statistiques et répartitions détaillées pour les cas UNCERTAIN
            "uncertain_distributions": {
                "by_score_band": {
                    "REVIEW_NOW": uncertain_score_dist["REVIEW_NOW"].to_dict(),
                    "DEFER_DATA_INCOMPLETE": uncertain_score_dist["DEFER_DATA_INCOMPLETE"].to_dict()
                },
                "by_reason_code": {
                    "REVIEW_NOW": uncertain_reason_dist["REVIEW_NOW"].to_dict(),
                    "DEFER_DATA_INCOMPLETE": uncertain_reason_dist["DEFER_DATA_INCOMPLETE"].to_dict()
                },
                "by_evidence_coverage": {
                    "REVIEW_NOW": uncertain_coverage_dist["REVIEW_NOW"].to_dict(),
                    "DEFER_DATA_INCOMPLETE": uncertain_coverage_dist["DEFER_DATA_INCOMPLETE"].to_dict()
                },
                "by_credible_candidate_presence": {
                    "REVIEW_NOW": uncertain_has_credible_dist["REVIEW_NOW"].to_dict(),
                    "DEFER_DATA_INCOMPLETE": uncertain_has_credible_dist["DEFER_DATA_INCOMPLETE"].to_dict()
                },
                "by_v1_historical_uncertainty": {
                    "REVIEW_NOW": uncertain_is_v1_dist["REVIEW_NOW"].to_dict(),
                    "DEFER_DATA_INCOMPLETE": uncertain_is_v1_dist["DEFER_DATA_INCOMPLETE"].to_dict()
                }
            }
        },
        "thresholds": asdict(thresholds),
        "duration_seconds": round(time.time() - start, 2),
        "warnings": warnings,
        "url_counters": {
            **url_counters.to_dict(),
            "reliable_urls": url_counters["RAW_ABSOLUTE_URL"] + url_counters["RELATIVE_HREF_RESOLVED"],
            "unavailable_urls": url_counters["URL_UNAVAILABLE"],
            "legacy_invalid_urls_rejected": url_legacy_or_invalid,
            "valid_urls": url_counters["RAW_ABSOLUTE_URL"] + url_counters["RELATIVE_HREF_RESOLVED"],
            "missing_urls": url_counters["URL_UNAVAILABLE"],
            "legacy_or_incorrect_urls": url_legacy_or_invalid,
            "remaining_job_postings_urls_in_main_output": count_job_postings_urls(decisions_path),
        },
        "skill_propagation_integrity": {
            "normalized_offers_found": integrity_counters["normalized_offers_found"],
            "normalized_offers_missing": integrity_counters["normalized_offers_missing"],
            "skill_propagation_failures": integrity_counters["skill_propagation_failures"],
            "duplicate_source_ids": 0,
        },
        "structured_skill_statistics": build_skill_statistics(decisions_path),
        "structured_skill_warning": "Les statistiques reposent sur les compétences structurées fournies par Free-Work. Elles peuvent inclure des compétences techniques, fonctionnelles ou transversales et ne couvrent pas nécessairement toutes les compétences citées dans les descriptions.",
        "reactis_ecully_case": reactis_case,
        "artifact_policy": {
            "main_files": [
                "run_manifest.json",
                "triage_decisions.jsonl",
                "import_candidates.json",
                "review_queue.csv",
            ],
            "debug_artifacts_enabled": debug_artifacts,
            "legacy_artifacts_enabled": legacy_artifacts,
        },
    }
    write_json(output_dir / "run_manifest.json", manifest)
    if debug_artifacts:
        debug_dir = output_dir / "debug"
        debug_dir.mkdir(exist_ok=True)
        write_json(debug_dir / "thresholds.json", asdict(thresholds))
    if legacy_artifacts:
        legacy_dir = output_dir / "legacy"
        legacy_dir.mkdir(exist_ok=True)
        write_json(legacy_dir / "v1_category_counts.json", v1_counters.to_dict())
    return manifest


def count_job_postings_urls(jsonl_path: Path) -> int:
    count = 0
    with jsonl_path.open("r", encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            exposed_url = (record.get("free_work") or {}).get("url")
            if is_legacy_job_postings_url(exposed_url):
                count += 1
    return count


def build_skill_statistics(jsonl_path: Path) -> dict:
    total_offers = 0
    offers_with = 0
    total_links = 0
    global_skills = {}
    by_decision = defaultdict(lambda: {"offers_with_structured_skills": 0, "total_offer_skill_links": 0, "skills": {}})
    with jsonl_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            total_offers += 1
            record = json.loads(line)
            decision = record.get("decision")
            skills = (record.get("free_work") or {}).get("skills") or []
            if skills:
                offers_with += 1
                by_decision[decision]["offers_with_structured_skills"] += 1
            total_links += len(skills)
            by_decision[decision]["total_offer_skill_links"] += len(skills)
            seen_in_offer = set()
            for skill in skills:
                normalized = skill.get("name_normalized") or skill.get("slug") or skill.get("source_skill_id")
                if not normalized or normalized in seen_in_offer:
                    continue
                seen_in_offer.add(normalized)
                display_name = skill.get("name") or normalized
                global_skills.setdefault(normalized, {"name": display_name, "normalized_name": normalized, "offer_count": 0})
                global_skills[normalized]["offer_count"] += 1
                decision_skills = by_decision[decision]["skills"]
                decision_skills.setdefault(normalized, {"name": display_name, "normalized_name": normalized, "offer_count": 0})
                decision_skills[normalized]["offer_count"] += 1

    def top_twenty(skill_map):
        return sorted(skill_map.values(), key=lambda item: (-item["offer_count"], item["normalized_name"]))[:20]

    by_decision_out = {}
    for decision, stats in by_decision.items():
        by_decision_out[decision] = {
            "offers_with_structured_skills": stats["offers_with_structured_skills"],
            "offers_without_structured_skills": sum(1 for _ in []),  # filled below
            "total_offer_skill_links": stats["total_offer_skill_links"],
            "unique_structured_skills": len(stats["skills"]),
            "top_structured_skills": top_twenty(stats["skills"]),
        }
    decision_counts = CounterDict()
    with jsonl_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                decision_counts.add(json.loads(line).get("decision"))
    for decision, count in decision_counts.items():
        by_decision_out[decision]["offers_without_structured_skills"] = count - by_decision_out[decision]["offers_with_structured_skills"]

    return {
        "all_offers": {
            "offers_with_structured_skills": offers_with,
            "offers_without_structured_skills": total_offers - offers_with,
            "unique_structured_skills": len(global_skills),
            "total_offer_skill_links": total_links,
            "top_structured_skills": top_twenty(global_skills),
        },
        "by_decision": by_decision_out,
    }


class CounterDict(defaultdict):
    def __init__(self):
        super().__init__(int)

    def add(self, key: str) -> None:
        self[str(key)] += 1

    def to_dict(self) -> dict:
        return dict(sorted(self.items()))


def decision_volume_summary(manifest: dict) -> dict:
    counters = manifest["counters"]
    return {
        "present": counters.get("PRESENT_IN_FT_SNAPSHOT", 0),
        "not_found": counters.get("NOT_FOUND_IN_FT_SNAPSHOT", 0),
        "uncertain": counters.get("UNCERTAIN", 0),
        "processing_error": counters.get("PROCESSING_ERROR", 0),
        "uncertainty_rate_percent": counters.get("uncertainty_rate_percent", 0),
    }

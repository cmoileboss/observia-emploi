"""Prépare des paquets aveugles et valide les annotations humaines."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PROTOCOL_VERSION = "observia-human-annotation-v1"
ANNOTATOR_SEEDS = {
    "annotator_1": "observia-human-annotation-v1-annotator-1",
    "annotator_2": "observia-human-annotation-v1-annotator-2",
}
PILOT_SEED = "observia-human-annotation-v1-pilot"
PILOT_OFFER_COUNT = 5

DUPLICATE_MIN_DESCRIPTION_LENGTH = 200
DUPLICATE_MIN_LENGTH_RATIO = 0.90
DUPLICATE_MIN_TOKEN_JACCARD = 0.95

VALID_MAIN_CRITERIA = (
    "METIER_ACTIVITES",
    "COMPETENCES",
    "NIVEAU_PREREQUIS",
    "SECTEUR_DEBOUCHES",
    "GENERALITE_SPECIALISATION",
)
VALID_UNCERTAINTY_VALUES = ("OUI", "NON")

ANNOTATION_INPUT_COLUMNS = (
    "score",
    "critere_principal",
    "justification",
    "incertain",
)
ANNOTATOR_COLUMNS = (
    "pair_id",
    "offer_group_id",
    "offre_intitule",
    "offre_appellation",
    "offre_code_rome",
    "offre_libelle_rome",
    "offre_description",
    "offre_competences",
    "contexte_source_complementaire",
    "certification_code_rncp",
    "certification_intitule",
    "certification_niveau",
    "certification_activites",
    "certification_competences_attestees",
    "certification_metiers_accessibles",
    "certification_secteurs_activite",
    "certification_prerequis",
    "certification_blocs_competences",
    *ANNOTATION_INPUT_COLUMNS,
)
PROTECTED_COLUMNS = tuple(
    column for column in ANNOTATOR_COLUMNS if column not in ANNOTATION_INPUT_COLUMNS
)
HIDDEN_FIELDS = (
    "source",
    "source_offer_id",
    "database_offer_id",
    "split",
    "raison_selection_candidat",
    "ordre_pool_original",
    "identite_methode_matching",
)

LOT5_ARTIFACT_NAMES = (
    "sample_manifest.json",
    "evaluation_offers.json",
    "candidate_pools.jsonl",
    "annotation_template.csv",
)


@dataclass(frozen=True)
class Lot5AnnotationInputs:
    """Regroupe les quatre artefacts lot 5 déjà chargés et vérifiés."""

    manifest: Mapping[str, Any]
    offers: tuple[Mapping[str, Any], ...]
    candidate_pools: tuple[Mapping[str, Any], ...]
    annotation_pairs: frozenset[tuple[str, str, str]]
    artifact_sha256: Mapping[str, str]


@dataclass(frozen=True)
class CrossSplitDuplicate:
    """Décrit un doublon exact ou quasi exact traversant les deux splits."""

    duplicate_type: str
    development_offer: tuple[str, str]
    validation_offer: tuple[str, str]
    token_jaccard: float | None = None
    length_ratio: float | None = None


@dataclass(frozen=True)
class DuplicateAuditResult:
    """Contient les doublons inter-splits trouvés par l'audit préalable."""

    exact_duplicates: tuple[CrossSplitDuplicate, ...]
    near_duplicates: tuple[CrossSplitDuplicate, ...]

    @property
    def has_cross_split_duplicates(self) -> bool:
        """Indique si au moins un doublon bloquant a été détecté."""
        return bool(self.exact_duplicates or self.near_duplicates)


@dataclass(frozen=True)
class AnnotationPackageResult:
    """Regroupe les octets générés et les offres retenues pour le pilote."""

    artifacts: Mapping[str, bytes]
    pilot_offer_keys: tuple[tuple[str, str], ...]
    duplicate_audit: DuplicateAuditResult
    packet_counts: Mapping[str, Mapping[str, int]]
    pool_size: int


@dataclass(frozen=True)
class AnnotationValidationResult:
    """Résume la validation réussie d'un fichier annoté."""

    row_count: int
    pair_count: int


def _sha256_bytes(content: bytes) -> str:
    """Calcule le SHA-256 hexadécimal d'un contenu binaire."""
    return hashlib.sha256(content).hexdigest()


def _stable_hash(seed: str, *parts: object) -> str:
    """Calcule une clé SHA-256 déterministe à partir de valeurs ordonnées."""
    serialized = "\x1f".join(str(part) for part in (seed, *parts))
    return _sha256_bytes(serialized.encode("utf-8"))


def _offer_key(item: Mapping[str, Any]) -> tuple[str, str]:
    """Retourne la clé stable source et identifiant source d'une offre."""
    source = str(item.get("source") or "").strip()
    source_offer_id = str(item.get("source_offer_id") or "").strip()
    if not source or not source_offer_id:
        raise ValueError("Une offre ne possède pas une provenance complète.")
    return source, source_offer_id


def normalize_duplicate_text(value: object) -> str:
    """Normalise un texte Unicode pour l'audit conservateur des doublons."""
    raw_value = "" if value is None else str(value)
    decomposed = unicodedata.normalize("NFKD", raw_value)
    without_marks = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[^\w]+", " ", without_marks.casefold()).strip()


def _token_jaccard(left: str, right: str) -> float:
    """Calcule le Jaccard des ensembles de mots de deux textes normalisés."""
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    if not union:
        return 1.0
    return len(left_tokens & right_tokens) / len(union)


def audit_cross_split_duplicates(
    offers: Iterable[Mapping[str, Any]],
) -> DuplicateAuditResult:
    """Détecte les doublons exacts et quasi exacts entre les deux splits."""
    indexed_offers: list[
        tuple[Mapping[str, Any], tuple[str, str], str, str]
    ] = []
    for offer in offers:
        source_fields = offer.get("champs_sources", {})
        indexed_offers.append(
            (
                offer,
                _offer_key(offer),
                normalize_duplicate_text(source_fields.get("intitule")),
                normalize_duplicate_text(source_fields.get("description")),
            )
        )
    development = [item for item in indexed_offers if item[0].get("split") == "development"]
    validation = [item for item in indexed_offers if item[0].get("split") == "validation"]

    exact_duplicates: list[CrossSplitDuplicate] = []
    near_duplicates: list[CrossSplitDuplicate] = []
    for _, development_key, development_title, development_description in development:
        for _, validation_key, validation_title, validation_description in validation:
            if (
                development_title,
                development_description,
            ) == (validation_title, validation_description):
                exact_duplicates.append(
                    CrossSplitDuplicate(
                        duplicate_type="EXACT",
                        development_offer=development_key,
                        validation_offer=validation_key,
                    )
                )
                continue
            if development_title != validation_title:
                continue
            shortest_length = min(
                len(development_description), len(validation_description)
            )
            longest_length = max(
                len(development_description), len(validation_description)
            )
            if shortest_length < DUPLICATE_MIN_DESCRIPTION_LENGTH or not longest_length:
                continue
            length_ratio = shortest_length / longest_length
            if length_ratio < DUPLICATE_MIN_LENGTH_RATIO:
                continue
            token_jaccard = _token_jaccard(
                development_description, validation_description
            )
            if token_jaccard >= DUPLICATE_MIN_TOKEN_JACCARD:
                near_duplicates.append(
                    CrossSplitDuplicate(
                        duplicate_type="QUASI_EXACT",
                        development_offer=development_key,
                        validation_offer=validation_key,
                        token_jaccard=token_jaccard,
                        length_ratio=length_ratio,
                    )
                )
    sort_key = lambda item: (item.development_offer, item.validation_offer)
    return DuplicateAuditResult(
        exact_duplicates=tuple(sorted(exact_duplicates, key=sort_key)),
        near_duplicates=tuple(sorted(near_duplicates, key=sort_key)),
    )


def _load_json(content: bytes, artifact_name: str) -> Any:
    """Décode un artefact JSON UTF-8 avec une erreur explicite."""
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Artefact JSON invalide : {artifact_name}.") from exc


def _read_csv_rows(content: bytes, artifact_name: str) -> list[dict[str, str]]:
    """Décode un CSV UTF-8, avec ou sans BOM, en dictionnaires."""
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Artefact CSV non UTF-8 : {artifact_name}.") from exc
    return list(csv.DictReader(io.StringIO(decoded, newline="")))


def read_annotation_csv(
    content: bytes,
    artifact_name: str = "paquet d'annotation",
) -> list[dict[str, str]]:
    """Lit les lignes d'un CSV d'annotation UTF-8 avec ou sans BOM."""
    return _read_csv_rows(content, artifact_name)


def _get_uniform_pool_size(
    manifest: Mapping[str, Any],
    candidate_pools: Iterable[Mapping[str, Any]],
) -> int:
    """Lit la taille déclarée des pools ou vérifie une taille uniforme non vide."""
    pool_sizes = [len(pool.get("candidats", ())) for pool in candidate_pools]
    if not pool_sizes or any(size <= 0 for size in pool_sizes):
        raise ValueError("Chaque offre doit posséder un pool de candidats non vide.")
    actual_sizes = set(pool_sizes)
    if len(actual_sizes) != 1:
        raise ValueError("Les pools de candidats ne possèdent pas une taille uniforme.")
    declared_size = manifest.get("parametres", {}).get("candidate_pool_size")
    if declared_size is None:
        return pool_sizes[0]
    if not isinstance(declared_size, int) or isinstance(declared_size, bool) or declared_size <= 0:
        raise ValueError("La taille déclarée des pools est invalide.")
    if declared_size != pool_sizes[0]:
        raise ValueError("La taille déclarée des pools diffère des artefacts.")
    return declared_size


def load_lot5_annotation_inputs(
    artifact_contents: Mapping[str, bytes],
) -> Lot5AnnotationInputs:
    """Charge et recoupe strictement les quatre artefacts du lot 5."""
    if set(artifact_contents) != set(LOT5_ARTIFACT_NAMES):
        raise ValueError("Les quatre artefacts attendus du lot 5 sont requis.")
    manifest = _load_json(
        artifact_contents["sample_manifest.json"], "sample_manifest.json"
    )
    offers_payload = _load_json(
        artifact_contents["evaluation_offers.json"], "evaluation_offers.json"
    )
    offers = tuple(offers_payload.get("offres", ()))
    pool_lines = artifact_contents["candidate_pools.jsonl"].decode("utf-8").splitlines()
    candidate_pools = tuple(
        json.loads(line) for line in pool_lines if line.strip()
    )
    annotation_rows = _read_csv_rows(
        artifact_contents["annotation_template.csv"], "annotation_template.csv"
    )

    offers_by_key = {_offer_key(offer): offer for offer in offers}
    if len(offers_by_key) != len(offers):
        raise ValueError("Une offre apparaît plusieurs fois dans evaluation_offers.json.")
    pools_by_key = {_offer_key(pool): pool for pool in candidate_pools}
    if len(pools_by_key) != len(candidate_pools):
        raise ValueError("Une offre apparaît plusieurs fois dans candidate_pools.jsonl.")
    if set(offers_by_key) != set(pools_by_key):
        raise ValueError("Les offres et les pools du lot 5 ne correspondent pas.")

    expected_pool_size = _get_uniform_pool_size(manifest, candidate_pools)
    pool_pairs: set[tuple[str, str, str]] = set()
    for offer_key, pool in pools_by_key.items():
        candidates = pool.get("candidats", ())
        if len(candidates) != expected_pool_size:
            raise ValueError(
                f"Le pool {offer_key} ne contient pas {expected_pool_size} certifications."
            )
        for candidate in candidates:
            code_rncp = str(candidate.get("code_rncp") or "").strip()
            pair = (*offer_key, code_rncp)
            if not code_rncp or pair in pool_pairs:
                raise ValueError(f"Couple lot 5 invalide ou dupliqué : {pair}.")
            pool_pairs.add(pair)
    template_pairs = {
        (
            str(row.get("source") or "").strip(),
            str(row.get("source_offer_id") or "").strip(),
            str(row.get("code_rncp") or "").strip(),
        )
        for row in annotation_rows
    }
    if len(template_pairs) != len(annotation_rows) or template_pairs != pool_pairs:
        raise ValueError("Le modèle d'annotation du lot 5 ne correspond pas aux pools.")
    expected_offer_count = manifest.get("compteurs", {}).get("offres")
    expected_pair_count = manifest.get("compteurs", {}).get(
        "couples_offre_certification"
    )
    if expected_offer_count != len(offers) or expected_pair_count != len(pool_pairs):
        raise ValueError("Les compteurs du manifeste lot 5 sont incohérents.")
    return Lot5AnnotationInputs(
        manifest=manifest,
        offers=offers,
        candidate_pools=candidate_pools,
        annotation_pairs=frozenset(pool_pairs),
        artifact_sha256={
            name: _sha256_bytes(content)
            for name, content in sorted(artifact_contents.items())
        },
    )


def build_pair_id(source: str, source_offer_id: str, code_rncp: str) -> str:
    """Construit l'identifiant stable commun aux deux annotateurs."""
    digest = _stable_hash(
        PROTOCOL_VERSION, source, source_offer_id, code_rncp
    )
    return f"pair_{digest[:24]}"


def build_offer_group_id(source: str, source_offer_id: str) -> str:
    """Construit un identifiant opaque permettant de regrouper une offre."""
    digest = _stable_hash(PROTOCOL_VERSION, "offer-group", source, source_offer_id)
    return f"offer_{digest[:20]}"


def _format_competences(competences: object) -> str:
    """Formate les compétences structurées d'une offre dans une cellule CSV."""
    if not isinstance(competences, list):
        return ""
    values = []
    for competence in competences:
        code = str(competence.get("code") or "").strip()
        label = str(competence.get("libelle") or "").strip()
        value = " — ".join(part for part in (code, label) if part)
        if value:
            values.append(value)
    return " | ".join(values)


def _format_france_travail_requirements(requirements: object) -> str:
    """Formate lisiblement les exigences de formation France Travail."""
    if not isinstance(requirements, list):
        return ""
    formatted_requirements = []
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            continue
        formatted = " — ".join(
            str(requirement.get(field) or "").strip()
            for field in ("intitule", "code_source", "niveau", "commentaire")
            if str(requirement.get(field) or "").strip()
        )
        if formatted:
            formatted_requirements.append(formatted)
    return " | ".join(formatted_requirements)


def build_source_complementary_context(
    source: object,
    source_fields: Mapping[str, Any],
) -> str:
    """Construit le contexte complémentaire générique selon les données source."""
    generic_context = source_fields.get("contexte_source_complementaire")
    if isinstance(generic_context, str) and generic_context.strip():
        return generic_context.strip()
    if source == "FRANCE_TRAVAIL":
        return _format_france_travail_requirements(
            source_fields.get("exigences_france_travail")
        )
    return ""


def _format_level(level: object) -> str:
    """Formate le code et le libellé du niveau officiel RNCP."""
    if not isinstance(level, Mapping):
        return ""
    return " — ".join(
        str(level.get(field) or "").strip()
        for field in ("code", "libelle")
        if str(level.get(field) or "").strip()
    )


def _format_blocks(blocks: object) -> str:
    """Formate les blocs de compétences officiels dans un ordre stable."""
    if not isinstance(blocks, list):
        return ""
    formatted_blocks = []
    for block in blocks:
        formatted = " — ".join(
            str(block.get(field) or "").strip()
            for field in ("code", "libelle", "competences")
            if str(block.get(field) or "").strip()
        )
        if formatted:
            formatted_blocks.append(formatted)
    return " | ".join(formatted_blocks)


def _annotation_context_row(
    offer: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, str]:
    """Construit une ligne visible sans les champs cachés du protocole."""
    source, source_offer_id = _offer_key(offer)
    source_fields = offer.get("champs_sources", {})
    official = candidate.get("donnees_officielles", {})
    code_rncp = str(candidate.get("code_rncp") or "").strip()
    return {
        "pair_id": build_pair_id(source, source_offer_id, code_rncp),
        "offer_group_id": build_offer_group_id(source, source_offer_id),
        "offre_intitule": str(source_fields.get("intitule") or ""),
        "offre_appellation": str(source_fields.get("appellation") or ""),
        "offre_code_rome": str(offer.get("code_rome") or ""),
        "offre_libelle_rome": str(source_fields.get("libelle_rome") or ""),
        "offre_description": str(source_fields.get("description") or ""),
        "offre_competences": _format_competences(
            source_fields.get("competences")
        ),
        "contexte_source_complementaire": build_source_complementary_context(
            offer.get("source"),
            source_fields,
        ),
        "certification_code_rncp": code_rncp,
        "certification_intitule": str(
            candidate.get("intitule_officiel") or ""
        ),
        "certification_niveau": _format_level(official.get("niveau")),
        "certification_activites": str(official.get("activites_visees") or ""),
        "certification_competences_attestees": str(
            official.get("competences_attestees") or ""
        ),
        "certification_metiers_accessibles": str(
            official.get("metiers_accessibles") or ""
        ),
        "certification_secteurs_activite": str(
            official.get("secteurs_activite") or ""
        ),
        "certification_prerequis": str(official.get("prerequis") or ""),
        "certification_blocs_competences": _format_blocks(
            official.get("blocs_competences")
        ),
        "score": "",
        "critere_principal": "",
        "justification": "",
        "incertain": "",
    }


def _candidate_order(
    candidates: Sequence[Mapping[str, Any]],
    annotator_seed: str,
    source: str,
    source_offer_id: str,
) -> tuple[Mapping[str, Any], ...]:
    """Mélange un pool par tri SHA-256 déterministe propre à l'annotateur."""
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: _stable_hash(
                annotator_seed,
                source,
                source_offer_id,
                candidate.get("code_rncp"),
            ),
        )
    )


def select_pilot_offer_keys(
    offers: Iterable[Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    """Sélectionne cinq offres development maximisant les dimensions couvertes."""
    development = [offer for offer in offers if offer.get("split") == "development"]
    if len(development) < PILOT_OFFER_COUNT:
        raise ValueError("Moins de cinq offres development pour le pilote.")

    def feature_set(offer: Mapping[str, Any]) -> frozenset[str]:
        source_fields = offer.get("champs_sources", {})
        richness = offer.get("richesse", {})
        return frozenset(
            {
                f"ROME:{offer.get('code_rome')}",
                f"DESCRIPTION:{richness.get('description')}",
                f"COMPETENCES:{bool(source_fields.get('competences'))}",
                "CONTEXTE:"
                + str(
                    bool(
                        build_source_complementary_context(
                            offer.get("source"),
                            source_fields,
                        )
                    )
                ),
            }
        )

    remaining = list(development)
    selected: list[Mapping[str, Any]] = []
    covered_features: set[str] = set()
    while len(selected) < PILOT_OFFER_COUNT:
        ranked = sorted(
            remaining,
            key=lambda offer: (
                -len(feature_set(offer) - covered_features),
                _stable_hash(PILOT_SEED, *_offer_key(offer)),
            ),
        )
        chosen = ranked[0]
        selected.append(chosen)
        covered_features.update(feature_set(chosen))
        remaining.remove(chosen)
    return tuple(_offer_key(offer) for offer in selected)


def serialize_annotation_csv(rows: Sequence[Mapping[str, str]]) -> bytes:
    """Sérialise des lignes avec en-tête UTF-8 et fins de ligne LF."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=ANNOTATOR_COLUMNS,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _build_packet_rows(
    offer_keys: Sequence[tuple[str, str]],
    offers_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    pools_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    annotator_name: str,
    first_orders: Mapping[tuple[str, str], tuple[str, ...]] | None = None,
) -> tuple[list[dict[str, str]], dict[tuple[str, str], tuple[str, ...]]]:
    """Construit un paquet aveugle et mémorise l'ordre de chaque pool."""
    seed = ANNOTATOR_SEEDS[annotator_name]
    rows: list[dict[str, str]] = []
    orders: dict[tuple[str, str], tuple[str, ...]] = {}
    for offer_key in sorted(
        offer_keys,
        key=lambda key: build_offer_group_id(*key),
    ):
        candidates = _candidate_order(
            pools_by_key[offer_key]["candidats"], seed, *offer_key
        )
        codes = tuple(str(candidate["code_rncp"]) for candidate in candidates)
        if first_orders is not None and codes == first_orders[offer_key]:
            candidates = candidates[1:] + candidates[:1]
            codes = tuple(str(candidate["code_rncp"]) for candidate in candidates)
        orders[offer_key] = codes
        rows.extend(
            _annotation_context_row(offers_by_key[offer_key], candidate)
            for candidate in candidates
        )
    return rows, orders


def _reference_jsonl(
    offers_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    pools_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> bytes:
    """Sérialise la référence cachée des couples dans un ordre stable."""
    references = []
    for offer_key in sorted(offers_by_key):
        offer = offers_by_key[offer_key]
        pool = pools_by_key[offer_key]
        for original_index, candidate in enumerate(pool["candidats"]):
            code_rncp = str(candidate["code_rncp"])
            references.append(
                {
                    "pair_id": build_pair_id(*offer_key, code_rncp),
                    "offer_group_id": build_offer_group_id(*offer_key),
                    "source": offer_key[0],
                    "source_offer_id": offer_key[1],
                    "database_offer_id": offer.get("database_offer_id"),
                    "split": offer.get("split"),
                    "code_rncp": code_rncp,
                    "raison_selection_candidat": candidate.get(
                        "raison_selection"
                    ),
                    "ordre_pool_original": original_index,
                }
            )
    references.sort(key=lambda item: item["pair_id"])
    return (
        "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in references
        )
        + "\n"
    ).encode("utf-8")


def build_annotation_packages(
    inputs: Lot5AnnotationInputs,
) -> AnnotationPackageResult:
    """Audite puis génère les paquets pilotes et complets des deux annotateurs."""
    duplicate_audit = audit_cross_split_duplicates(inputs.offers)
    if duplicate_audit.has_cross_split_duplicates:
        concerned = [
            f"{item.development_offer}->{item.validation_offer}"
            for item in (
                *duplicate_audit.exact_duplicates,
                *duplicate_audit.near_duplicates,
            )
        ]
        raise ValueError(
            "Doublons inter-splits détectés, génération arrêtée : "
            + ", ".join(concerned)
        )

    offers_by_key = {_offer_key(offer): offer for offer in inputs.offers}
    pools_by_key = {_offer_key(pool): pool for pool in inputs.candidate_pools}
    pool_size = _get_uniform_pool_size(inputs.manifest, inputs.candidate_pools)
    development_keys = tuple(
        key for key, offer in offers_by_key.items() if offer.get("split") == "development"
    )
    validation_keys = tuple(
        key for key, offer in offers_by_key.items() if offer.get("split") == "validation"
    )
    if not development_keys or not validation_keys:
        raise ValueError("Les artefacts doivent contenir development et validation.")
    if len(development_keys) < PILOT_OFFER_COUNT:
        raise ValueError("Les offres development sont insuffisantes pour le pilote.")
    pilot_keys = select_pilot_offer_keys(inputs.offers)

    artifacts: dict[str, bytes] = {}
    packet_specs = (
        ("pilot", pilot_keys),
        ("development", development_keys),
        ("validation", validation_keys),
    )
    packet_counts: dict[str, dict[str, int]] = {}
    for packet_name, offer_keys in packet_specs:
        first_rows, first_orders = _build_packet_rows(
            offer_keys,
            offers_by_key,
            pools_by_key,
            "annotator_1",
        )
        second_rows, _ = _build_packet_rows(
            offer_keys,
            offers_by_key,
            pools_by_key,
            "annotator_2",
            first_orders,
        )
        first_name = f"{packet_name}_annotator_1.csv"
        second_name = f"{packet_name}_annotator_2.csv"
        artifacts[first_name] = serialize_annotation_csv(first_rows)
        artifacts[second_name] = serialize_annotation_csv(second_rows)
        packet_counts[first_name] = {
            "offres": len(offer_keys),
            "couples": len(first_rows),
        }
        packet_counts[second_name] = {
            "offres": len(offer_keys),
            "couples": len(second_rows),
        }
    artifacts["annotation_reference.jsonl"] = _reference_jsonl(
        offers_by_key, pools_by_key
    )

    manifest = {
        "version_protocole": PROTOCOL_VERSION,
        "source_lot5": {
            "format_version": inputs.manifest.get("format_version"),
            "sha256": dict(sorted(inputs.artifact_sha256.items())),
        },
        "graines": {
            "pilote": PILOT_SEED,
            **ANNOTATOR_SEEDS,
        },
        "paquets": dict(sorted(packet_counts.items())),
        "champs_caches": list(HIDDEN_FIELDS),
        "audit_doublons": {
            "normalisation": "NFKD, suppression des diacritiques, casefold, espaces normalisés",
            "doublon_exact": "titre et description normalisés identiques",
            "quasi_doublon": {
                "titre_normalise_identique": True,
                "longueur_description_minimale": DUPLICATE_MIN_DESCRIPTION_LENGTH,
                "ratio_longueur_minimal": DUPLICATE_MIN_LENGTH_RATIO,
                "jaccard_mots_minimal": DUPLICATE_MIN_TOKEN_JACCARD,
            },
            "doublons_exacts_inter_splits": 0,
            "quasi_doublons_inter_splits": 0,
        },
        "pilote": {
            "offres": PILOT_OFFER_COUNT,
            "couples_par_annotateur": PILOT_OFFER_COUNT * pool_size,
            "doit_etre_termine_et_analyse_avant_paquets_complets": True,
        },
        "validation": {
            "criteres_principaux_valides": list(VALID_MAIN_CRITERIA),
            "valeurs_incertain_valides": list(VALID_UNCERTAINTY_VALUES),
        },
    }
    artifacts["annotation_manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    return AnnotationPackageResult(
        artifacts=artifacts,
        pilot_offer_keys=pilot_keys,
        duplicate_audit=duplicate_audit,
        packet_counts=packet_counts,
        pool_size=pool_size,
    )


def export_annotation_packages(
    result: AnnotationPackageResult,
    output_directory: Path,
) -> None:
    """Écrit les artefacts canoniques et les six classeurs compagnons."""
    expected_names = {
        "annotation_manifest.json",
        "annotation_reference.jsonl",
        "pilot_annotator_1.csv",
        "pilot_annotator_2.csv",
        "development_annotator_1.csv",
        "development_annotator_2.csv",
        "validation_annotator_1.csv",
        "validation_annotator_2.csv",
    }
    if set(result.artifacts) != expected_names:
        raise ValueError("La collection de paquets d'annotation est incomplète.")
    output_directory.mkdir(parents=True, exist_ok=True)
    for name in sorted(result.artifacts):
        (output_directory / name).write_bytes(result.artifacts[name])
    from backend.services.human_annotation_workbook import (
        build_annotation_workbook,
    )

    for csv_name in sorted(name for name in expected_names if name.endswith(".csv")):
        workbook_name = f"{Path(csv_name).stem}.xlsx"
        (output_directory / workbook_name).write_bytes(
            build_annotation_workbook(result.artifacts[csv_name])
        )


def validate_completed_annotation(
    expected_template: bytes,
    completed_annotation: bytes,
) -> AnnotationValidationResult:
    """Valide les réponses et l'intégrité d'un paquet annoté complet."""
    expected_rows = _read_csv_rows(expected_template, "paquet attendu")
    completed_rows = _read_csv_rows(completed_annotation, "paquet annoté")
    if not expected_rows:
        raise ValueError("Le paquet attendu est vide.")
    if not completed_rows:
        raise ValueError("Le paquet annoté est vide.")
    if tuple(expected_rows[0]) != ANNOTATOR_COLUMNS:
        raise ValueError("Les colonnes du paquet attendu sont invalides.")
    if tuple(completed_rows[0]) != ANNOTATOR_COLUMNS:
        raise ValueError("Les colonnes du paquet annoté ont été modifiées.")

    expected_by_pair = {row["pair_id"]: row for row in expected_rows}
    completed_by_pair = {row["pair_id"]: row for row in completed_rows}
    if len(expected_by_pair) != len(expected_rows):
        raise ValueError("Le paquet attendu contient un pair_id dupliqué.")
    if len(completed_by_pair) != len(completed_rows):
        raise ValueError("Le paquet annoté contient un pair_id dupliqué.")
    if set(completed_by_pair) != set(expected_by_pair):
        raise ValueError("Les pair_id du paquet annoté ne sont pas exactement attendus.")

    for pair_id, completed_row in completed_by_pair.items():
        expected_row = expected_by_pair[pair_id]
        for column in PROTECTED_COLUMNS:
            if completed_row[column] != expected_row[column]:
                raise ValueError(
                    f"Colonne de contexte modifiée pour {pair_id} : {column}."
                )
        if completed_row["score"] not in {"0", "1", "2", "3"}:
            raise ValueError(f"Score invalide pour {pair_id}.")
        if completed_row["critere_principal"] not in VALID_MAIN_CRITERIA:
            raise ValueError(f"Critère principal invalide pour {pair_id}.")
        if not completed_row["justification"].strip():
            raise ValueError(f"Justification vide pour {pair_id}.")
        if completed_row["incertain"] not in VALID_UNCERTAINTY_VALUES:
            raise ValueError(f"Valeur incertain invalide pour {pair_id}.")
    return AnnotationValidationResult(
        row_count=len(completed_rows),
        pair_count=len(completed_by_pair),
    )

"""."""
from backend.scripts.free_work_triage_v2 import resolve_free_work_url
import argparse
import hashlib
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = BACKEND_ROOT / "data"
RAW_DATA_ROOT = DATA_ROOT / "raw"
PROCESSED_DATA_ROOT = DATA_ROOT / "processed"


def normaliser_texte(texte: str | None) -> str | None:
    """
    Applique la normalisation NFKC, convertit les entités HTML,
    remplace les suites d'espaces par un espace unique, supprime les espaces
    aux extrémités et retourne None si vide.
    """
    if texte is None:
        return None
    texte_str = str(texte)
    texte_norm = unicodedata.normalize("NFKC", texte_str)
    texte_unescaped = html.unescape(texte_norm)
    texte_cleaned = re.sub(r"\s+", " ", texte_unescaped).strip()
    return texte_cleaned if texte_cleaned else None


def normaliser_html(html_content: str | None) -> str | None:
    """
    Utilise BeautifulSoup pour retirer les balises HTML en préservant
    une séparation lisible entre les blocs, puis applique normaliser_texte.
    """
    if html_content is None:
        return None
    content_str = str(html_content)
    soup = BeautifulSoup(content_str, "html.parser")
    # Ajoute un espace après les balises de blocs et sauts de ligne pour éviter de coller les mots
    for tag in soup.find_all(["p", "div", "br", "li", "ul", "ol",
                             "h1", "h2", "h3", "h4", "h5", "h6"]):
        tag.insert_after(" ")
    text = soup.get_text()
    return normaliser_texte(text)


def normaliser_nom_competence(nom: str | None) -> str | None:
    """."""
    nom_clean = normaliser_texte(nom)
    if not nom_clean:
        return None
    decomposed = unicodedata.normalize("NFKD", nom_clean)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.lower()).strip() or None


def normaliser_competences(raw_skills) -> list[dict]:
    """."""
    if not isinstance(raw_skills, list):
        return []

    deduplicated = {}
    for item in raw_skills:
        if not isinstance(item, dict):
            continue
        source_skill_id = item.get("id")
        source_skill_id = str(source_skill_id).strip() if source_skill_id is not None and str(
            source_skill_id).strip() else None
        source_ref = normaliser_texte(item.get("@id"))
        name = normaliser_texte(item.get("name"))
        name_normalized = normaliser_nom_competence(name)
        slug = normaliser_texte(item.get("slug"))
        displayed = item.get("displayed") if isinstance(item.get("displayed"), bool) else None

        if not any([source_skill_id, source_ref, name,
                   name_normalized, slug, displayed is not None]):
            continue

        dedup_key = ("id", source_skill_id) if source_skill_id else (
            "name", name_normalized or slug or source_ref)
        if dedup_key[1] is None:
            continue

        if dedup_key not in deduplicated:
            deduplicated[dedup_key] = {
                "source_skill_id": source_skill_id,
                "source_ref": source_ref,
                "name": name,
                "name_normalized": name_normalized,
                "slug": slug,
                "displayed": displayed,
            }

    return sorted(
        deduplicated.values(),
        key=lambda skill: (
            skill.get("name_normalized") or "",
            skill.get("source_skill_id") or "",
            skill.get("slug") or "",
            skill.get("source_ref") or "",
        ),
    )


def calculer_sha256_fichier(filepath: Path) -> str:
    """."""
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ecriture_atomique(dest_path: Path, content_bytes: bytes) -> str:
    """
    Écrit de manière atomique le contenu dans dest_path après comparaison.
    """
    if dest_path.exists():
        if dest_path.read_bytes() == content_bytes:
            return "inchangé"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_name(dest_path.name + ".tmp")
    try:
        temp_path.write_bytes(content_bytes)
        temp_path.replace(dest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return "mis à jour"


def normaliser_offres(input_file: Path) -> Path:
    """."""
    if not input_file.exists():
        raise FileNotFoundError(f"Fichier d'entrée introuvable : {input_file}")

    with input_file.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalide dans {input_file} : {e}")

    if not isinstance(data, list):
        raise ValueError("La racine du fichier JSON d'entrée doit être une liste.")

    batch_id = input_file.parent.name
    if "full_catalog" in str(input_file.resolve()):
        output_dir = PROCESSED_DATA_ROOT / "free_work" / "full_catalog" / batch_id
    else:
        output_dir = PROCESSED_DATA_ROOT / "free_work" / "normalized" / batch_id

    seen_ids = set()
    normalized_offers = []

    # Statistiques du manifeste
    offers_with_missing_company = 0
    offers_with_missing_location = 0
    offers_with_missing_description = 0

    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"L'élément à l'index {idx} n'est pas un dictionnaire.")

        for k in ["source", "source_id", "matched_rome_queries", "offer"]:
            if k not in item:
                raise ValueError(f"Clé '{k}' manquante dans l'élément à l'index {idx}.")

        if item["source"] != "free_work":
            raise ValueError(f"Source invalide à l'index {idx} : {item['source']}.")

        source_id = item["source_id"]
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(f"source_id invalide ou vide à l'index {idx}.")

        source_id = source_id.strip()
        if source_id in seen_ids:
            raise ValueError(f"source_id dupliqué détecté : {source_id}")
        seen_ids.add(source_id)

        matched_rome_queries = item["matched_rome_queries"]
        if not isinstance(matched_rome_queries, list):
            raise ValueError(f"matched_rome_queries doit être une liste à l'index {idx}.")

        for q_idx, q in enumerate(matched_rome_queries):
            if not isinstance(q, dict):
                raise ValueError(
                    f"La requête ROME à l'index {q_idx} de l'offre {source_id} n'est pas un dictionnaire.")  # pylint: disable=line-too-long
            for field in ["rome_code", "rome_label", "query"]:
                if field not in q or not str(q[field]).strip():
                    raise ValueError(
                        f"Le champ ROME '{field}' est manquant ou vide pour l'offre {source_id}.")

        offer = item["offer"]
        if not isinstance(offer, dict):
            raise ValueError(f"Le champ 'offer' de l'offre {source_id} doit être un dictionnaire.")

        offer_id = offer.get("id") or offer.get("@id")
        if offer_id is None:
            raise ValueError(f"L'offre sous source_id {source_id} ne contient aucun identifiant.")
        if str(offer_id) != source_id:
            raise ValueError(
                f"Incohérence d'identifiant : source_id={source_id}, offer_id={offer_id}.")

        title = offer.get("title")
        if not title or not str(title).strip():
            raise ValueError(f"Titre manquant ou vide pour l'offre {source_id}.")

        # URL source : conserver uniquement un href public fiable.
        # Les @id /job_postings/... sont des identifiants API historiques, pas des
        # routes publiques garanties.
        source_url_resolution = resolve_free_work_url(offer)

        # Tri et déduplication des provenances ROME
        seen_queries = set()
        unique_queries = []
        for q in matched_rome_queries:
            rome_code = str(q["rome_code"]).strip()
            rome_label = str(q["rome_label"]).strip()
            query = str(q["query"]).strip()
            q_key = (rome_code, query, rome_label)
            if q_key not in seen_queries:
                seen_queries.add(q_key)
                unique_queries.append({
                    "rome_code": rome_code,
                    "rome_label": rome_label,
                    "query": query
                })
        unique_queries.sort(key=lambda x: (x["rome_code"], x["query"], x["rome_label"]))

        # Normalisation des textes
        desc = normaliser_html(offer.get("description"))
        if not desc:
            offers_with_missing_description += 1

        profile = normaliser_html(offer.get("candidateProfile"))
        comp_desc = normaliser_html(offer.get("companyDescription"))

        # Société
        company = offer.get("company")
        company_name = None
        if isinstance(company, dict):
            company_name = normaliser_texte(company.get("name"))
        if not company_name:
            offers_with_missing_company += 1

        # Localisation
        loc = offer.get("location")
        location_normalized = {
            "locality": None,
            "postal_code": None,
            "region": None,
            "country": None
        }
        if isinstance(loc, dict):
            location_normalized["locality"] = normaliser_texte(loc.get("locality"))
            location_normalized["postal_code"] = normaliser_texte(loc.get("postalCode"))
            location_normalized["region"] = normaliser_texte(loc.get("adminLevel1"))
            location_normalized["country"] = normaliser_texte(loc.get("country"))
        if not location_normalized["locality"]:
            offers_with_missing_location += 1

        # Contrats
        raw_contracts = offer.get("contracts")
        if raw_contracts is None:
            contracts = []
        elif not isinstance(raw_contracts, list):
            raise ValueError(f"Le champ 'contracts' de l'offre {source_id} doit être une liste.")
        else:
            contracts = sorted(list({str(c).strip() for c in raw_contracts if c}))

        skills = normaliser_competences(offer.get("skills"))
        soft_skills = normaliser_competences(offer.get("softSkills"))

        # Salaires
        salary = {
            "annual_min": offer.get("minAnnualSalary"),
            "annual_max": offer.get("maxAnnualSalary"),
            "daily_min": offer.get("minDailySalary"),
            "daily_max": offer.get("maxDailySalary"),
            "currency": normaliser_texte(offer.get("currency"))
        }

        # SHA-256 du payload brut canonique
        raw_payload_bytes = json.dumps(
            offer,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        raw_payload_sha256 = hashlib.sha256(raw_payload_bytes).hexdigest()

        normalized_offers.append({
            "source": "free_work",
            "source_id": source_id,
            "source_url": source_url_resolution.absolute_url,
            "source_url_raw": source_url_resolution.raw_url,
            "source_url_resolution_method": source_url_resolution.method,
            "matched_rome_queries": unique_queries,
            "title": normaliser_texte(title),
            "description": desc,
            "candidate_profile": profile,
            "company_description": comp_desc,
            "company_name": company_name,
            "location": location_normalized,
            "contracts": contracts,
            "skills": skills,
            "soft_skills": soft_skills,
            "remote_mode": normaliser_texte(offer.get("remoteMode")),
            "experience_level": normaliser_texte(offer.get("experienceLevel")),
            "salary": salary,
            "published_at": normaliser_texte(offer.get("publishedAt")),
            "updated_at": normaliser_texte(offer.get("updatedAt")),
            "expires_at": normaliser_texte(offer.get("expiredAt")),
            "raw_payload_sha256": raw_payload_sha256
        })

    # Tri déterministe final par source_id
    normalized_offers.sort(key=lambda x: x["source_id"])

    # Sérialisation stable
    output_bytes = json.dumps(
        normalized_offers,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8") + b"\n"

    input_sha256 = calculer_sha256_fichier(input_file)
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()

    # Écriture atomique
    offers_file_path = output_dir / "offers_normalized.json"
    status_offers = ecriture_atomique(offers_file_path, output_bytes)

    try:
        input_file_rel = str(input_file.relative_to(BACKEND_ROOT)).replace("\\", "/")
    except ValueError:
        input_file_rel = str(input_file).replace("\\", "/")

    # Manifeste
    manifest = {
        "normalization_schema_version": 1,
        "source": "free_work",
        "source_batch_id": batch_id,
        "input_file": input_file_rel,
        "input_sha256": input_sha256,
        "input_offers": len(data),
        "output_offers": len(normalized_offers),
        "output_file": "offers_normalized.json",
        "output_sha256": output_sha256,
        "offers_with_missing_company": offers_with_missing_company,
        "offers_with_missing_location": offers_with_missing_location,
        "offers_with_missing_description": offers_with_missing_description
    }

    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2
    ).encode("utf-8") + b"\n"

    manifest_file_path = output_dir / "normalization_manifest.json"
    status_manifest = ecriture_atomique(manifest_file_path, manifest_bytes)

    # Affichage du statut d'écriture
    if status_offers == "inchangé" and status_manifest == "inchangé":
        print("inchangé")
    else:
        print("mis à jour")

    return output_dir


def lire_arguments() -> argparse.Namespace:
    """."""
    parser = argparse.ArgumentParser(
        description="Normalise les offres d'emploi Free-Work dédupliquées."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Chemin vers le fichier d'entrée offers_deduplicated.json."
    )
    return parser.parse_args()


def main() -> None:
    """."""
    args = lire_arguments()
    input_file = Path(args.input)
    try:
        normaliser_offres(input_file)
    except FileNotFoundError as e:
        print(f"Erreur de fichier : {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Erreur de validation : {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erreur inattendue : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

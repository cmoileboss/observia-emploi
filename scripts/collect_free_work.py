import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "ObservIA-Emploi/1.0 (projet pédagogique)"
ROBOTS_URL = "https://www.free-work.com/robots.txt"
API_URL = "https://www.free-work.com/api/job_postings"
TIMEOUT_SECONDS = 20


def valider_query(query: str) -> str:
    """Valide et nettoie la requête de recherche."""
    query_cleaned = query.strip()
    if not query_cleaned:
        raise ValueError("La requête (--query) ne doit pas être vide.")
    return query_cleaned


def charger_robots_txt(user_agent: str) -> str:
    """Télécharge le fichier robots.txt de Free-Work."""
    headers = {"User-Agent": user_agent}
    response = requests.get(ROBOTS_URL, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def construire_url_api(query: str, page: int, items_per_page: int) -> str:
    """Construit l'URL de recherche avec les paramètres de requête pour l'API."""
    req = requests.Request(
        "GET",
        API_URL,
        params={
            "page": page,
            "itemsPerPage": items_per_page,
            "locationKeys": "fr~~~",
            "searchKeywords": query
        }
    )
    prepared = req.prepare()
    if not prepared.url:
        raise RuntimeError("Impossible de construire l'URL de recherche.")
    return prepared.url


def verifier_autorisation_robots(robots_txt_content: str, url: str, user_agent: str) -> bool:
    """Vérifie l'autorisation d'accès à l'URL via urllib.robotparser."""
    rp = RobotFileParser()
    rp.parse(robots_txt_content.splitlines())
    return rp.can_fetch(user_agent, url)


def telecharger_reponse(url: str, params: dict | None, user_agent: str) -> requests.Response:
    """Effectue la requête GET vers l'API Free-Work."""
    headers = {"User-Agent": user_agent}
    response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response


def sauvegarder_reponse_brute(directory: Path, filename: str, content: bytes) -> None:
    """Sauvegarde le contenu brut de la réponse dans le fichier spécifié."""
    filepath = directory / filename
    filepath.write_bytes(content)


def decoder_json(content: bytes) -> dict:
    """Décode le contenu JSON et vérifie qu'il s'agit d'un dictionnaire."""
    try:
        data = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise requests.exceptions.JSONDecodeError(
            f"Erreur de décodage JSON : {e}", doc=content.decode("utf-8", errors="replace"), pos=0
        )

    if not isinstance(data, dict):
        raise ValueError("Structure JSON invalide : la racine doit être un dictionnaire.")
    return data


def extraire_total_annonce(data: dict) -> int:
    """Extrait la valeur de hydra:totalItems et valide sa structure."""
    if "hydra:totalItems" not in data:
        raise ValueError("Structure JSON invalide : la clé 'hydra:totalItems' est absente.")

    total = data["hydra:totalItems"]
    # hydra:totalItems doit être un entier positif ou nul
    if not isinstance(total, int) or total < 0:
        raise ValueError(f"Structure JSON invalide : 'hydra:totalItems' doit être un entier positif ou nul (reçu : {total}).")
    return total


def extraire_offres(data: dict) -> list:
    """Extrait et valide la liste des offres dans hydra:member."""
    if "hydra:member" not in data:
        raise ValueError("Structure JSON invalide : la clé 'hydra:member' est absente.")

    offres = data["hydra:member"]
    if not isinstance(offres, list):
        raise ValueError("Structure JSON invalide : 'hydra:member' doit être une liste.")

    for idx, offre in enumerate(offres):
        if not isinstance(offre, dict):
            raise ValueError(f"Structure JSON invalide : l'offre à l'index {idx} de 'hydra:member' doit être un dictionnaire.")
    return offres


def valider_url_pagination(url: str) -> bool:
    """Vérifie que l'URL finale est sûre, utilise HTTPS, cible www.free-work.com et le chemin de l'API."""
    parsed = urlparse(url)
    return (
        parsed.scheme == "https" and
        parsed.netloc == "www.free-work.com" and
        parsed.path == "/api/job_postings"
    )


def extraire_url_suivante(data: dict) -> str | None:
    """Extrait l'URL de la page suivante depuis hydra:view -> hydra:next."""
    view = data.get("hydra:view")
    if view is None:
        return None
    if not isinstance(view, dict):
        raise ValueError("Structure JSON invalide : 'hydra:view' doit être un dictionnaire.")

    next_url = view.get("hydra:next")
    if next_url is None:
        return None

    if not isinstance(next_url, str) or not next_url.strip():
        raise ValueError("Structure JSON invalide : 'hydra:next' doit être une chaîne non vide.")

    next_url = next_url.strip()
    # Gestion de l'incohérence de préfixe de Free-Work
    if next_url.startswith("/job_postings"):
        next_url = "/api" + next_url
    elif next_url.startswith("job_postings"):
        next_url = "/api/" + next_url

    return next_url


def ajouter_offres_uniques(offres: list, uniques: list, ids_vus: set) -> int:
    """Filtre et ajoute les offres uniques de la page courante à la liste globale."""
    nouvelles_offres_page = 0
    for offre in offres:
        identifiant = offre.get("id") or offre.get("@id")
        if identifiant is None:
            raise ValueError("Structure JSON invalide : l'offre ne possède ni 'id' ni '@id'.")

        if identifiant not in ids_vus:
            ids_vus.add(identifiant)
            uniques.append(offre)
            nouvelles_offres_page += 1

    return nouvelles_offres_page


def creer_dossier_execution() -> Path:
    """Crée le dossier UTC horodaté pour stocker les résultats bruts."""
    utc_now = datetime.now(timezone.utc)
    folder_name = utc_now.strftime("%Y%m%d_%H%M%S")
    directory = Path("data") / "raw" / "free_work" / folder_name
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def sauvegarder_offres_agregees(directory: Path, uniques: list) -> None:
    """Sauvegarde le fichier agregé unique des offres."""
    filepath = directory / "offers_merged_raw.json"
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(uniques, f, ensure_ascii=False, indent=2)


def sauvegarder_metadonnees(
    directory: Path,
    query: str,
    total_annonce: int,
    uniques_len: int,
    page_files: list,
    pages_downloaded: int,
    stop_reason: str
) -> None:
    """Sauvegarde le fichier metadata.json final."""
    metadata = {
        "source": "free_work",
        "query": query,
        "api_url": API_URL,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_items_annonce_premiere_page": total_annonce,
        "offres_uniques_collectees": uniques_len,
        "difference_total": uniques_len - total_annonce,
        "page_files": page_files,
        "offers_merged_file": "offers_merged_raw.json",
        "pages_downloaded": pages_downloaded,
        "pagination_stop_reason": stop_reason
    }

    filepath = directory / "metadata.json"
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def collecter_offres(query: str) -> Path:
    """Orchestre la collecte des offres Free-Work via son endpoint interne."""
    query_cleaned = valider_query(query)

    print(f"Initialisation de la collecte Free-Work : {query_cleaned}")

    # 1. Chargement et vérification des robots.txt
    robots_txt = charger_robots_txt(USER_AGENT)
    if not verifier_autorisation_robots(robots_txt, API_URL, USER_AGENT):
        raise PermissionError(f"L'accès à l'URL {API_URL} est interdit par le fichier robots.txt.")
    print("Contrôle robots.txt : autorisé")

    # 2. Création du dossier d'exécution
    directory = creer_dossier_execution()

    # 3. Sauvegarde du fichier robots.txt
    robots_file = directory / "robots.txt"
    robots_file.write_text(robots_txt, encoding="utf-8")

    uniques = []
    ids_vus = set()
    page_files = []
    pages_downloaded = 0
    stop_reason = "no_results"
    total_annonce = 0

    current_url = API_URL
    params = {
        "page": 1,
        "itemsPerPage": 100,
        "locationKeys": "fr~~~",
        "searchKeywords": query_cleaned
    }
    urls_visitees = set()

    while current_url:
        # Enregistrement pour détecter les boucles infinies de pagination
        url_key = current_url
        if pages_downloaded == 0 and params:
            req = requests.Request("GET", current_url, params=params)
            url_key = req.prepare().url or current_url

        # Validation stricte de l'URL de pagination
        if not valider_url_pagination(url_key):
            raise ValueError(f"Sécurité : URL de pagination invalide ou non sécurisée : {url_key}")

        if url_key in urls_visitees:
            stop_reason = "repeated_page_url"
            print(f"Pagination interrompue : l'URL {url_key} a déjà été visitée.")
            break
        urls_visitees.add(url_key)

        pages_downloaded += 1
        filename = f"page_{pages_downloaded:03d}.json"
        print(f"Téléchargement de la page {pages_downloaded}...")

        # Pour la première page, on passe les paramètres, pour les pages suivantes l'url absolue les contient déjà
        response = telecharger_reponse(current_url, params if pages_downloaded == 1 else None, USER_AGENT)
        sauvegarder_reponse_brute(directory, filename, response.content)
        page_files.append(filename)

        data = decoder_json(response.content)

        # Récupération du total à la première page
        if pages_downloaded == 1:
            total_annonce = extraire_total_annonce(data)
            print(f"Total annoncé par la première page : {total_annonce}")
            if total_annonce == 0:
                stop_reason = "no_results"
                break

        offres = extraire_offres(data)

        if not offres:
            stop_reason = "empty_page"
            print(f"Pagination terminée : la page {pages_downloaded} ne contient aucune offre.")
            break

        nouvelles = ajouter_offres_uniques(offres, uniques, ids_vus)
        print(f"Page {pages_downloaded} : {len(offres)} offre(s) reçue(s), {nouvelles} nouvelle(s)")

        if nouvelles == 0:
            stop_reason = "no_new_offer"
            print(f"Pagination terminée : aucun nouvel identifiant unique détecté à la page {pages_downloaded}.")
            break

        # Extraction de la page suivante
        next_url = extraire_url_suivante(data)
        if next_url:
            current_url = urljoin(API_URL, next_url)
        else:
            current_url = None
            stop_reason = "no_next_page"

    if stop_reason == "no_next_page":
        print("Pagination terminée : aucune page suivante")

    # 6. Gestion de l'incohérence du total
    difference_total = len(uniques) - total_annonce
    if difference_total != 0:
        print(f"Avertissement : la première page annonçait {total_annonce} résultat(s), mais {len(uniques)} offre(s) unique(s) ont été collectées.")

    print(f"{len(uniques)} offre(s) unique(s) collectée(s)")

    # 7. Sauvegardes finales
    sauvegarder_offres_agregees(directory, uniques)
    sauvegarder_metadonnees(
        directory=directory,
        query=query_cleaned,
        total_annonce=total_annonce,
        uniques_len=len(uniques),
        page_files=page_files,
        pages_downloaded=pages_downloaded,
        stop_reason=stop_reason
    )

    print(f"Collecte sauvegardée dans : {directory}")
    return directory


def lire_arguments() -> argparse.Namespace:
    """Lit les arguments passés en ligne de commande."""
    parser = argparse.ArgumentParser(description="Collecte les offres de Free-Work via l'API interne.")
    parser.add_argument(
        "--query",
        required=True,
        help="Terme de recherche d'offres d'emploi."
    )
    return parser.parse_args()


def main() -> None:
    args = lire_arguments()
    try:
        collecter_offres(args.query)
    except (ValueError, PermissionError, requests.RequestException, OSError, RuntimeError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

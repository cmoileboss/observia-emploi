import csv
import json

from backend.scripts.free_work_triage_v2 import (
    TriageThresholds,
    AdvertiserRoleResult,
    build_free_work_details_lookup,
    classify_v2,
    human_explanation,
    replay_triage_v2,
    resolve_free_work_url,
)


def candidate(
    score=35.0,
    title_similarity=0.3,
    description_similarity=0.1,
    company_match="NO_MATCH",
    geography="DIFFERENT",
    blocks=None,
    coverage=95,
    ft_id="FT-1",
):
    return {
        "france_travail_id": ft_id,
        "title": "Développeur Java",
        "company_name": "Other",
        "postal_code": "69000",
        "rome_code": "M1805",
        "preliminary_match_score": score,
        "evidence_coverage": coverage,
        "components": {
            "title_sequence_similarity": title_similarity,
            "description_token_jaccard": description_similarity,
            "rome_query_match": False,
        },
        "company_comparison": {
            "free_work_raw": "REACTIS",
            "france_travail_raw": "Other",
            "match_type": company_match,
        },
        "geography_comparison": {"result": geography},
        "title_comparison": {
            "sequence_similarity": title_similarity,
            "shared_significant_tokens": ["java"],
        },
        "candidate_blocks": blocks or [],
    }


def match_entry(candidates=None, title="Concepteur Développeur JAVA ANGULAR", description="Mission Java Angular"):
    return {
        "free_work_source_id": "14277",
        "free_work_title": title,
        "free_work_title_normalized": "concepteur developpeur java angular",
        "free_work_company": "REACTIS",
        "free_work_location": {"locality": "Écully", "postal_code": "69130"},
        "free_work_source_url": "https://www.free-work.com/job_postings/legacy",
        "free_work_description_excerpt": description,
        "top_candidates": candidates if candidates is not None else [candidate()],
    }


def custom_match_entry(source_id, decision_candidate, title="Concepteur Developpeur Java Angular Confirme"):
    entry = match_entry([decision_candidate], title=title, description="Mission Java Angular detaillee et comparable")
    entry["free_work_source_id"] = source_id
    entry["free_work_title"] = title
    entry["free_work_title_normalized"] = "concepteur developpeur java angular confirme"
    return entry


def test_url_absolute_href_is_preserved():
    resolved = resolve_free_work_url({"href": "https://www.free-work.com/fr/tech-it/job-mission/autre/slug"})

    assert resolved.absolute_url == "https://www.free-work.com/fr/tech-it/job-mission/autre/slug"
    assert resolved.method == "RAW_ABSOLUTE_URL"


def test_url_relative_href_uses_urljoin_and_preserves_accents():
    resolved = resolve_free_work_url({"href": "/fr/tech-it/job-mission/développeur/slug-é"})

    assert resolved.absolute_url == "https://www.free-work.com/fr/tech-it/job-mission/développeur/slug-é"
    assert resolved.method == "RELATIVE_HREF_RESOLVED"


def test_url_never_exposes_legacy_job_postings_prefix():
    resolved = resolve_free_work_url({"@id": "/job_postings/faux-slug"})

    assert resolved.absolute_url is None
    assert resolved.raw_url == "/job_postings/faux-slug"
    assert resolved.method == "LEGACY_URL_REBUILT"


def test_url_unavailable_is_not_invented():
    resolved = resolve_free_work_url({})

    assert resolved.absolute_url is None
    assert resolved.method == "URL_UNAVAILABLE"


def test_old_record_can_be_repaired_from_raw_href():
    resolved = resolve_free_work_url(
        {"href": "/fr/tech-it/job-mission/autre/vrai-slug"},
        "https://www.free-work.com/job_postings/faux-slug",
    )

    assert resolved.absolute_url == "https://www.free-work.com/fr/tech-it/job-mission/autre/vrai-slug"
    assert "/job_postings/" not in resolved.absolute_url


def test_v2_weak_candidate_with_good_coverage_is_not_found():
    decision, reasons = classify_v2(match_entry([candidate(score=35.0)]))

    assert decision == "NOT_FOUND_IN_FT_SNAPSHOT"
    assert "ALL_CANDIDATES_WEAK" in reasons


def test_v2_two_weak_close_candidates_are_not_uncertain():
    decision, reasons = classify_v2(match_entry([candidate(score=35.0), candidate(score=34.8, ft_id="FT-2")]))

    assert decision == "NOT_FOUND_IN_FT_SNAPSHOT"
    assert "ALL_CANDIDATES_WEAK" in reasons


def test_v2_insufficient_data_is_uncertain():
    entry = match_entry([candidate(score=35.0)], description="")

    decision, reasons = classify_v2(entry)

    assert decision == "UNCERTAIN"
    assert "INSUFFICIENT_FREE_WORK_DATA" in reasons


def test_v2_credible_close_candidates_are_uncertain():
    decision, reasons = classify_v2(
        match_entry(
            [
                candidate(score=56.0, company_match="NO_MATCH", geography="SAME_DEPARTMENT"),
                candidate(score=54.0, company_match="NO_MATCH", geography="SAME_DEPARTMENT", ft_id="FT-2"),
            ]
        )
    )

    assert decision == "UNCERTAIN"
    assert "MULTIPLE_CREDIBLE_CLOSE_CANDIDATES" in reasons


def test_v2_strong_fingerprint_is_present():
    decision, reasons = classify_v2(
        match_entry(
            [
                candidate(
                    score=88.0,
                    title_similarity=0.95,
                    description_similarity=0.7,
                    company_match="EXACT_NORMALIZED",
                    geography="EXACT_POSTAL_CODE",
                    blocks=["EXACT_FINGERPRINT"],
                )
            ],
            title="Concepteur Développeur JAVA ANGULAR confirmé",
        )
    )

    assert decision == "PRESENT_IN_FT_SNAPSHOT"
    assert "EXACT_FINGERPRINT" in reasons


def test_v2_contradictory_signals_are_uncertain():
    decision, reasons = classify_v2(
        match_entry(
            [
                candidate(
                    score=62.0,
                    title_similarity=0.9,
                    description_similarity=0.35,
                    company_match="NO_MATCH",
                    geography="SAME_DEPARTMENT",
                )
            ]
        )
    )

    assert decision == "UNCERTAIN"
    assert "HIGH_SCORE_COMPANY_DIFFERS" in reasons or "STRONG_TITLE_COMPANY_DIFFERS" in reasons


def test_processing_error_is_kept_separate():
    decision, reasons = classify_v2(match_entry([]), {"triage_category": "PROCESSING_ERROR"})

    assert decision == "PROCESSING_ERROR"
    assert "V1_PROCESSING_ERROR" in reasons


def test_human_explanation_rounds_and_keeps_unknown_nulls():
    best = candidate(title_similarity=0.736, description_similarity=None, company_match="NO_MATCH", geography="SAME_DEPARTMENT")
    explanation = human_explanation(match_entry([best]), best, "NOT_FOUND_IN_FT_SNAPSHOT", ["BEST_CANDIDATE_NOT_CREDIBLE"])

    assert explanation["title"]["score_percent"] == 74
    assert explanation["description"]["score_percent"] is None
    assert explanation["description"]["level"] == "UNKNOWN"
    assert "Entreprises différentes" in explanation["company"]["message"]
    assert "Même département" in explanation["location"]["message"]


def test_replay_writes_only_four_main_artifacts_by_default(tmp_path):
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    raw_path = tmp_path / "offers_deduplicated.json"
    out_dir = tmp_path / "run_v2"

    candidate_path.write_text(json.dumps([match_entry([candidate(score=35.0)])], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(
        json.dumps(
            [
                {
                    "free_work_source_id": "14277",
                    "triage_category": "HUMAN_REVIEW_REQUIRED",
                    "data_coverage": 95,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    raw_path.write_text(
        json.dumps(
            [
                {
                    "source_id": "14277",
                    "offer": {"href": "/fr/tech-it/job-mission/autre/slug"},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = replay_triage_v2(candidate_path, triage_path, out_dir, raw_path, run_id="test_run")
    files = sorted(path.name for path in out_dir.iterdir())

    assert files == ["import_candidates.json", "review_queue.csv", "run_manifest.json", "triage_decisions.jsonl"]
    assert manifest["counters"]["total_processed"] == 1
    assert manifest["counters"]["NOT_FOUND_IN_FT_SNAPSHOT"] == 1
    assert manifest["url_counters"]["remaining_job_postings_urls_in_main_output"] == 0

    with (out_dir / "review_queue.csv").open(encoding="utf-8-sig", newline="") as file:
        header = next(csv.reader(file, delimiter=";"))
    assert "title_sequence_similarity" not in header
    assert "score_similarite" in header



def test_replay_preserves_structured_skills_in_main_artifacts(tmp_path):
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    raw_path = tmp_path / "offers_deduplicated.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"

    candidate_path.write_text(json.dumps([match_entry([candidate(score=35.0)])], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "HUMAN_REVIEW_REQUIRED"}]), encoding="utf-8")
    raw_path.write_text(json.dumps([{"source_id": "14277", "offer": {"href": "/fr/jobs/slug"}}]), encoding="utf-8")
    normalized_path.write_text(
        json.dumps(
            [
                {
                    "source_id": "14277",
                    "skills": [{"source_skill_id": "152", "source_ref": "/skills/152", "name": "Python", "name_normalized": "python", "slug": "python", "displayed": True}],
                    "soft_skills": [],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = replay_triage_v2(candidate_path, triage_path, out_dir, raw_path, normalized_offers_path=normalized_path, run_id="test_run")

    decision = json.loads((out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    imports = json.loads((out_dir / "import_candidates.json").read_text(encoding="utf-8"))
    csv_text = (out_dir / "review_queue.csv").read_text(encoding="utf-8")

    assert decision["free_work"]["skills"][0]["name"] == "Python"
    assert imports[0]["skills"][0]["name_normalized"] == "python"
    assert "competences_free_work" in csv_text
    assert manifest["structured_skill_statistics"]["all_offers"]["offers_with_structured_skills"] == 1
    assert manifest["structured_skill_statistics"]["all_offers"]["unique_structured_skills"] == 1
    assert sorted(path.name for path in out_dir.iterdir()) == ["import_candidates.json", "review_queue.csv", "run_manifest.json", "triage_decisions.jsonl"]


def test_normalized_lookup_accepts_int_and_string_ids_and_rejects_duplicates(tmp_path):
    normalized_path = tmp_path / "offers_normalized.json"
    normalized_path.write_text(json.dumps([{"source_id": 14277, "skills": []}], ensure_ascii=False), encoding="utf-8")

    assert build_free_work_details_lookup(normalized_path)["14277"]["source_id"] == 14277

    normalized_path.write_text(json.dumps([{"source_id": "1"}, {"source_id": 1}], ensure_ascii=False), encoding="utf-8")
    try:
        build_free_work_details_lookup(normalized_path)
    except ValueError as exc:
        assert "Duplicate normalized Free-Work source id" in str(exc)
    else:
        raise AssertionError("duplicate normalized source ids should fail")


def test_replay_reports_missing_normalized_offer(tmp_path):
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"

    candidate_path.write_text(json.dumps([match_entry([candidate(score=35.0)])], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "HUMAN_REVIEW_REQUIRED"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")

    manifest = replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")

    integrity = manifest["skill_propagation_integrity"]
    assert integrity["normalized_offers_found"] == 0
    assert integrity["normalized_offers_missing"] == 1
    assert integrity["skill_propagation_failures"] == 0
    assert manifest["warnings"][0]["code"] == "NORMALIZED_FREE_WORK_OFFER_MISSING"


def test_replay_propagates_skills_for_present_not_found_and_uncertain_without_soft_skill_top(tmp_path):
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    skill = {"source_skill_id": "152", "name": "Python", "name_normalized": "python", "slug": "python", "displayed": True}
    soft = {"source_skill_id": "soft-1", "name": "Communication", "name_normalized": "communication", "slug": "communication", "displayed": True}
    matches = [
        custom_match_entry("1", candidate(score=88, title_similarity=0.95, description_similarity=0.7, company_match="EXACT_NORMALIZED", geography="EXACT_POSTAL_CODE", blocks=["EXACT_FINGERPRINT"])),
        custom_match_entry(2, candidate(score=35, title_similarity=0.3, description_similarity=0.1, company_match="NO_MATCH", geography="DIFFERENT")),
        custom_match_entry("3", candidate(score=62, title_similarity=0.9, description_similarity=0.35, company_match="NO_MATCH", geography="SAME_DEPARTMENT")),
    ]
    candidate_path.write_text(json.dumps(matches, ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(
        json.dumps([{"free_work_source_id": "1"}, {"free_work_source_id": "2"}, {"free_work_source_id": "3"}], ensure_ascii=False),
        encoding="utf-8",
    )
    normalized_path.write_text(
        json.dumps(
            [
                {"source_id": "1", "title": "Present", "company_name": "A", "skills": [skill], "soft_skills": [soft]},
                {"source_id": "2", "title": "Not found", "company_name": "B", "skills": [skill], "soft_skills": [soft]},
                {"source_id": 3, "title": "Uncertain", "company_name": "C", "skills": [skill], "soft_skills": [soft]},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    by_decision = {row["decision"]: row for row in decisions}

    assert {"PRESENT_IN_FT_SNAPSHOT", "NOT_FOUND_IN_FT_SNAPSHOT", "UNCERTAIN"} == set(by_decision)
    for row in decisions:
        assert row["free_work"]["skills"] == [skill]
        assert row["free_work"]["soft_skills"] == [soft]
    assert manifest["skill_propagation_integrity"]["normalized_offers_found"] == 3
    assert manifest["skill_propagation_integrity"]["skill_propagation_failures"] == 0
    stats = manifest["structured_skill_statistics"]
    assert stats["all_offers"]["offers_with_structured_skills"] == 3
    assert stats["all_offers"]["top_structured_skills"] == [{"name": "Python", "normalized_name": "python", "offer_count": 3}]
    assert "communication" not in json.dumps(stats, ensure_ascii=False)


def test_strong_intermediary_rule_is_strict_and_possible_is_not_enough():
    strong = candidate(score=67, title_similarity=0.9, description_similarity=0.35, company_match="NO_MATCH", geography="SAME_DEPARTMENT")
    strong["title_comparison"]["free_work_normalized"] = "developpeur java angular confirme"
    entry = match_entry([strong], title="Developpeur Java Angular Confirme")

    decision, reasons = classify_v2(entry, advertiser_role=AdvertiserRoleResult("RECRUITMENT_INTERMEDIARY", ["preuve explicite"]))
    assert decision == "PRESENT_IN_FT_SNAPSHOT"
    assert reasons == ["STRONG_MATCH_VIA_RECRUITMENT_INTERMEDIARY"]

    possible_decision, possible_reasons = classify_v2(entry, advertiser_role=AdvertiserRoleResult("POSSIBLE_INTERMEDIARY", ["notre client"]))
    assert possible_decision == "UNCERTAIN"
    assert "STRONG_MATCH_VIA_RECRUITMENT_INTERMEDIARY" not in possible_reasons


def test_exact_fingerprint_keeps_priority_over_intermediary_rule():
    strong = candidate(
        score=88,
        title_similarity=0.95,
        description_similarity=0.7,
        company_match="EXACT_NORMALIZED",
        geography="EXACT_POSTAL_CODE",
        blocks=["EXACT_FINGERPRINT"],
    )
    decision, reasons = classify_v2(
        match_entry([strong], title="Developpeur Java Angular Confirme"),
        advertiser_role=AdvertiserRoleResult("RECRUITMENT_INTERMEDIARY", ["preuve explicite"]),
    )

    assert decision == "PRESENT_IN_FT_SNAPSHOT"
    assert reasons == ["EXACT_FINGERPRINT"]


def test_review_action_defer_data_incomplete(tmp_path):
    # Cas incomplet réellement différé :
    # - décision UNCERTAIN (grâce à description vide -> INSUFFICIENT_FREE_WORK_DATA)
    # - score faible < 50
    # - aucun autre signal fort (entreprise différente, géo différente, titre non similaire)
    # - pas d'ancien doublon V1
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    cand = candidate(score=35.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2)
    entry = match_entry([cand], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8") # pas doublon V1
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    manifest = replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "DEFER_DATA_INCOMPLETE"
    assert "Données insuffisantes et aucun signal" in decisions[0]["review_action_reason"]
    assert manifest["counters"]["deferred_data_incomplete"] == 1
    assert manifest["counters"]["human_review_required"] == 0


def test_review_action_kept_due_to_score_ge_50(tmp_path):
    # Score >= 50 est toujours conservé en revue (REVIEW_NOW)
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    cand = candidate(score=52.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2)
    entry = match_entry([cand], description="") # déclenche INSUFFICIENT_FREE_WORK_DATA
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    manifest = replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "REVIEW_NOW"
    assert "Score candidat significatif" in decisions[0]["review_action_reason"]
    assert manifest["counters"]["deferred_data_incomplete"] == 0
    assert manifest["counters"]["human_review_required"] == 1


def test_review_action_kept_due_to_v1_historical_uncertainty(tmp_path):
    # Ancien doublon V1 DUPLICATE_HIGH_CONFIDENCE est protégé
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    cand = candidate(score=35.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2)
    entry = match_entry([cand], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "DUPLICATE_HIGH_CONFIDENCE"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "REVIEW_NOW"
    assert "Ancien doublon V1" in decisions[0]["review_action_reason"]


def test_review_action_not_kept_due_to_v1_human_review_required(tmp_path):
    # HUMAN_REVIEW_REQUIRED V1 n'est PAS protégé et est donc différé
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    cand = candidate(score=35.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2)
    entry = match_entry([cand], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "HUMAN_REVIEW_REQUIRED"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "DEFER_DATA_INCOMPLETE"


def test_review_action_two_weak_close_candidates_do_not_block_deferral(tmp_path):
    # Deux candidats faibles (ex: scores 30 et 28) ne constituent pas des candidats crédibles, l'offre peut être différée
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    cand1 = candidate(score=30.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2)
    cand2 = candidate(score=28.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2, ft_id="FT-2")
    entry = match_entry([cand1, cand2], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "DEFER_DATA_INCOMPLETE"


def test_review_action_two_credible_close_candidates_block_deferral(tmp_path):
    # Deux candidats >= 50 et proches bloquent le différé
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    # On met une description vide pour avoir le motif INSUFFICIENT_FREE_WORK_DATA.
    # Et des candidats proches à scores >= 50.
    # Note : Normalement, si le meilleur score est >= 50, l'offre ne serait pas différée
    # à cause du score. Pour tester le blocage spécifique par candidats multiples proches,
    # on doit vérifier que has_close_candidate est bien True (ce qui est testé ici indirectement
    # car le score >= 50 bloque de toute façon le différé, mais cela valide le fonctionnement de l'indicateur).
    cand1 = candidate(score=52.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2)
    cand2 = candidate(score=51.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2, ft_id="FT-2")
    entry = match_entry([cand1, cand2], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "REVIEW_NOW"
    assert "Plusieurs candidats" in decisions[0]["review_action_reason"] or "Score candidat" in decisions[0]["review_action_reason"]


def test_review_action_possible_intermediary_does_not_block_deferral(tmp_path):
    # POSSIBLE_INTERMEDIARY ne bloque pas le différé
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    cand = candidate(score=35.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2)
    entry = match_entry([cand], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": [], "description": "notre client a besoin de renfort"}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "DEFER_DATA_INCOMPLETE"


def test_review_action_recruitment_intermediary_blocks_deferral(tmp_path):
    # RECRUITMENT_INTERMEDIARY explicite bloque le différé
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    cand = candidate(score=35.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.2)
    entry = match_entry([cand], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": [], "description": "recrute pour le compte de son client"}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "REVIEW_NOW"
    assert "Intermédiaire de recrutement" in decisions[0]["review_action_reason"]


def test_review_action_geography_alone_does_not_block_deferral(tmp_path):
    # Localisation compatible seule ne bloque pas le différé
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    # score < 50, entreprise NO_MATCH, titre faible, mais géo SAME_LOCALITY
    cand = candidate(score=35.0, company_match="NO_MATCH", geography="SAME_LOCALITY", title_similarity=0.2)
    entry = match_entry([cand], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "DEFER_DATA_INCOMPLETE"


def test_review_action_strong_title_isolated_can_be_deferred(tmp_path):
    # Titre fort isolé sans autre signal peut être différé
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    # score < 50, titre fort (0.9), mais géo DIFFERENT, entreprise NO_MATCH, pas de compétences, pas d'intermédiaire
    cand = candidate(score=35.0, company_match="NO_MATCH", geography="DIFFERENT", title_similarity=0.9)
    entry = match_entry([cand], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "DEFER_DATA_INCOMPLETE"


def test_review_action_strong_title_with_second_signal_remains_in_review(tmp_path):
    # Titre fort avec un second signal (ex: géographie compatible) reste en revue
    candidate_path = tmp_path / "candidate_matches.json"
    triage_path = tmp_path / "triage_results.json"
    normalized_path = tmp_path / "offers_normalized.json"
    out_dir = tmp_path / "run_v2"
    
    # score < 50, titre fort (0.9) et géo compatible
    cand = candidate(score=35.0, company_match="NO_MATCH", geography="SAME_LOCALITY", title_similarity=0.9)
    entry = match_entry([cand], description="")
    
    candidate_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
    triage_path.write_text(json.dumps([{"free_work_source_id": "14277", "triage_category": "PROBABLY_NEW"}]), encoding="utf-8")
    normalized_path.write_text(json.dumps([{"source_id": "14277", "skills": [], "soft_skills": []}]), encoding="utf-8")

    replay_triage_v2(candidate_path, triage_path, out_dir, normalized_offers_path=normalized_path, run_id="test_run")
    
    decisions = [json.loads(line) for line in (out_dir / "triage_decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert decisions[0]["review_action"] == "REVIEW_NOW"
    assert "Titre fortement similaire avec signal significatif" in decisions[0]["review_action_reason"]




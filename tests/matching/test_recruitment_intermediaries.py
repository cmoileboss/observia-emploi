from scripts.free_work_triage_v2 import (
    compare_companies_with_advertiser_role,
    detect_advertiser_role,
    strong_match_via_intermediary,
)


def role(text):
    return detect_advertiser_role(text)


def candidate(score=67.0, title=0.9, desc=0.35, geo="SAME_DEPARTMENT"):
    return {
        "preliminary_match_score": score,
        "components": {"description_token_jaccard": desc},
        "title_comparison": {"sequence_similarity": title, "free_work_normalized": "developpeur java angular confirme"},
        "geography_comparison": {"result": geo},
    }


def test_same_company_comparison():
    result = compare_companies_with_advertiser_role("ACME", "ACME", "EXACT_NORMALIZED", role("Nous recrutons."))

    assert result.result == "SAME_COMPANY"


def test_known_alias_comparison():
    result = compare_companies_with_advertiser_role("ACME SAS", "ACME", "ALIAS_MATCH", role("Nous recrutons."))

    assert result.result == "KNOWN_ALIAS"


def test_different_companies_without_evidence():
    result = compare_companies_with_advertiser_role("Client final", "Cabinet X", "NO_MATCH", role("Nous recrutons un développeur."))

    assert result.result == "DIFFERENT_COMPANIES"
    assert result.advertiser_role == "DIRECT_EMPLOYER"


def test_explicit_intermediary_explains_different_companies():
    result = compare_companies_with_advertiser_role(
        "Client final",
        "Cabinet X",
        "NO_MATCH",
        role("Nous recrutons pour le compte de notre client un développeur."),
    )

    assert result.result == "DIFFERENT_BUT_INTERMEDIARY_EXPLAINED"
    assert result.advertiser_role == "RECRUITMENT_INTERMEDIARY"
    assert "pour le compte de notre client" in result.advertiser_role_evidence[0]


def test_esn_without_intermediary_evidence_is_not_assumed_intermediary():
    result = compare_companies_with_advertiser_role("Client", "Grande ESN Services", "NO_MATCH", role("Grande ESN recrute son équipe."))

    assert result.result == "DIFFERENT_COMPANIES"


def test_score_67_with_strong_signals_and_intermediary_can_be_simulated_present():
    detected = role("Cabinet de recrutement, nous accompagnons notre client dans sa recherche.")

    assert strong_match_via_intermediary(candidate(), detected) is True


def test_score_67_without_intermediary_stays_not_present_simulation():
    detected = role("Nous recrutons un développeur pour notre équipe interne.")

    assert strong_match_via_intermediary(candidate(desc=0.1, geo="DIFFERENT"), detected) is False


def test_no_final_client_is_invented():
    detected = role("Pour le compte de notre client, nous recherchons un développeur.")
    result = compare_companies_with_advertiser_role("Entreprise A", "Cabinet B", "NO_MATCH", detected)

    assert result.free_work_company == "Entreprise A"
    assert result.france_travail_company == "Cabinet B"
    assert "client final" not in result.message.lower()


def test_absent_text_role_unknown():
    detected = detect_advertiser_role(None, "")

    assert detected.advertiser_role == "UNKNOWN"
    assert detected.advertiser_role_evidence == []

"""
Calcule la modalité dominante (présentiel / distanciel / mixte) par RNCP
à partir du CSV CDC filtré.
"""

import pandas as pd


def extract_modalite_dominante(cdc_filtered_path: str) -> pd.DataFrame:
    """Retourne un DataFrame [code_rncp, modalite] avec la modalité majoritaire par RNCP."""
    cdc = pd.read_csv(
        cdc_filtered_path,
        sep=";",
        dtype={"code_rncp": str, "nb_dossiers": "Int64"},
        encoding="utf-8",
    )
    dominante = (
        cdc.groupby(["code_rncp", "modalite_presence"])["nb_dossiers"]
        .sum()
        .reset_index()
        .sort_values("nb_dossiers", ascending=False)
        .drop_duplicates("code_rncp")
        [["code_rncp", "modalite_presence"]]
        .rename(columns={"modalite_presence": "modalite"})
    )
    return dominante

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from backend.scripts.matching_normalization import (
    normaliser_entreprise,
    normaliser_localite,
    normaliser_titre,
    normaliser_description,
    extraire_departement
)


def test_normaliser_entreprise():
    assert normaliser_entreprise("Signe +") == "signe"
    assert normaliser_entreprise("Signe+") == "signe"
    assert normaliser_entreprise("SIGNE + SAS") == "signe"
    assert normaliser_entreprise("ECONOCOM INFOGERANCE ET SYSTEME") == "econocom infogerance et systeme"
    assert normaliser_entreprise("Microsoft Groupe") == "microsoft"


def test_normaliser_localite():
    assert normaliser_localite("Aix-en-Provence") == "aix en provence"
    assert normaliser_localite("Aix en Provence") == "aix en provence"
    assert normaliser_localite("AIX EN PROVENCE") == "aix en provence"
    assert normaliser_localite("Ville de Paris") == "paris"


def test_extraire_departement():
    assert extraire_departement("92400") == "92"
    assert extraire_departement("97130") == "971"
    assert extraire_departement("98800") == "988"


def test_normaliser_titre():
    assert normaliser_titre("DÉVELOPPEUR C++ (H/F)") == "developpeur cpp"
    assert normaliser_titre("Ingénieur C# / .NET") == "ingenieur csharp net"
    assert normaliser_titre("Développeur Back-End") == "developpeur backend"
    assert normaliser_titre("Développeur front end") == "developpeur frontend"
    assert normaliser_titre("Consultant fonctionnel SAP SD/MM") == "consultant fonctionnel sap sd/mm"

from enum import Enum


class NiveauRNCP(Enum):
    """Enumère les niveaux RNCP manipulés lors de l'import des offres."""

    NIV3 = "CAP, BEP et équivalents"
    NIV4 = "Niveau Bac"
    NIV5 = "Bac+2 ou équivalents"
    NIV6 = "Bac+3, Bac+4 ou équivalents"
    NIV7 = "Bac+5 et plus ou équivalents"
    NIV8 = "Doctorat"

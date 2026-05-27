import pandas as pd

corr = pd.read_csv("Ressources/correspondance-rome-rncp-tech-6a16c0f17343f806639940.csv", sep=";")
form = pd.read_csv("Ressources/entree_sortie_formation.csv", sep=";")

result = form.merge(corr[["code_rncp", "code_rome", "intitule_rome", "niveau_rncp"]], 
                    on="code_rncp", how="left")
result.to_csv("Ressources/joined.csv", sep=";", index=False)
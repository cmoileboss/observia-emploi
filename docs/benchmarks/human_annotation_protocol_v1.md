# Protocole d'annotation humaine offre–certification — version 1

Version du protocole : `observia-human-annotation-v1`.

Le pilote doit être terminé, contrôlé et analysé avant d'utiliser les paquets complets. Les fichiers `validation_*` doivent rester fermés jusqu'au gel des méthodes et de leurs paramètres.

## Travail demandé

Chaque ligne représente un couple indépendant entre une offre d'emploi et une certification RNCP. Il faut lire les informations fournies, attribuer une note, choisir le critère principal, rédiger une justification concise et indiquer si le jugement est incertain.

Aucune recherche externe ne doit être effectuée. Plusieurs certifications d'une même offre peuvent recevoir la même note. L'ordre des lignes et le code ROME ne constituent pas une vérité terrain.

Le contexte complémentaire dépend de la source et peut être vide. Pour France Travail, il contient par exemple les exigences de formation employeur. Ce contexte fournit un indice, mais ne constitue jamais une vérité terrain. Son absence ne signifie pas qu'une certification est incompatible.

Le lot 6A annote actuellement l'échantillon France Travail. La structure accepte une offre sans code ROME, notamment une offre Free-Work ; un échantillon Free-Work séparé sera construit ultérieurement et le ROME n'en sera pas un filtre obligatoire. Le pilote est inclus dans le paquet development : ses résultats devront être réinjectés par `pair_id` afin d'éviter une seconde annotation des mêmes couples.

## Échelle de pertinence

- `3` — Certification très pertinente, préparant directement aux principales activités et compétences de l'offre.
- `2` — Certification pertinente mais partielle, plus large ou plus spécialisée que l'offre.
- `1` — Lien faible ou indirect, avec seulement quelques compétences transférables.
- `0` — Certification non pertinente ou relevant d'un autre métier.

## Critère principal

La colonne `critere_principal` accepte exactement une valeur :

- `METIER_ACTIVITES` — adéquation avec le métier et les activités ;
- `COMPETENCES` — adéquation avec les compétences demandées ;
- `NIVEAU_PREREQUIS` — niveau ou prérequis réellement déterminant ;
- `SECTEUR_DEBOUCHES` — secteur ou débouchés professionnels ;
- `GENERALITE_SPECIALISATION` — certification trop générale ou trop spécialisée.

Le critère choisi doit expliquer principalement la note, sans empêcher de mentionner d'autres éléments dans la justification.

## Colonnes à remplir

- `score` : entier de `0` à `3` ;
- `critere_principal` : une valeur de la liste ci-dessus ;
- `justification` : texte non vide expliquant le jugement ;
- `incertain` : `OUI` ou `NON`.

Toutes les autres colonnes sont protégées et ne doivent jamais être modifiées. Aucune ligne ne doit être ajoutée, supprimée ou dupliquée.

## Précautions d'aveuglement

Les fichiers annotateurs ne révèlent ni le split, ni la raison de sélection du candidat, ni l'ordre original du pool, ni une méthode de matching. Le fichier `annotation_reference.jsonl` contient les informations cachées : il ne doit pas être transmis aux annotateurs.

Chaque couple doit être jugé indépendamment, y compris lorsqu'il partage la même offre avec d'autres certifications.

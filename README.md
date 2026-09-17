# Carbon Pricing Effects Analysis

**Évaluation causale de l'impact de la Contribution Climat Énergie (CCE) 2014 sur les émissions de GES du secteur transport en France**, par la méthode du Contrôle Synthétique (Abadie, Diamond & Hainmueller, 2010).

> **Statut : recherche exploratoire.** Le pipeline est fonctionnel de bout en bout, mais le résultat obtenu à ce jour **ne satisfait pas** les critères de robustesse fixés par le projet lui-même (voir [Limites et mises en garde](#limites-et-mises-en-garde)). À traiter comme un prototype méthodologique, pas comme une conclusion causale établie.

---

## Sommaire

- [Contexte et question de recherche](#contexte-et-question-de-recherche)
- [Stratégie d'identification](#stratégie-didentification)
- [Résultats](#résultats)
- [Limites et mises en garde](#limites-et-mises-en-garde)
- [Architecture du pipeline](#architecture-du-pipeline)
- [Structure du dépôt](#structure-du-dépôt)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Configuration](#configuration)
- [Données](#données)
- [Pistes d'évolution](#pistes-dévolution)
- [Références](#références)
- [Licence](#licence)

---

## Contexte et question de recherche

La **Contribution Climat Énergie (CCE)**, introduite en France en 2014, constitue une composante carbone intégrée à la fiscalité des énergies fossiles — un choc de politique quasi-naturel sur le prix implicite du carbone dans les carburants.

**Question posée :** la CCE a-t-elle causé une baisse mesurable des émissions de gaz à effet de serre du secteur transport en France, par rapport à la trajectoire qu'aurait suivie le pays en son absence ?

**Question d'identification sous-jacente**, à garder en tête à chaque lecture des résultats :
> Quelle est la source de variation exploitée, et quelles sont les menaces à la validité interne de l'estimateur ?

## Stratégie d'identification

| Élément | Valeur |
|---|---|
| **Estimateur** | Synthetic Control Method (Abadie, Diamond & Hainmueller, 2010) |
| **Unité traitée** | France (`FR`) |
| **Variable cible** | `env_air_gge` — émissions GES transport (Eurostat, CRF1A3, THS_T) |
| **Choc de traitement** | CCE 2014 |
| **Hypothèse d'identification** | Une combinaison convexe de pays donateurs non traités réplique la trajectoire contrefactuelle de la France en l'absence de CCE |

Le contrefactuel « France synthétique » est une moyenne pondérée de pays donateurs, les poids étant calculés pour minimiser l'écart pré-traitement (2005–2013) sur la variable cible et un jeu de prédicteurs structurels (motorisation, densité de population, part des renouvelables, etc.). Toutes les variables continues sont transformées en **log-log**, de sorte que le gap France − Synthétique s'interprète directement comme un pourcentage d'impact sur les émissions.

Fenêtres temporelles et seuils structurants (`config.py`) :

| Paramètre | Valeur | Rôle |
|---|---|---|
| Entraînement | 2005–2009 | Calcul des poids W (in-sample) |
| Validation | 2010–2013 | Sélection du donor pool sur RMSE out-of-sample |
| Traitement | 2014 | Mise en œuvre de la CCE |
| Placebo in-time | 2010 | Test de rupture de tendance préexistante |
| Fin de panel | 2023 | Dernier millésime Eurostat disponible |
| Seuil MSPE | ×3 erreur France | Filtre des placebos à mauvais pré-fit |

Le donor pool exclut *a priori* les pays ayant une tarification carbone directe antérieure ou concomitante à 2014 (Suède, Finlande, Danemark, Irlande, etc. — cf. `PAYS_CIBLES` dans `config.py`), pour éviter toute contamination du contrefactuel.

## Résultats

Dernière exécution disponible dans `outputs/figures/` (Stage 2 + Stage 3 relancés le 2026-09-17 sur le master dataset complété par le stage d'imputation TimesFM — voir [Architecture du pipeline](#architecture-du-pipeline)) :

![Résultats SCM et tests de robustesse](outputs/figures/scm_results_20260917.png)
![Effet net (log-gap)](outputs/figures/scm_gap_20260917.png)

| Indicateur | Valeur observée |
|---|---|
| RMSE pré-traitement (France) | 0.0180 log-points |
| Donor pool SCM (outcome-only, Stage 3) | DE (0.765), IT (0.194), AT (0.041) |
| Unités valides après filtre MSPE (bornes ×3 / ÷3) | 8 (pool élargi aux 20 `PAYS_CIBLES`, cf. Stage 3) |
| Ratio MSPE post/pré — France | 7.73 (médiane des 8 unités valides : 16) |
| **p-valeur empirique — placebo in-space (pays)** | **0.750** (rang 6/8) |
| **p-valeur empirique — placebo in-time (permutation temporelle, 18 tirages)** | **0.105** |
| Gap moyen post-2014 | −0.040 log-points ≈ **−4,0 %** d'émissions GES transport, soit de l'ordre de −5 Mt CO₂eq/an sur la base du niveau moyen observé sur la période (ordre de grandeur, pas un chiffre précis) |

**Lecture honnête du résultat :** le pré-fit reste très bon (RMSE 0.0180, sous le seuil de 0.05) et le graphique brut montre une divergence post-2014 visuellement nette. L'élargissement du pool de contrôle à 20 pays (au lieu de 7) a résolu le plancher mécanique de p-valeur qui affectait la version précédente (p ne pouvait alors prendre que 1/3, 2/3 ou 1, faute d'unités valides) : on dispose maintenant de 8 unités placebo valides, et un test de permutation temporelle complémentaire. Mais sur les deux critères, le résultat **ne franchit pas** le seuil p ≤ 0.10 fixé par le projet : le ratio MSPE de la France (7.73) est proche de la médiane des placebos (16), pas dans sa queue supérieure (p = 0.750) ; le test temporel s'en approche sans le passer (p = 0.105). Voir la section suivante.

## Limites et mises en garde

Ce projet documente lui-même une hiérarchie de validité stricte (pré-fit → absence de contamination → significativité des placebos). Sur cette base, l'état actuel présente trois limites qui empêchent une conclusion causale robuste :

1. **Significativité des placebos non atteinte, malgré un pool élargi.** Le plancher mécanique de p-valeur (n=3, p ∈ {1/3, 2/3, 1}) a été résolu en élargissant le pool de contrôle à 20 pays (8 unités valides après filtre MSPE) — mais la p-valeur reste au-dessus de 0.10 sur les deux tests (placebo in-space : 0.750 ; permutation temporelle : 0.105). Ce n'est donc plus une limite de puissance statistique, mais un résultat de fond : le ratio MSPE de la France n'est pas extrême dans la distribution des placebos.
2. **Absence de traitement du choc COVID-19.** Le gap post-2014 rapporté est fortement tiré par l'effondrement de la mobilité en 2020, un choc exogène sans lien avec la CCE. Le test de permutation temporelle hors 2020 (p = 0.111, ratio 4.74) suggère que ce choc n'est pas seul en cause, mais aucune spécification alternative (sous-périodes, DiD synthétique) n'isole complètement cet effet à ce stade.
3. **`diesel_price_ht` reste écarté, mais plus par manque de données.** Un stage d'imputation TimesFM (`src/timesfm_imputation.py`, optionnel — voir plus bas) a comblé le trou 2004 qui excluait auparavant `diesel_price_ht` de la sélection du Stage 2 sur toute la fenêtre d'entraînement 2005–2009. La série est désormais éligible, mais n'est toujours pas retenue par la sélection gloutonne (RMSE de validation) — une limite de spécification, pas de disponibilité des données.

**En clair : le graphique de gap seul ne suffit pas à conclure à un effet causal de la CCE sur ce panel.** Voir [Pistes d'évolution](#pistes-dévolution) pour les leviers identifiés afin de renforcer l'inférence.

## Architecture du pipeline

```
run_pipeline.py
│
├── Stage 1 — src/data_pipeline.py
│   Entrées : API Eurostat (live) + Data/raw/oil/Weekly_Oil_Bulletin_*.xlsx
│   Sortie  : Data/processed/master_dataset_final_scm.csv
│
├── Stage 2 — src/donor_selection.py
│   Entrée  : Data/processed/master_dataset_final_scm.csv
│   Algo    : optimisation alternée (moteur A : pays, moteur B : prédicteurs)
│   Sortie  : Data/processed/optimal_joint_panel.csv
│
├── Stage 3 — src/scm_estimation.py
│   Entrée  : Data/processed/optimal_joint_panel.csv
│   Tests   : placebo in-space, placebo in-time (2010), filtre MSPE (×3)
│   Sorties : outputs/figures/scm_results_YYYYMMDD.png
│             outputs/figures/scm_gap_YYYYMMDD.png
│
└── Stage optionnel — src/timesfm_imputation.py  (--only impute, entre Stage 1 et 2)
    Entrée/Sortie : Data/processed/master_dataset_final_scm.csv (écrasé, complété)
    Remplace le flat-fill des bords utilisé par défaut dans Stages 2/3
    (pandas interpolate limit_direction='both') par un forecast/backcast
    TimesFM 2.5 — nécessite l'environnement dédié .venv-timesfm (voir
    scripts/setup_timesfm_env.sh), incompatible avec le .venv principal.
```

Chaque stage peut être relancé indépendamment via `run_pipeline.py` (voir [Utilisation](#utilisation)). Les paramètres structurants sont centralisés dans `config.py` et ne doivent pas être modifiés sans validation (cf. `AGENTS.md`).

## Structure du dépôt

```
.
├── AGENTS.md                    # Instructions détaillées pour intervention sur le projet
├── config.py                    # Paramètres centralisés (chemins, fenêtres, seuils, donor pool)
├── run_pipeline.py              # Point d'entrée unique (orchestration des 3 stages)
├── requirements.txt
├── docs/
│   └── synthese_technique.md    # Cadre analytique et stratégie d'identification détaillée
├── src/
│   ├── data_pipeline.py         # Stage 1 — ingestion Eurostat + Weekly Oil Bulletin
│   ├── donor_selection.py       # Stage 2 — sélection optimale du donor pool
│   └── scm_estimation.py        # Stage 3 — estimation SCM + tests de robustesse
├── Data/
│   ├── raw/                     # Sources brutes (Eurostat, Weekly Oil Bulletin)
│   └── processed/               # Master dataset et panel optimal (générés)
└── outputs/
    └── figures/                 # Graphiques SCM générés (datés YYYYMMDD)
```

> `main.py`, `donor_selection.py` et `econ_analysis.py` à la racine sont d'anciens scripts, conservés comme stubs qui lèvent une erreur explicite pointant vers `src/` — ne pas les utiliser.

## Installation

Prérequis : Python ≥ 3.10.

```bash
git clone https://github.com/hcollotd2-crypto/Carbon-pricing-effects-analysis.git
cd Carbon-pricing-effects-analysis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Utilisation

```bash
# Pipeline complet (télécharge les données, sélectionne le donor pool, estime le SCM)
python run_pipeline.py

# Reprendre à partir d'un stage donné (si les données amont existent déjà)
python run_pipeline.py --from stage2
python run_pipeline.py --from stage3

# Exécuter un seul stage
python run_pipeline.py --only stage3
```

Les stages peuvent aussi être exécutés directement :

```bash
python src/data_pipeline.py
python src/donor_selection.py
python src/scm_estimation.py
```

Les résultats numériques (RMSE, poids, p-valeur) sont imprimés dans la console à chaque exécution du Stage 3 ; les figures sont écrites dans `outputs/figures/`.

## Configuration

Toute modification structurante passe par `config.py`. Principaux leviers :

| Paramètre | Rôle |
|---|---|
| `PAYS_CIBLES` | Liste des pays candidats au donor pool |
| `TREATED_UNIT`, `TARGET_VAR` | Unité traitée et variable cible |
| `TRAIN_START` / `TRAIN_END` / `VAL_END` / `TREATMENT_YEAR` / `PLACEBO_YEAR` / `PANEL_END` | Fenêtres temporelles |
| `MIN_DONORS`, `MIN_PREDICTORS`, `MAX_ITER` | Paramètres de l'optimisation alternée (Stage 2) |
| `MSPE_THRESHOLD` | Seuil d'exclusion des placebos à mauvais pré-fit |
| `CODES_EUROSTAT`, `FILTRES_EUROSTAT` | Séries Eurostat téléchargées et filtres appliqués |

Voir `docs/synthese_technique.md` pour la justification économétrique de chaque paramètre.

## Données

| Source | Contenu | Accès |
|---|---|---|
| [Eurostat](https://ec.europa.eu/eurostat) | Émissions GES transport, motorisation, densité, énergie, PIB | API live (`eurostat` package Python) |
| [Weekly Oil Bulletin](https://energy.ec.europa.eu/) | Prix hebdomadaires du diesel hors taxes | Fichier Excel fourni dans `Data/raw/oil/` |

⚠️ Les données Eurostat sont récupérées en direct via API à chaque exécution du Stage 1 ; les millésimes peuvent être révisés par Eurostat entre deux exécutions, ce qui peut faire varier légèrement les résultats d'une run à l'autre. Les CSV présents dans `Data/raw/eurostat/` sont des extraits partiels de référence, pas un snapshot figé utilisé par le pipeline.

## Pistes d'évolution

Par ordre de priorité pour renforcer la robustesse de l'inférence :

1. ~~Élargir le pool de contrôle~~ **Fait (2026-09-16)** pour les 20 `PAYS_CIBLES` UE (8 unités valides au lieu de 3) — reste à tester au-delà de l'UE (OCDE : USA, Canada, Australie, Japon, Corée du Sud) pour voir si ça déplace le rang de la France dans la distribution des placebos.
2. ~~Assouplir le critère d'exclusion sur données manquantes~~ **Fait (2026-09-17)** via le stage optionnel d'imputation TimesFM (`src/timesfm_imputation.py`) — `diesel_price_ht` est désormais éligible sur la fenêtre d'entraînement 2005–2009, mais n'est toujours pas retenu par la sélection gloutonne sur critère RMSE.
3. **Isoler l'effet COVID-19** via une spécification Synthetic Difference-in-Differences ou une lecture séparée 2014–2019 / 2020–2023.
4. **Comparer à des estimateurs alternatifs** (DiD à deux voies, inférence conforme à la Chernozhukov et al.) pour tester la stabilité du signe et de l'ordre de grandeur hors du cadre SCM strict.
5. **Étendre l'analyse à d'autres secteurs énergétiques** (résidentiel, industrie) couverts par la CCE, moins exposés au confondant de mobilité COVID que le transport seul.
6. **Automatiser la traçabilité des résultats** : journaliser à chaque exécution du Stage 3 (date, RMSE, p-valeur, donor pool, prédicteurs) dans un fichier de log ou le tableau de `docs/synthese_technique.md`.

## Références

- Abadie, A., Diamond, A., & Hainmueller, J. (2010). *Synthetic Control Methods for Comparative Case Studies.* Journal of the American Statistical Association, 105(490), 493–505.
- Abadie, A. (2021). *Using Synthetic Controls: Feasibility, Data Requirements, and Methodological Aspects.* Journal of Economic Literature, 59(2), 391–425.
- [World Bank Carbon Pricing Dashboard](https://carbonpricingdashboard.worldbank.org)

## Licence

Aucune licence n'est actuellement définie pour ce dépôt. Contacter l'auteur avant toute réutilisation.

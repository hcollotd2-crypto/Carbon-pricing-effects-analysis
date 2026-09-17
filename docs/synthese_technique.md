# Synthèse Technique — Évaluation causale CCE 2014 (SCM)
*Économétrie de l'impact de la taxe carbone française sur les émissions GES transport*

> **Fichier de référence** — À lire en début de session avant toute intervention sur le projet.

---

## 1. Question d'identification centrale

> Quelle est la source de variation exploitée, et quelles sont les menaces à la validité interne de l'estimateur ?

**Réponse** : La Contribution Climat Énergie (CCE) introduite en France en 2014 constitue un choc de politique fiscale quasi-naturel. La variation exploitée est la discontinuité temporelle dans le prix carbone implicite des carburants en France, en l'absence de choc équivalent dans les pays membres de l'UE non traiteurs (donor pool). L'estimateur du Contrôle Synthétique (ADH 2010) construit un contrefactuel France en combinaison convexe des donateurs.

---

## 2. Cadre analytique

| Élément | Valeur |
|---|---|
| **Estimateur** | Synthetic Control Method (Abadie, Diamond & Hainmueller, 2010) |
| **Unité traitée** | France (`FR`) |
| **Variable cible** | `env_air_gge` (émissions GES transport, CRF1A3, THS_T) |
| **Choc de traitement** | CCE 2014 (Contribution Climat Énergie) |
| **Hypothèse d'identification** | La combinaison convexe des donateurs réplique la trajectoire contrefactuelle de la France en l'absence de CCE |

---

## 3. Paramètres structurants

> ⚠️ Ces valeurs sont définies dans `config.py`. Ne pas modifier sans validation.

| Paramètre | Valeur | Justification |
|---|---|---|
| `TRAIN_START` | 2005 | Début du calcul des poids W |
| `TRAIN_END` | 2009 | Fin de la fenêtre d'entraînement |
| `VAL_END` | 2013 | Fin de la fenêtre de validation (RMSE OOS) |
| `TREATMENT_YEAR` | 2014 | Mise en œuvre de la CCE |
| `PLACEBO_YEAR` | 2010 | Faux traitement (placebo in-time) |
| `PANEL_END` | 2023 | Dernier millésime Eurostat disponible |
| `MIN_DONORS` | 6 | Stabilisation du simplex |
| `MIN_PREDICTORS` | 2 | Forçage sur les confounders structurels |
| `MSPE_THRESHOLD` | 3× | Filtre des placebos à mauvais pre-fit |

---

## 4. Transformation des variables

**Règle générale** : transformation log-log systématique sur toutes les variables continues.

**Exception** : `nrg_ind_ren` (part des renouvelables, déjà en %) → pas de log.

**Traitement des zéros** : toute valeur ≤ 0 est remplacée par `0.0001` avant application du log.

**Interprétation** : en log-log, le gap France − Synthétique est directement interprétable comme un pourcentage d'impact sur les émissions. Un gap de −0.10 correspond à une réduction d'environ 10%.

---

## 5. Architecture du pipeline

```
run_pipeline.py
│
├── Stage 1 : src/data_pipeline.py
│   Entrées  : API Eurostat + Data/raw/oil/Weekly_Oil_Bulletin_*.xlsx
│   Sortie   : Data/processed/master_dataset_final_scm.csv
│
├── Stage 2 : src/donor_selection.py
│   Entrée   : Data/processed/master_dataset_final_scm.csv
│   Sortie   : Data/processed/optimal_joint_panel.csv
│   Algo     : Optimisation alternée (moteur A : pays, moteur B : prédicteurs)
│
└── Stage 3 : src/scm_estimation.py
    Entrée   : Data/processed/optimal_joint_panel.csv
    Sorties  : outputs/figures/scm_results_YYYYMMDD.png
               outputs/figures/scm_gap_YYYYMMDD.png
```

---

## 6. Protocole d'exclusion du donor pool

**Exclus (risque élevé)** : pays avec taxe carbone directe avant 2014 :
Suède (1991), Finlande (1990), Norvège (1991), Danemark (1992), Suisse (2008), Irlande (2010), Islande (2010).

**À surveiller (risque moyen)** : pays ayant introduit une taxe carbone entre 2015 et 2020 — biais potentiel sur la période post-traitement.

**Distinction clé** : seule une taxe carbone directe (prix fixé sur la teneur en CO₂ des combustibles) constitue un choc d'exclusion. Un ETS (mécanisme de quotas) n'est **pas** excluant.

---

## 7. Checklist de robustesse SCM

À chaque modification substantielle, vérifier :

**Validité interne**
- [ ] RMSE pré-traitement France < 0.05 log-points
- [ ] Qualité du pre-fit visuel (graphique A)
- [ ] Stabilité des poids W (pas de concentration excessive)

**Tests de permutation**
- [ ] Ratio MSPE FR parmi les plus élevés des unités valides (p-valeur ≤ 0.10)
- [ ] Placebo in-time 2010 : pas de gap significatif avant le vrai traitement
- [ ] Filtre MSPE actif (3× erreur France)

**Spécification**
- [ ] Stabilité des résultats selon la fenêtre de validation (2010–2012 vs 2010–2013)
- [ ] Sensibilité au seuil MSPE (2× vs 3× vs 5×)
- [ ] Robustesse leave-one-out (exclusion séquentielle d'un donateur)

---

## 8. Résultats courants

*À compléter après chaque exécution du pipeline.*

| Date | RMSE pré | Gap moyen post-2014 | Ratio MSPE FR | p-valeur (pays) | p-valeur (temps) | Donor pool (Stage 3, outcome-only) |
|---|---|---|---|---|---|---|
| 2026-09-17 | 0.0180 | −0.040 log-pts (≈ −4,0 %) | 7.73 (médiane placebos : 16) | 0.750 (rang 6/8) | 0.105 (18 tirages) | DE (0.765), IT (0.194), AT (0.041) — master dataset complété par imputation TimesFM |

---

## 9. Références

- Abadie, A., Diamond, A., & Hainmueller, J. (2010). Synthetic Control Methods for Comparative Case Studies. *Journal of the American Statistical Association*, 105(490), 493–505.
- Abadie, A. (2021). Using Synthetic Controls: Feasibility, Data Requirements, and Methodological Aspects. *Journal of Economic Literature*, 59(2), 391–425.
- World Bank Carbon Pricing Dashboard : https://carbonpricingdashboard.worldbank.org

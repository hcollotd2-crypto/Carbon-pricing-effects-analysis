"""
config.py — Paramètres centralisés du pipeline SCM (CCE 2014)
=============================================================
Toute modification structurante (fenêtres temporelles, donor pool,
seuils MSPE) doit passer par ce fichier, conformément à la
hiérarchie de validité du projet.
"""

from pathlib import Path

# ─────────────────────────────────────────────
# RACINE DU PROJET (résolution automatique)
# ─────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent

# ─────────────────────────────────────────────
# CHEMINS — DONNÉES BRUTES
# ─────────────────────────────────────────────
DATA_RAW_DIR       = PROJECT_ROOT / "Data" / "raw"
DATA_EUROSTAT_DIR  = DATA_RAW_DIR / "eurostat"
DATA_OIL_DIR       = DATA_RAW_DIR / "oil"
DATA_UNFCCC_DIR    = DATA_RAW_DIR / "unfccc"

FICHIER_OIL = DATA_OIL_DIR / "Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx"
# FICHIER_OCDE = DATA_EUROSTAT_DIR / "OECD_gdp_per_capita.csv"  # décommenter si réactivé

# Extension OCDE hors UE (src/oecd_extension.py) — émissions transport
# (env_air_gge) pour des pays à risque carbone faible sur 2005-2023,
# cf. classification documentée dans le README. Snapshot mis en cache,
# pas un appel réseau à chaque exécution.
OECD_EXTRA_PATH = DATA_UNFCCC_DIR / "transport_ghg_non_eu.csv"

# ─────────────────────────────────────────────
# CHEMINS — DONNÉES TRAITÉES
# ─────────────────────────────────────────────
DATA_PROCESSED_DIR    = PROJECT_ROOT / "Data" / "processed"
DATA_ARCHIVE_DIR      = DATA_PROCESSED_DIR / "archive"
MASTER_DATASET_PATH   = DATA_PROCESSED_DIR / "master_dataset_final_scm.csv"
OPTIMAL_PANEL_PATH    = DATA_PROCESSED_DIR / "optimal_joint_panel.csv"
IMPUTATION_REPORT_PATH = DATA_PROCESSED_DIR / "imputation_report.csv"

# ─────────────────────────────────────────────
# STAGE OPTIONNEL — IMPUTATION TIMESFM
# ─────────────────────────────────────────────
# Nécessite un environnement dédié (torch + timesfm), incompatible avec le
# .venv principal — voir scripts/setup_timesfm_env.sh et src/timesfm_imputation.py
TIMESFM_VENV_PYTHON = PROJECT_ROOT / ".venv-timesfm" / "bin" / "python"

# ─────────────────────────────────────────────
# CHEMINS — OUTPUTS
# ─────────────────────────────────────────────
OUTPUTS_DIR  = PROJECT_ROOT / "outputs"
FIGURES_DIR  = OUTPUTS_DIR / "figures"

# ─────────────────────────────────────────────
# GÉOGRAPHIE
# ─────────────────────────────────────────────

# 21 États membres de l'UE constituant le donor pool initial
# (pays avec taxe carbone antérieure à 2014 exclus en aval dans donor_selection)
PAYS_CIBLES = [
    'AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'EE', 'EL',
    'ES', 'FR', 'HR', 'HU', 'IT', 'LT', 'LU',
    'LV', 'MT', 'NL', 'PL', 'RO', 'SK'
]

# Mapping ISO-3 (OCDE) → ISO-2 (Eurostat)
DICO_OCDE_ISO2 = {
    'AUT': 'AT', 'BEL': 'BE', 'BGR': 'BG', 'CYP': 'CY', 'CZE': 'CZ',
    'DEU': 'DE', 'EST': 'EE', 'GRC': 'EL', 'ESP': 'ES', 'FRA': 'FR',
    'HRV': 'HR', 'HUN': 'HU', 'ITA': 'IT', 'LTU': 'LT', 'LUX': 'LU',
    'LVA': 'LV', 'MLT': 'MT', 'NLD': 'NL', 'POL': 'PL', 'ROU': 'RO',
    'SVK': 'SK'
}

# ─────────────────────────────────────────────
# UNITÉ TRAITÉE & VARIABLE CIBLE
# ─────────────────────────────────────────────
TREATED_UNIT = "FR"
TARGET_VAR   = "env_air_gge"   # émissions GES transport, CRF1A3, THS_T

# ─────────────────────────────────────────────
# FENÊTRES TEMPORELLES
# ─────────────────────────────────────────────
# ⚠️ Ne pas modifier sans validation — cf. §3.2 des instructions du projet
ANNEE_MIN        = 2004   # première année du panel brut
TRAIN_START      = 2005   # début de la période d'entraînement (calcul des poids W)
TRAIN_END        = 2009   # fin de la période d'entraînement
VAL_END          = 2013   # fin de la période de validation (RMSE out-of-sample)
TREATMENT_YEAR   = 2014   # mise en œuvre de la CCE
PLACEBO_YEAR     = 2010   # faux traitement pour le placebo in-time
PANEL_END        = 2023   # dernier millésime Eurostat disponible

# Années exclues pour le contrôle de robustesse "sans choc COVID" du test de
# permutation temporelle (time_permutation_pvalue). N'affecte ni l'estimation
# principale ni le panel — sert uniquement à vérifier que la quasi-significativité
# du test temporel ne repose pas seulement sur le creux de mobilité de 2020.
COVID_EXCLUDED_YEARS = [2020]

# Prédicteurs structurels pour la variante "SCM augmenté" (scm_estimation.
# run_scm_predictor_augmented) — choisis pour représenter les canaux
# théoriques de la CCE (motorisation, mix énergétique, prix du carburant)
# et complets pour la quasi-totalité de PAYS_CIBLES après imputation TimesFM.
# La Grèce (EL) n'a aucune donnée diesel_price_ht (Weekly Oil Bulletin) et
# est donc exclue du pool candidat de cette variante uniquement.
PREDICTOR_VARS = ['road_eqs_carhab', 'nrg_ind_ren', 'diesel_price_ht']

# ─────────────────────────────────────────────
# PARAMÈTRES SCM
# ─────────────────────────────────────────────
MIN_DONORS     = 6    # minimum de pays dans le simplex
MIN_PREDICTORS = 2    # minimum de prédicteurs (forçage confounders)
MAX_ITER       = 5    # iterations max de l'optimisation alternée
MSPE_THRESHOLD = 3    # seuil d'exclusion des placebos (× erreur France)

# ─────────────────────────────────────────────
# FILTRES EUROSTAT
# ─────────────────────────────────────────────
FILTRES_EUROSTAT = {
    'env_air_gge':    lambda df: df[(df['src_crf'] == 'CRF1A3') & (df['airpol'] == 'GHG') & (df['unit'] == 'THS_T')],
    'nrg_ind_ren':    lambda df: df[df['nrg_bal'] == 'REN'],
    'road_eqs_carmot': lambda df: df[(df['mot_nrg'] == 'DIE') & (df['engine'] == 'TOTAL')],
}

# Codes Eurostat à télécharger (variables cible + prédicteurs candidats)
CODES_EUROSTAT = list(FILTRES_EUROSTAT.keys()) + [
    'demo_r_d3dens', 'road_eqs_carhab', 'sdg_07_11', 'sdg_07_30', 'sdg_08_10'
]

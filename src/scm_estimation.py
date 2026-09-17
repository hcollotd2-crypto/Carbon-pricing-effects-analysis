"""
src/scm_estimation.py — Stage 3 : Estimation SCM + tests de robustesse
=======================================================================
Entrée  : Data/processed/master_dataset_final_scm.csv (SCM outcome-only,
          tous les candidats PAYS_CIBLES — découplé de la sélection de
          donneurs/prédicteurs du Stage 2, cf. justification ci-dessous)
Sorties : outputs/figures/scm_results_YYYYMMDD.png
          outputs/figures/scm_gap_YYYYMMDD.png

Transformations : Log-Log systématique sur toutes les variables continues
                  (exception : nrg_ind_ren déjà en %)
Tests inclus    : Placebo in-space, Placebo in-time (2010), filtre MSPE (3×)

Note méthodologique — SCM outcome-only sur pool élargi (2026-09) :
L'estimation des poids W (get_w) n'utilise que les valeurs pré-traitement
de TARGET_VAR (approche ADH classique par lags de la variable de résultat),
sans les prédicteurs structurels sélectionnés au Stage 2. Comme TARGET_VAR
est complet sur 2005-2023 pour les 20 candidats PAYS_CIBLES (et pas
seulement les 7 donneurs retenus par la sélection gloutonne du Stage 2),
le Stage 3 est ici alimenté par le master dataset complet plutôt que par
le panel restreint du Stage 2 — afin d'élargir la base de la distribution
de permutation (placebo in-space) et de sortir du plancher de p-valeur
mécanique (p ∈ {1/3, 2/3, 1}) observé avec seulement 3 unités valides.
Le Stage 2 reste exécutable indépendamment (utile pour une future
extension du SCM aux prédicteurs structurels), mais n'est plus une
dépendance du Stage 3.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date
from pathlib import Path
from scipy.optimize import minimize

from config import (
    TREATED_UNIT, TARGET_VAR, TREATMENT_YEAR, PLACEBO_YEAR,
    TRAIN_START, TRAIN_END, PANEL_END, MSPE_THRESHOLD, COVID_EXCLUDED_YEARS,
    PAYS_CIBLES, MASTER_DATASET_PATH, FIGURES_DIR, PREDICTOR_VARS, OECD_EXTRA_PATH
)


# ──────────────────────────────────────────────────────────────────────────────
# 1. CHARGEMENT ET TRANSFORMATION LOG-LOG
# ──────────────────────────────────────────────────────────────────────────────

def load_panel(filepath) -> pd.DataFrame:
    """Charge le panel (Stage 2, donor pool restreint) et applique le log-log.

    Conservé pour compatibilité / usage exploratoire, mais n'est plus la
    source par défaut de main() — voir load_target_panel_full_pool().
    """
    df = pd.read_csv(filepath)

    cols_vars = [c for c in df.columns if c not in ['geo', 'year']]

    # Interpolation par pays
    df[cols_vars] = df.groupby('geo')[cols_vars].transform(
        lambda x: x.interpolate(method='linear', limit_direction='both')
    )

    # Log-Log (exception : nrg_ind_ren déjà en %)
    cols_to_log = [c for c in cols_vars if c != 'nrg_ind_ren']
    for col in cols_to_log:
        df.loc[df[col] <= 0, col] = 0.0001
        df[col] = np.log(df[col])

    return df


def load_target_panel_full_pool(filepath, pays_cibles: list, target_var: str,
                                 year_start: int, year_end: int,
                                 extra_pays_filepath=None) -> pd.DataFrame:
    """Charge TARGET_VAR pour tous les candidats PAYS_CIBLES depuis le master
    dataset (SCM outcome-only), borné à [year_start, year_end], interpolé
    par pays puis transformé en log. Indépendant de la sélection du Stage 2.

    `extra_pays_filepath` (ex. OECD_EXTRA_PATH) fusionne des pays candidats
    supplémentaires au même format wide (geo, variable, années) — utilisé
    pour l'extension OCDE hors UE (src/oecd_extension.py). Les années
    manquantes pour ces pays (ex. 2022-2023, absentes du snapshot UNFCCC)
    sont comblées par la même interpolation de bord que le reste du panel,
    pas par une observation réelle.
    """
    df_raw = pd.read_csv(filepath)
    df_target = df_raw[
        (df_raw['variable'] == target_var) & (df_raw['geo'].isin(pays_cibles))
    ].copy()

    if extra_pays_filepath is not None and Path(extra_pays_filepath).exists():
        df_extra = pd.read_csv(extra_pays_filepath)
        df_extra = df_extra[df_extra['variable'] == target_var]
        df_target = pd.concat([df_target, df_extra], ignore_index=True)
        pays_cibles = pays_cibles + df_extra['geo'].tolist()

    year_cols = [c for c in df_target.columns
                 if str(c).isdigit() and year_start <= int(c) <= year_end]
    df_long = df_target.melt(
        id_vars=['geo'], value_vars=year_cols, var_name='year', value_name=target_var
    )
    df_long['year'] = df_long['year'].astype(int)
    df_long.sort_values(['geo', 'year'], inplace=True)

    df_long[target_var] = df_long.groupby('geo')[target_var].transform(
        lambda x: x.interpolate(method='linear', limit_direction='both')
    )

    df_long.loc[df_long[target_var] <= 0, target_var] = 0.0001
    df_long[target_var] = np.log(df_long[target_var])

    return df_long.reset_index(drop=True)


def load_predictor_augmented_data(filepath, pays_cibles: list, target_var: str,
                                   predictor_vars: list, year_start: int,
                                   year_end: int) -> tuple:
    """Charge TARGET_VAR + PREDICTOR_VARS pour les candidats PAYS_CIBLES ayant
    des données complètes sur toutes ces variables (un candidat totalement
    dépourvu d'une variable, ex. la Grèce pour diesel_price_ht, est exclu du
    pool avec un avertissement plutôt que silencieusement mis à zéro).

    Retourne (data_by_var, valid_countries) où data_by_var[var] est un pivot
    year × geo (log sauf nrg_ind_ren, interpolé par pays).
    """
    df_raw = pd.read_csv(filepath)
    all_vars = [target_var] + predictor_vars

    valid_countries = set(pays_cibles)
    for var in all_vars:
        present = set(df_raw.loc[df_raw['variable'] == var, 'geo'])
        missing = valid_countries - present
        if missing:
            print(f"   [Prédicteurs] {var} absent pour {sorted(missing)} — "
                  f"exclu(s) du pool candidat de la variante augmentée.")
        valid_countries &= present
    valid_countries = sorted(valid_countries)

    data_by_var = {}
    for var in all_vars:
        sub = df_raw[
            (df_raw['variable'] == var) & (df_raw['geo'].isin(valid_countries))
        ].copy()
        year_cols = [c for c in sub.columns
                     if str(c).isdigit() and year_start <= int(c) <= year_end]
        long = sub.melt(id_vars=['geo'], value_vars=year_cols,
                         var_name='year', value_name=var)
        long['year'] = long['year'].astype(int)
        long.sort_values(['geo', 'year'], inplace=True)
        long[var] = long.groupby('geo')[var].transform(
            lambda x: x.interpolate(method='linear', limit_direction='both')
        )
        if var != 'nrg_ind_ren':
            long.loc[long[var] <= 0, var] = 0.0001
            long[var] = np.log(long[var])
        data_by_var[var] = long.pivot(index='year', columns='geo', values=var)

    return data_by_var, valid_countries


# ──────────────────────────────────────────────────────────────────────────────
# 2. OPTIMISATION SCM
# ──────────────────────────────────────────────────────────────────────────────

def get_w(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Poids W minimisant le RMSE pré-traitement sous contraintes simplex."""
    w_init = np.ones(X.shape[1]) / X.shape[1]

    def loss_w(W, X, y):
        return np.sqrt(np.mean((y - X @ W) ** 2))

    cons = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
    bounds = [(0, 1)] * X.shape[1]
    res = minimize(loss_w, w_init, args=(X, y), method='SLSQP',
                   bounds=bounds, constraints=cons)
    return res.x


def get_w_predictor_augmented(data_by_var: dict, treated_unit: str, donors: list,
                               target_var: str, predictor_vars: list,
                               pre_years) -> np.ndarray:
    """Poids W ajustés sur la variable cible (une ligne par année
    pré-traitement, comme get_w) ET sur des prédicteurs structurels (une
    ligne par prédicteur = sa moyenne pré-traitement), à la manière d'ADH.

    Simplification assumée par rapport à l'ADH complet : chaque bloc
    (cible et chaque prédicteur) est standardisé (centré-réduit sur
    traité+donneurs) avant d'être empilé, ce qui revient à donner à
    chaque variable un poids d'importance V = 1/variance — la
    recommandation par défaut de la littérature SCM quand la pondération V
    n'est pas calibrée par optimisation imbriquée (nested optimization),
    plutôt qu'une vraie estimation de V. Pas de biais de fuite : la
    standardisation n'utilise que les années pré-traitement.
    """
    rows_X, rows_y = [], []

    df_t = data_by_var[target_var]
    sub_t = df_t.loc[df_t.index.isin(pre_years)]
    all_units = [treated_unit] + donors
    mu_t, sigma_t = sub_t[all_units].values.mean(), sub_t[all_units].values.std()
    rows_X.append(((sub_t[donors] - mu_t) / sigma_t).values)
    rows_y.append(((sub_t[treated_unit] - mu_t) / sigma_t).values)

    for pred in predictor_vars:
        df_p = data_by_var[pred]
        sub_p = df_p.loc[df_p.index.isin(pre_years)]
        pre_means = sub_p[all_units].mean(axis=0)
        mu_p, sigma_p = pre_means.mean(), pre_means.std()
        rows_X.append(((pre_means[donors] - mu_p) / sigma_p).values.reshape(1, -1))
        rows_y.append(np.array([(pre_means[treated_unit] - mu_p) / sigma_p]))

    X = np.vstack(rows_X)
    y = np.concatenate(rows_y)
    return get_w(X, y)


# ──────────────────────────────────────────────────────────────────────────────
# 3. CALCUL MSPE
# ──────────────────────────────────────────────────────────────────────────────

def calculate_mspe(unit_gap: np.ndarray, t_year: int,
                   years: pd.Index, pre_or_post: str = 'pre') -> float:
    if pre_or_post == 'pre':
        return float(np.mean(unit_gap[years < t_year] ** 2))
    return float(np.mean(unit_gap[years >= t_year] ** 2))


# ──────────────────────────────────────────────────────────────────────────────
# 3bis. INFÉRENCE PAR PERMUTATION TEMPORELLE (indépendante du nombre de pays)
# ──────────────────────────────────────────────────────────────────────────────

def time_permutation_pvalue(gap: pd.Series, treatment_year: int,
                             exclude_years: list = None) -> dict:
    """Test de permutation circulaire des résidus de l'unité traitée (Piste B).

    Principe (variante simplifiée de Chernozhukov, Wüthrich & Zhu, 2021, dans
    l'esprit des tests de permutation temporelle de Politis & Romano) :
    au lieu de comparer la France à d'autres pays (placebo in-space, limité
    par le nombre de donneurs disponibles), on permute circulairement sa
    propre série de résidus (france_gap) sur T années, et on recalcule pour
    chaque rotation le même ratio MSPE post/pré à la même position de coupure
    que le vrai traitement. La p-valeur empirique compare le ratio observé
    à cette distribution de T-1 ratios "placebo temporels".

    Avantage : la granularité de la p-valeur dépend du nombre d'années (T),
    pas du nombre de pays valides après filtre MSPE — totalement indépendant
    de la taille ou de la qualité du donor pool.

    `exclude_years` (ex. COVID_EXCLUDED_YEARS) retire ces années de la série
    avant le calcul — contrôle de robustesse pour vérifier que le résultat ne
    repose pas sur un choc ponctuel sans lien avec le traitement étudié.
    """
    if exclude_years:
        gap = gap.drop(index=[y for y in exclude_years if y in gap.index])

    years = gap.index.to_numpy()
    values = gap.values.astype(float)
    n_years = len(values)
    split_idx = int(np.searchsorted(years, treatment_year))

    def ratio_at_split(v: np.ndarray, idx: int):
        pre, post = v[:idx], v[idx:]
        if len(pre) == 0 or len(post) == 0:
            return np.nan
        pre_mspe = np.mean(pre ** 2)
        if pre_mspe == 0:
            return np.nan
        return np.mean(post ** 2) / pre_mspe

    actual_ratio = ratio_at_split(values, split_idx)

    perm_ratios = []
    for shift in range(1, n_years):
        perm_ratios.append(ratio_at_split(np.roll(values, shift), split_idx))
    perm_ratios = np.array([r for r in perm_ratios if not np.isnan(r)])

    rank = int(np.sum(perm_ratios >= actual_ratio)) + 1
    p_value = rank / (len(perm_ratios) + 1)

    return {
        'actual_ratio':    actual_ratio,
        'perm_ratios':     perm_ratios,
        'p_value':         p_value,
        'n_permutations':  len(perm_ratios),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 3ter. AUTRES CONTRÔLES DE ROBUSTESSE (checklist AGENTS.md §5)
# ──────────────────────────────────────────────────────────────────────────────

def leave_one_out_check(df_emissions: pd.DataFrame, control_units: list,
                         treated_unit: str, treatment_year: int,
                         donors_to_drop: list) -> dict:
    """Robustesse leave-one-out : recalcule le contrôle synthétique de la
    France en retirant tour à tour chaque donneur de `donors_to_drop` (les
    donneurs à poids non nul), pour vérifier que le pré-fit et le gap ne
    reposent pas sur un seul pays (cf. concentration DE=76.5%/IT=19.4%).

    Ne recalcule pas la distribution de permutation par pays (ce qui
    impliquerait de refaire tous les placebos sous le même pool restreint) —
    seulement la stabilité du pré-fit et du gap propres à la France, plus la
    p-valeur de permutation temporelle (indépendante du pool), qui elle reste
    directement comparable d'une variante à l'autre.
    """
    mask_pre = df_emissions.index < treatment_year
    out = {}
    for dropped in donors_to_drop:
        remaining = [c for c in control_units if c != dropped]
        y_pre = df_emissions.loc[mask_pre, treated_unit].values
        X_pre = df_emissions.loc[mask_pre, remaining].values
        w = get_w(X_pre, y_pre)
        synth = df_emissions[remaining].values @ w
        pre_rmse_loo = float(np.sqrt(np.mean((y_pre - X_pre @ w) ** 2)))
        gap_loo = pd.Series(
            df_emissions[treated_unit].values - synth, index=df_emissions.index
        )
        avg_gap_post_loo = float(gap_loo[gap_loo.index >= treatment_year].mean())
        tp_loo = time_permutation_pvalue(gap_loo, treatment_year)
        out[dropped] = {
            'weights':          {c: round(float(x), 3) for c, x in zip(remaining, w)},
            'pre_rmse':         pre_rmse_loo,
            'avg_gap_post':     avg_gap_post_loo,
            'time_p_value':     tp_loo['p_value'],
        }
    return out


def mspe_threshold_sensitivity(placebos_space: dict, mspe_pre_all: dict,
                                treated_unit: str, treatment_year: int,
                                years: pd.Index, thresholds=(2, 3, 5)) -> dict:
    """Robustesse : rang et p-valeur (pays) de la France pour plusieurs
    seuils de bande MSPE (checklist AGENTS.md §5 : "sensibilité au seuil
    MSPE 2× vs 3× vs 5×"), sans relancer d'optimisation — réutilise les
    pré/post-MSPE déjà calculés pour chaque unité.
    """
    post_mspe_all = {
        u: calculate_mspe(g, treatment_year, years, 'post') for u, g in placebos_space.items()
    }
    fr_pre_mspe = mspe_pre_all[treated_unit]
    out = {}
    for thr in thresholds:
        lo, hi = fr_pre_mspe / thr, fr_pre_mspe * thr
        valid = [u for u, e in mspe_pre_all.items() if lo <= e <= hi]
        ratios_t = {u: post_mspe_all[u] / mspe_pre_all[u] for u in valid if mspe_pre_all[u] > 0}
        if treated_unit not in ratios_t:
            out[thr] = {'n_valid': len(valid), 'rank': None, 'p_value': None}
            continue
        rank = sorted(ratios_t.values(), reverse=True).index(ratios_t[treated_unit]) + 1
        out[thr] = {'n_valid': len(ratios_t), 'rank': rank, 'p_value': rank / len(ratios_t)}
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 4. ESTIMATION PRINCIPALE
# ──────────────────────────────────────────────────────────────────────────────

def run_scm(df_panel: pd.DataFrame) -> dict:
    """
    Calcule le contrôle synthétique de la France et tous les tests de robustesse.
    Retourne un dict avec tous les objets nécessaires à la visualisation.
    """
    df_emissions = df_panel.pivot(index='year', columns='geo', values=TARGET_VAR)
    control_units = [c for c in df_emissions.columns if c != TREATED_UNIT]
    print(f"   Pool de contrôle ({len(control_units)}) : {control_units}")

    mask_pre = df_emissions.index < TREATMENT_YEAR

    # ── France synthétique (vrai traitement) ──
    y_pre_fr = df_emissions.loc[mask_pre, TREATED_UNIT].values
    X_pre_fr = df_emissions.loc[mask_pre, control_units].values
    weights_fr = get_w(X_pre_fr, y_pre_fr)
    france_synth = df_emissions[control_units].values @ weights_fr

    pre_rmse = np.sqrt(np.mean((y_pre_fr - X_pre_fr @ weights_fr) ** 2))
    print(f"   RMSE pré-traitement France : {pre_rmse:.4f} log-points")
    print(f"   Poids W : { {c: round(w, 3) for c, w in zip(control_units, weights_fr)} }")

    # ── Placebo in-space ──
    placebos_space = {}
    for unit in df_emissions.columns:
        donor_pool = [c for c in df_emissions.columns if c != unit]
        y_pre = df_emissions.loc[mask_pre, unit].values
        X_pre = df_emissions.loc[mask_pre, donor_pool].values
        w_p = get_w(X_pre, y_pre)
        unit_synth = df_emissions[donor_pool].values @ w_p
        placebos_space[unit] = df_emissions[unit].values - unit_synth

    # ── Placebo in-time (faux traitement 2010) ──
    mask_pre_fake = df_emissions.index < PLACEBO_YEAR
    y_pre_fake = df_emissions.loc[mask_pre_fake, TREATED_UNIT].values
    X_pre_fake = df_emissions.loc[mask_pre_fake, control_units].values
    weights_fake = get_w(X_pre_fake, y_pre_fake)
    france_synth_past = df_emissions[control_units].values @ weights_fake

    # ── Filtre MSPE (bande haute ET basse) ──
    # Borne haute (ADH standard) : exclut les mauvais pré-fits.
    # Borne basse (ajout) : exclut les pré-fits quasi parfaits (pré-MSPE proche
    # de zéro). Avec un donor pool large relativement au nombre de périodes
    # pré-traitement, l'optimiseur peut sur-ajuster presque exactement un
    # placebo (ex. Belgique : pré-MSPE ≈ 1.3e-10), ce qui produit un ratio
    # post/pré numériquement explosif sans rapport avec un signal réel
    # (cf. Abadie, 2021, JEL, sur la dégénérescence du test quand N donneurs
    # se rapproche ou dépasse T0). On exige donc un pré-fit du même ordre de
    # grandeur que celui de la France, dans les deux sens.
    mspe_pre_all = {
        u: calculate_mspe(g, TREATMENT_YEAR, df_emissions.index, 'pre')
        for u, g in placebos_space.items()
    }
    fr_pre_mspe = mspe_pre_all[TREATED_UNIT]
    upper_bound = fr_pre_mspe * MSPE_THRESHOLD
    lower_bound = fr_pre_mspe / MSPE_THRESHOLD
    valid_units = [u for u, e in mspe_pre_all.items() if lower_bound <= e <= upper_bound]
    excluded_overfit = [u for u, e in mspe_pre_all.items() if e < lower_bound]
    if excluded_overfit:
        print(f"   Unités exclues pour pré-fit suspect (sur-ajustement quasi parfait) : "
              f"{excluded_overfit}")

    ratios = {
        u: calculate_mspe(placebos_space[u], TREATMENT_YEAR, df_emissions.index, 'post')
           / mspe_pre_all[u]
        for u in valid_units
    }
    ratios_series = pd.Series(ratios).sort_values()

    rank = sorted(ratios.values(), reverse=True).index(ratios[TREATED_UNIT]) + 1
    p_val = rank / len(valid_units)
    france_gap = pd.Series(
        df_emissions[TREATED_UNIT].values - france_synth,
        index=df_emissions.index
    )

    print(f"\n   Ratio MSPE France : {ratios[TREATED_UNIT]:.2f}")
    print(f"   Rang France / {len(valid_units)} unités valides → p-valeur empirique (pays) : {p_val:.3f}")
    avg_gap_post = france_gap[france_gap.index >= TREATMENT_YEAR].mean()
    print(f"   Gap moyen post-2014 : {avg_gap_post:.3f} log-points "
          f"(≈ {avg_gap_post * 100:.1f}% d'impact)")

    # ── Inférence par permutation temporelle (indépendante du donor pool) ──
    time_perm = time_permutation_pvalue(france_gap, TREATMENT_YEAR)
    print(f"   Permutation temporelle : ratio observé = {time_perm['actual_ratio']:.2f} | "
          f"p-valeur empirique (temps, {time_perm['n_permutations']} permutations) : "
          f"{time_perm['p_value']:.3f}")

    # Contrôle de robustesse : le résultat tient-il sans le choc COVID (2020) ?
    time_perm_no_covid = time_permutation_pvalue(
        france_gap, TREATMENT_YEAR, exclude_years=COVID_EXCLUDED_YEARS
    )
    print(f"   Permutation temporelle (sans {COVID_EXCLUDED_YEARS}) : "
          f"ratio observé = {time_perm_no_covid['actual_ratio']:.2f} | "
          f"p-valeur : {time_perm_no_covid['p_value']:.3f} "
          f"({time_perm_no_covid['n_permutations']} permutations)")

    # ── Leave-one-out sur les donneurs à poids non nul ──
    donors_with_weight = [c for c, w in zip(control_units, weights_fr) if w > 0.01]
    loo = leave_one_out_check(
        df_emissions, control_units, TREATED_UNIT, TREATMENT_YEAR, donors_with_weight
    )
    print(f"\n   Leave-one-out (donneurs à poids non nul : {donors_with_weight}) :")
    for dropped, r in loo.items():
        print(f"      sans {dropped} : RMSE pré = {r['pre_rmse']:.4f} | "
              f"gap post moyen = {r['avg_gap_post']:.3f} | "
              f"p-valeur temps = {r['time_p_value']:.3f} | poids = {r['weights']}")

    # ── Sensibilité au seuil MSPE (checklist §5 : 2× vs 3× vs 5×) ──
    mspe_sensitivity = mspe_threshold_sensitivity(
        placebos_space, mspe_pre_all, TREATED_UNIT, TREATMENT_YEAR,
        df_emissions.index, thresholds=(2, 3, 5)
    )
    print(f"\n   Sensibilité au seuil MSPE :")
    for thr, r in mspe_sensitivity.items():
        print(f"      ×{thr} : {r['n_valid']} unités valides | "
              f"rang France = {r['rank']} | p-valeur = {r['p_value']}")

    return {
        'df_emissions':          df_emissions,
        'france_synth':          france_synth,
        'france_synth_past':     france_synth_past,
        'france_gap':            france_gap,
        'placebos_space':        placebos_space,
        'valid_units':           valid_units,
        'ratios_series':         ratios_series,
        'pre_rmse':              pre_rmse,
        'p_value':               p_val,
        'time_permutation':          time_perm,
        'time_permutation_no_covid': time_perm_no_covid,
        'leave_one_out':             loo,
        'mspe_sensitivity':          mspe_sensitivity,
        'avg_gap_post':          avg_gap_post,
    }


def run_scm_predictor_augmented(data_by_var: dict, valid_countries: list,
                                 target_var: str, predictor_vars: list) -> dict:
    """Variante "SCM augmenté" de run_scm() : les poids W sont ajustés sur la
    variable cible ET les prédicteurs structurels (get_w_predictor_augmented)
    au lieu des seuls lags de la variable cible. Reproduit les mêmes tests de
    robustesse que run_scm() (placebo in-space/in-time, bande MSPE, permutation
    temporelle + contrôle COVID, leave-one-out, sensibilité au seuil MSPE), sur
    le même format de résultats pour rester compatible avec plot_results().

    Objectif : tester si le fait d'ancrer les poids sur des variables
    structurelles (motorisation, mix énergétique, prix carburant), plutôt
    que sur les seules valeurs pré-traitement de la cible, réduit la
    dépendance à un seul pays observée avec le SCM outcome-only (run_scm) —
    l'Allemagne y portait 76.5% du poids et sa seule absence faisait
    exploser le RMSE pré-traitement (0.018 → 0.149) et changer le signe du
    gap post-2014.
    """
    df_emissions = data_by_var[target_var]
    control_units = [c for c in valid_countries if c != TREATED_UNIT]
    print(f"   Pool de contrôle augmenté ({len(control_units)}) : {control_units}")
    print(f"   Prédicteurs structurels : {predictor_vars}")

    pre_years = df_emissions.index[df_emissions.index < TREATMENT_YEAR]

    # ── France synthétique (vrai traitement) ──
    weights_fr = get_w_predictor_augmented(
        data_by_var, TREATED_UNIT, control_units, target_var, predictor_vars, pre_years
    )
    france_synth = df_emissions[control_units].values @ weights_fr

    mask_pre = df_emissions.index < TREATMENT_YEAR
    y_pre_fr = df_emissions.loc[mask_pre, TREATED_UNIT].values
    X_pre_fr = df_emissions.loc[mask_pre, control_units].values
    pre_rmse = np.sqrt(np.mean((y_pre_fr - X_pre_fr @ weights_fr) ** 2))
    print(f"   RMSE pré-traitement France (cible seule, poids augmentés) : {pre_rmse:.4f} log-points")
    print(f"   Poids W : { {c: round(w, 3) for c, w in zip(control_units, weights_fr)} }")

    # ── Placebo in-space ──
    placebos_space = {}
    for unit in valid_countries:
        donor_pool = [c for c in valid_countries if c != unit]
        w_p = get_w_predictor_augmented(
            data_by_var, unit, donor_pool, target_var, predictor_vars, pre_years
        )
        unit_synth = df_emissions[donor_pool].values @ w_p
        placebos_space[unit] = df_emissions[unit].values - unit_synth

    # ── Placebo in-time (faux traitement 2010) ──
    pre_years_fake = df_emissions.index[df_emissions.index < PLACEBO_YEAR]
    weights_fake = get_w_predictor_augmented(
        data_by_var, TREATED_UNIT, control_units, target_var, predictor_vars, pre_years_fake
    )
    france_synth_past = df_emissions[control_units].values @ weights_fake

    # ── Filtre MSPE (bande haute ET basse, cf. run_scm) ──
    mspe_pre_all = {
        u: calculate_mspe(g, TREATMENT_YEAR, df_emissions.index, 'pre')
        for u, g in placebos_space.items()
    }
    fr_pre_mspe = mspe_pre_all[TREATED_UNIT]
    upper_bound = fr_pre_mspe * MSPE_THRESHOLD
    lower_bound = fr_pre_mspe / MSPE_THRESHOLD
    valid_units = [u for u, e in mspe_pre_all.items() if lower_bound <= e <= upper_bound]
    excluded_overfit = [u for u, e in mspe_pre_all.items() if e < lower_bound]
    if excluded_overfit:
        print(f"   Unités exclues pour pré-fit suspect (sur-ajustement quasi parfait) : "
              f"{excluded_overfit}")

    ratios = {
        u: calculate_mspe(placebos_space[u], TREATMENT_YEAR, df_emissions.index, 'post')
           / mspe_pre_all[u]
        for u in valid_units
    }
    ratios_series = pd.Series(ratios).sort_values()
    rank = sorted(ratios.values(), reverse=True).index(ratios[TREATED_UNIT]) + 1
    p_val = rank / len(valid_units)
    france_gap = pd.Series(
        df_emissions[TREATED_UNIT].values - france_synth, index=df_emissions.index
    )

    print(f"\n   Ratio MSPE France : {ratios[TREATED_UNIT]:.2f}")
    print(f"   Rang France / {len(valid_units)} unités valides → p-valeur empirique (pays) : {p_val:.3f}")
    avg_gap_post = france_gap[france_gap.index >= TREATMENT_YEAR].mean()
    print(f"   Gap moyen post-2014 : {avg_gap_post:.3f} log-points (≈ {avg_gap_post * 100:.1f}% d'impact)")

    # ── Permutation temporelle + contrôle COVID ──
    time_perm = time_permutation_pvalue(france_gap, TREATMENT_YEAR)
    print(f"   Permutation temporelle : ratio observé = {time_perm['actual_ratio']:.2f} | "
          f"p-valeur (temps, {time_perm['n_permutations']} permutations) : {time_perm['p_value']:.3f}")
    time_perm_no_covid = time_permutation_pvalue(
        france_gap, TREATMENT_YEAR, exclude_years=COVID_EXCLUDED_YEARS
    )
    print(f"   Permutation temporelle (sans {COVID_EXCLUDED_YEARS}) : "
          f"p-valeur : {time_perm_no_covid['p_value']:.3f} "
          f"({time_perm_no_covid['n_permutations']} permutations)")

    # ── Leave-one-out sur les donneurs à poids non nul ──
    donors_with_weight = [c for c, w in zip(control_units, weights_fr) if w > 0.01]
    loo = {}
    for dropped in donors_with_weight:
        remaining = [c for c in control_units if c != dropped]
        w = get_w_predictor_augmented(
            data_by_var, TREATED_UNIT, remaining, target_var, predictor_vars, pre_years
        )
        X_loo = df_emissions.loc[mask_pre, remaining].values
        pre_rmse_loo = float(np.sqrt(np.mean((y_pre_fr - X_loo @ w) ** 2)))
        synth_loo = df_emissions[remaining].values @ w
        gap_loo = pd.Series(
            df_emissions[TREATED_UNIT].values - synth_loo, index=df_emissions.index
        )
        avg_gap_post_loo = float(gap_loo[gap_loo.index >= TREATMENT_YEAR].mean())
        tp_loo = time_permutation_pvalue(gap_loo, TREATMENT_YEAR)
        loo[dropped] = {
            'weights':      {c: round(float(x), 3) for c, x in zip(remaining, w)},
            'pre_rmse':     pre_rmse_loo,
            'avg_gap_post': avg_gap_post_loo,
            'time_p_value': tp_loo['p_value'],
        }
    print(f"\n   Leave-one-out (donneurs à poids non nul : {donors_with_weight}) :")
    for dropped, r in loo.items():
        print(f"      sans {dropped} : RMSE pré = {r['pre_rmse']:.4f} | "
              f"gap post moyen = {r['avg_gap_post']:.3f} | "
              f"p-valeur temps = {r['time_p_value']:.3f} | poids = {r['weights']}")

    # ── Sensibilité au seuil MSPE ──
    mspe_sensitivity = mspe_threshold_sensitivity(
        placebos_space, mspe_pre_all, TREATED_UNIT, TREATMENT_YEAR,
        df_emissions.index, thresholds=(2, 3, 5)
    )
    print(f"\n   Sensibilité au seuil MSPE :")
    for thr, r in mspe_sensitivity.items():
        print(f"      ×{thr} : {r['n_valid']} unités valides | "
              f"rang France = {r['rank']} | p-valeur = {r['p_value']}")

    return {
        'df_emissions':              df_emissions,
        'france_synth':              france_synth,
        'france_synth_past':         france_synth_past,
        'france_gap':                france_gap,
        'placebos_space':            placebos_space,
        'valid_units':               valid_units,
        'ratios_series':             ratios_series,
        'pre_rmse':                  pre_rmse,
        'p_value':                   p_val,
        'time_permutation':          time_perm,
        'time_permutation_no_covid': time_perm_no_covid,
        'leave_one_out':             loo,
        'mspe_sensitivity':          mspe_sensitivity,
        'avg_gap_post':              avg_gap_post,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 5. VISUALISATION
# ──────────────────────────────────────────────────────────────────────────────

def plot_results(results: dict, suffix: str = "") -> None:
    """Génère et sauvegarde les deux figures SCM dans outputs/figures/.

    `suffix` (ex. "_predictors") différencie les figures d'une variante
    d'estimation alternative de celles du run outcome-only par défaut,
    pour éviter d'écraser les figures du jour si les deux tournent le
    même jour.
    """
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y%m%d")

    df_emissions      = results['df_emissions']
    france_synth      = results['france_synth']
    france_synth_past = results['france_synth_past']
    france_gap        = results['france_gap']
    placebos_space    = results['placebos_space']
    valid_units       = results['valid_units']
    ratios_series     = results['ratios_series']

    # ── Figure 1 : Grid 2×2 ──
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(f"SCM — Impact CCE 2014 sur les émissions GES transport (France)\n"
                 f"p-valeur (pays) = {results['p_value']:.3f} | "
                 f"p-valeur (temps) = {results['time_permutation']['p_value']:.3f} | "
                 f"RMSE pré = {results['pre_rmse']:.4f}",
                 fontsize=13, y=1.01)

    # A. Trajectoire réelle vs synthétique
    axes[0, 0].plot(df_emissions.index, df_emissions[TREATED_UNIT],
                    label="France (réelle)", lw=2)
    axes[0, 0].plot(df_emissions.index, france_synth,
                    label="France (synthétique)", ls="--", lw=2)
    axes[0, 0].axvline(TREATMENT_YEAR, color="black", ls=":", lw=1.5,
                        label=f"CCE {TREATMENT_YEAR}")
    axes[0, 0].set_title("A. SCM : France vs France Synthétique (Log-Log)")
    axes[0, 0].set_ylabel("log(Émissions GES transport)")
    axes[0, 0].legend()

    # B. Placebo in-time
    axes[0, 1].plot(df_emissions.index, df_emissions[TREATED_UNIT],
                    label="France (réelle)", lw=2)
    axes[0, 1].plot(df_emissions.index, france_synth_past,
                    label=f"Placebo Synthétique ({PLACEBO_YEAR})", ls="--", color="gray")
    axes[0, 1].axvline(PLACEBO_YEAR, color="red", ls=":",
                        label=f"Faux traitement {PLACEBO_YEAR}")
    axes[0, 1].set_title(f"B. Placebo In-Time (faux traitement {PLACEBO_YEAR})")
    axes[0, 1].set_ylabel("log(Émissions GES transport)")
    axes[0, 1].legend()

    # C. Placebo in-space (spaghetti plot)
    for unit in valid_units:
        gap = placebos_space[unit]
        is_fr = (unit == TREATED_UNIT)
        axes[1, 0].plot(df_emissions.index, gap,
                        color="blue" if is_fr else "lightgrey",
                        alpha=1.0 if is_fr else 0.5,
                        lw=3 if is_fr else 1,
                        label="France" if is_fr else None)
    axes[1, 0].axvline(TREATMENT_YEAR, color="black", ls=":", lw=1.5)
    axes[1, 0].axhline(0, color="black", lw=1)
    axes[1, 0].set_title(f"C. Placebo In-Space — {len(valid_units)} unités valides (bande MSPE ×{MSPE_THRESHOLD} / ÷{MSPE_THRESHOLD})")
    axes[1, 0].set_ylabel("Log-Gap (France − Synthétique)")
    axes[1, 0].legend()

    # D. Ratio MSPE
    colors = ['#1f77b4' if x == TREATED_UNIT else '#aec7e8' for x in ratios_series.index]
    ratios_series.plot(kind='barh', ax=axes[1, 1], color=colors)
    axes[1, 1].set_title("D. Ratio MSPE post/pré (significativité relative)")
    axes[1, 1].set_xlabel("Ratio MSPE (post / pré)")

    plt.tight_layout()
    path_grid = FIGURES_DIR / f"scm_results{suffix}_{today}.png"
    fig.savefig(path_grid, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"   Figure 1 sauvegardée : {path_grid}")

    # ── Figure 2 : Gap plot final ──
    fig2, ax = plt.subplots(figsize=(10, 6))
    ax.plot(france_gap.index, france_gap.values,
            label="France — Effet net (Log-Gap)", lw=2, color="purple")
    ax.axvline(TREATMENT_YEAR, color="black", ls=":", lw=2,
               label=f"Mise en œuvre CCE ({TREATMENT_YEAR})")
    ax.axhline(0, color="black", lw=1.5, alpha=0.6)

    gap_post = france_gap[france_gap.index >= TREATMENT_YEAR]
    ax.fill_between(gap_post.index, gap_post.values, 0,
                    alpha=0.12, color="purple", label="Zone d'effet post-CCE")

    ax.set_title("France — Effet CCE 2014 sur les émissions GES transport\n"
                 f"Contrôle Synthétique (Log-Gap Plot)")
    ax.set_ylabel("Log-Gap  ≈  % d'impact sur les émissions")
    ax.set_xlabel("Année")
    ax.legend()
    ax.grid(alpha=0.3)
    fig2.text(0.12, 0.01,
              f"Note : Un gap de −0.10 correspond à une baisse d'environ 10% des émissions. "
              f"p-valeur (pays) = {results['p_value']:.3f} | "
              f"p-valeur (temps) = {results['time_permutation']['p_value']:.3f} | "
              f"p-valeur (temps, hors COVID) = {results['time_permutation_no_covid']['p_value']:.3f}.",
              fontsize=9, style='italic', color='gray')

    path_gap = FIGURES_DIR / f"scm_gap{suffix}_{today}.png"
    fig2.savefig(path_gap, dpi=150, bbox_inches='tight')
    plt.close(fig2)
    print(f"   Figure 2 sauvegardée : {path_gap}")


# ──────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ──────────────────────────────────────────────────────────────────────────────

def main() -> dict:
    print(f"\n{'='*60}")
    print("STAGE 3 — Estimation SCM & tests de robustesse")
    print(f"{'='*60}")

    df_panel = load_target_panel_full_pool(
        MASTER_DATASET_PATH, PAYS_CIBLES, TARGET_VAR, TRAIN_START, PANEL_END,
        extra_pays_filepath=OECD_EXTRA_PATH
    )
    results = run_scm(df_panel)
    plot_results(results)

    print(f"\n{'─'*60}")
    print("STAGE 3bis — Variante SCM augmenté (prédicteurs structurels)")
    print(f"{'─'*60}")
    data_by_var, valid_countries = load_predictor_augmented_data(
        MASTER_DATASET_PATH, PAYS_CIBLES, TARGET_VAR, PREDICTOR_VARS,
        TRAIN_START, PANEL_END
    )
    results_augmented = run_scm_predictor_augmented(
        data_by_var, valid_countries, TARGET_VAR, PREDICTOR_VARS
    )
    plot_results(results_augmented, suffix="_predictors")

    print(f"\n✅ Stage 3 terminé.")
    return {'outcome_only': results, 'predictor_augmented': results_augmented}


if __name__ == "__main__":
    main()

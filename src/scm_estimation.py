"""
src/scm_estimation.py — Stage 3 : Estimation SCM + tests de robustesse
=======================================================================
Entrée  : Data/processed/optimal_joint_panel.csv
Sorties : outputs/figures/scm_results_YYYYMMDD.png
          outputs/figures/scm_gap_YYYYMMDD.png

Transformations : Log-Log systématique sur toutes les variables continues
                  (exception : nrg_ind_ren déjà en %)
Tests inclus    : Placebo in-space, Placebo in-time (2010), filtre MSPE (3×)
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date
from scipy.optimize import minimize

from config import (
    TREATED_UNIT, TARGET_VAR, TREATMENT_YEAR, PLACEBO_YEAR,
    TRAIN_START, TRAIN_END, PANEL_END, MSPE_THRESHOLD,
    OPTIMAL_PANEL_PATH, FIGURES_DIR
)


# ──────────────────────────────────────────────────────────────────────────────
# 1. CHARGEMENT ET TRANSFORMATION LOG-LOG
# ──────────────────────────────────────────────────────────────────────────────

def load_panel(filepath) -> pd.DataFrame:
    """Charge le panel et applique la transformation log-log."""
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


# ──────────────────────────────────────────────────────────────────────────────
# 3. CALCUL MSPE
# ──────────────────────────────────────────────────────────────────────────────

def calculate_mspe(unit_gap: np.ndarray, t_year: int,
                   years: pd.Index, pre_or_post: str = 'pre') -> float:
    if pre_or_post == 'pre':
        return float(np.mean(unit_gap[years < t_year] ** 2))
    return float(np.mean(unit_gap[years >= t_year] ** 2))


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

    # ── Filtre MSPE ──
    mspe_pre_all = {
        u: calculate_mspe(g, TREATMENT_YEAR, df_emissions.index, 'pre')
        for u, g in placebos_space.items()
    }
    threshold = mspe_pre_all[TREATED_UNIT] * MSPE_THRESHOLD
    valid_units = [u for u, e in mspe_pre_all.items() if e <= threshold]

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
    print(f"   Rang France / {len(valid_units)} unités valides → p-valeur empirique : {p_val:.3f}")
    avg_gap_post = france_gap[france_gap.index >= TREATMENT_YEAR].mean()
    print(f"   Gap moyen post-2014 : {avg_gap_post:.3f} log-points "
          f"(≈ {avg_gap_post * 100:.1f}% d'impact)")

    return {
        'df_emissions':        df_emissions,
        'france_synth':        france_synth,
        'france_synth_past':   france_synth_past,
        'france_gap':          france_gap,
        'placebos_space':      placebos_space,
        'valid_units':         valid_units,
        'ratios_series':       ratios_series,
        'pre_rmse':            pre_rmse,
        'p_value':             p_val,
        'avg_gap_post':        avg_gap_post,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 5. VISUALISATION
# ──────────────────────────────────────────────────────────────────────────────

def plot_results(results: dict) -> None:
    """Génère et sauvegarde les deux figures SCM dans outputs/figures/."""
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
                 f"p-valeur empirique = {results['p_value']:.3f} | "
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
    axes[1, 0].set_title(f"C. Placebo In-Space — {len(valid_units)} unités valides (filtre MSPE ×{MSPE_THRESHOLD})")
    axes[1, 0].set_ylabel("Log-Gap (France − Synthétique)")
    axes[1, 0].legend()

    # D. Ratio MSPE
    colors = ['#1f77b4' if x == TREATED_UNIT else '#aec7e8' for x in ratios_series.index]
    ratios_series.plot(kind='barh', ax=axes[1, 1], color=colors)
    axes[1, 1].set_title("D. Ratio MSPE post/pré (significativité relative)")
    axes[1, 1].set_xlabel("Ratio MSPE (post / pré)")

    plt.tight_layout()
    path_grid = FIGURES_DIR / f"scm_results_{today}.png"
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
              f"p-valeur empirique = {results['p_value']:.3f}.",
              fontsize=9, style='italic', color='gray')

    path_gap = FIGURES_DIR / f"scm_gap_{today}.png"
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

    df_panel = load_panel(OPTIMAL_PANEL_PATH)
    results = run_scm(df_panel)
    plot_results(results)

    print(f"\n✅ Stage 3 terminé.")
    return results


if __name__ == "__main__":
    main()

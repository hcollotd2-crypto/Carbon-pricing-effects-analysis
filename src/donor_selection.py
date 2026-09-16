"""
src/donor_selection.py — Stage 2 : Sélection optimale du donor pool (SCM)
==========================================================================
Algorithme d'optimisation alternée (moteurs A et B) :
  - Moteur A : forward_select_donors  — sélection greedy des pays
  - Moteur B : forward_select_predictors — sélection greedy des prédicteurs
Produit : Data/processed/optimal_joint_panel.csv
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from config import (
    TREATED_UNIT, TARGET_VAR,
    TRAIN_END, VAL_END, PANEL_END, TRAIN_START,
    MIN_DONORS, MIN_PREDICTORS, MAX_ITER,
    MASTER_DATASET_PATH, OPTIMAL_PANEL_PATH, DATA_PROCESSED_DIR
)


# ──────────────────────────────────────────────────────────────────────────────
# 1. CHARGEMENT ET OUTILS
# ──────────────────────────────────────────────────────────────────────────────

def load_and_melt(filepath) -> pd.DataFrame:
    """Charge le master dataset et le passe en format long avec interpolation."""
    df_raw = pd.read_csv(filepath)
    df_long = df_raw.melt(id_vars=['geo', 'variable'], var_name='year', value_name='value')
    df_long['year'] = df_long['year'].astype(int)

    df_long['value'] = df_long.groupby(['geo', 'variable'])['value'].transform(
        lambda x: x.interpolate(method='linear', limit_direction='both')
    )
    return df_long


def get_w_subset(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Calcule les poids W minimisant le RMSE sous contraintes SCM (simplex)."""
    n_donors = X.shape[1]
    if n_donors == 0:
        return np.array([])
    w_init = np.ones(n_donors) / n_donors

    def loss_w(W, X, y):
        return np.sqrt(np.mean((y - X @ W) ** 2))

    cons = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
    bounds = [(0, 1)] * n_donors
    res = minimize(loss_w, w_init, args=(X, y), method='SLSQP',
                   bounds=bounds, constraints=cons)
    return res.x


def build_matrices(df_long: pd.DataFrame, treated_unit: str, donors: list,
                   target_var: str, predictors: list, end_year: int):
    """Construit les matrices X et y empilées pour l'entraînement."""
    X_stack, y_stack = [], []
    for var in [target_var] + predictors:
        df_v = df_long[df_long['variable'] == var].pivot(
            index='year', columns='geo', values='value'
        )
        df_tr = df_v.loc[df_v.index <= end_year]
        X_stack.append(df_tr[donors].values)
        y_stack.append(df_tr[treated_unit].values)
    return np.vstack(X_stack), np.concatenate(y_stack)


def evaluate_validation_error(df_long: pd.DataFrame, treated_unit: str,
                               donors: list, target_var: str,
                               W: np.ndarray, train_end: int, val_end: int) -> float:
    """RMSE sur la variable cible durant la fenêtre de validation."""
    df_target = df_long[df_long['variable'] == target_var].pivot(
        index='year', columns='geo', values='value'
    )
    df_val = df_target.loc[(df_target.index > train_end) & (df_target.index <= val_end)]
    y_val = df_val[treated_unit].values
    X_val = df_val[donors].values
    return np.sqrt(np.mean((y_val - X_val @ W) ** 2))


def _has_missing_data(df_long: pd.DataFrame, variables: list,
                      units: list, train_end: int) -> bool:
    """Retourne True si une variable/unité a des NaN sur la période d'entraînement."""
    for var in variables:
        df_v = df_long[df_long['variable'] == var].pivot(
            index='year', columns='geo', values='value'
        )
        df_tr = df_v.loc[df_v.index <= train_end]
        missing_cols = [c for c in units if c not in df_tr.columns]
        if missing_cols or df_tr[units].isna().any().any():
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# 2. MOTEURS DE SÉLECTION
# ──────────────────────────────────────────────────────────────────────────────

def forward_select_donors(df_long: pd.DataFrame, treated_unit: str,
                          potential_donors: list, target_var: str,
                          current_predictors: list, train_end: int,
                          val_end: int, min_donors: int = MIN_DONORS) -> list:
    """Moteur A — sélection greedy des pays donateurs."""
    selected = []
    remaining = list(potential_donors)
    best_val_loss = float('inf')

    while remaining:
        best_candidate, best_loss = None, float('inf')

        for donor in remaining:
            pool = selected + [donor]
            if _has_missing_data(df_long, [target_var] + current_predictors,
                                  pool + [treated_unit], train_end):
                continue

            X_train, y_train = build_matrices(
                df_long, treated_unit, pool, target_var, current_predictors, train_end
            )
            W_train = get_w_subset(X_train, y_train)
            val_loss = evaluate_validation_error(
                df_long, treated_unit, pool, target_var, W_train, train_end, val_end
            )
            if val_loss < best_loss:
                best_loss, best_candidate = val_loss, donor

        if best_candidate and (best_loss < best_val_loss or len(selected) < min_donors):
            selected.append(best_candidate)
            remaining.remove(best_candidate)
            best_val_loss = best_loss
            print(f"      + Pays : {best_candidate}  (RMSE val = {best_val_loss:.4f})")
        else:
            break

    return selected


def forward_select_predictors(df_long: pd.DataFrame, treated_unit: str,
                               current_donors: list, target_var: str,
                               potential_predictors: list, train_end: int,
                               val_end: int, min_predictors: int = MIN_PREDICTORS) -> list:
    """Moteur B — sélection greedy des prédicteurs."""
    selected = []
    remaining = list(potential_predictors)
    best_val_loss = float('inf')

    while remaining:
        best_candidate, best_loss = None, float('inf')

        for pred in remaining:
            preds_to_test = selected + [pred]
            if _has_missing_data(df_long, [target_var] + preds_to_test,
                                  current_donors + [treated_unit], train_end):
                continue

            X_train, y_train = build_matrices(
                df_long, treated_unit, current_donors, target_var, preds_to_test, train_end
            )
            W_train = get_w_subset(X_train, y_train)
            val_loss = evaluate_validation_error(
                df_long, treated_unit, current_donors, target_var, W_train, train_end, val_end
            )
            if val_loss < best_loss:
                best_loss, best_candidate = val_loss, pred

        if best_candidate and (best_loss < best_val_loss or len(selected) < min_predictors):
            selected.append(best_candidate)
            remaining.remove(best_candidate)
            best_val_loss = best_loss
            print(f"      + Prédicteur : {best_candidate}  (RMSE val = {best_val_loss:.4f})")
        else:
            break

    return selected


# ──────────────────────────────────────────────────────────────────────────────
# 3. ALGORITHME D'OPTIMISATION ALTERNÉE
# ──────────────────────────────────────────────────────────────────────────────

def joint_optimization(df_long: pd.DataFrame, treated_unit: str = TREATED_UNIT,
                       target_var: str = TARGET_VAR, max_iter: int = MAX_ITER,
                       train_end: int = TRAIN_END, val_end: int = VAL_END,
                       min_donors: int = MIN_DONORS,
                       min_predictors: int = MIN_PREDICTORS) -> tuple:
    """Boucle d'optimisation alternée pays ↔ prédicteurs."""
    print(f"\n{'='*60}")
    print(f"STAGE 2 — Optimisation alternée pour {treated_unit}")
    print(f"{'='*60}")

    all_donors = [c for c in df_long['geo'].unique() if c != treated_unit]
    all_predictors = [v for v in df_long['variable'].unique() if v != target_var]

    current_predictors: list = []
    current_donors: list = []

    for iteration in range(1, max_iter + 1):
        print(f"\n  Boucle {iteration}/{max_iter}")
        old_donors = current_donors.copy()
        old_predictors = current_predictors.copy()

        print("  [A] Sélection des pays...")
        current_donors = forward_select_donors(
            df_long, treated_unit, all_donors, target_var,
            current_predictors, train_end, val_end, min_donors
        )
        print(f"      Pays retenus ({len(current_donors)}) : {current_donors}")

        print("\n  [B] Sélection des prédicteurs...")
        current_predictors = forward_select_predictors(
            df_long, treated_unit, current_donors, target_var,
            all_predictors, train_end, val_end, min_predictors
        )
        print(f"      Prédicteurs retenus ({len(current_predictors)}) : {current_predictors}")

        if (set(current_donors) == set(old_donors)
                and set(current_predictors) == set(old_predictors)):
            print("\n✅ Convergence atteinte.")
            break

    return current_donors, current_predictors


# ──────────────────────────────────────────────────────────────────────────────
# 4. EXPORT DU PANEL OPTIMAL
# ──────────────────────────────────────────────────────────────────────────────

def build_and_export_panel(df_long: pd.DataFrame, treated_unit: str,
                            target_var: str, donors: list,
                            predictors: list) -> pd.DataFrame:
    """Construit et exporte le panel optimal (format wide, log non appliqué ici)."""
    pays_sel = [treated_unit] + donors
    vars_sel = [target_var] + predictors

    df_final = df_long[
        df_long['geo'].isin(pays_sel) & df_long['variable'].isin(vars_sel)
    ]
    df_panel = df_final.pivot(
        index=['geo', 'year'], columns='variable', values='value'
    ).reset_index()
    df_panel.columns.name = None
    df_panel = (df_panel[(df_panel['year'] >= TRAIN_START) & (df_panel['year'] <= PANEL_END)]
                .sort_values(by=['geo', 'year']))

    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df_panel.to_csv(OPTIMAL_PANEL_PATH, index=False)
    print(f"\n💾 Panel exporté : {OPTIMAL_PANEL_PATH}")
    return df_panel


# ──────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ──────────────────────────────────────────────────────────────────────────────

def main():
    df_long = load_and_melt(MASTER_DATASET_PATH)

    final_donors, final_predictors = joint_optimization(df_long)

    df_panel = build_and_export_panel(
        df_long, TREATED_UNIT, TARGET_VAR, final_donors, final_predictors
    )
    return df_panel


if __name__ == "__main__":
    main()

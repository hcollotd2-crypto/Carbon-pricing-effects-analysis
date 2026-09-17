"""
src/timesfm_imputation.py — Stage optionnel : Imputation TimesFM du Master Dataset
====================================================================================
Entrée  : Data/processed/master_dataset_final_scm.csv (Stage 1, avec trous)
Sortie  : Data/processed/master_dataset_final_scm.csv (écrasé, complété)
          Data/processed/archive/master_dataset_final_scm_pre_timesfm_YYYYMMDD.csv
          Data/processed/imputation_report.csv

Remplace le flat-fill des bords (pandas interpolate(..., limit_direction='both'),
qui prolonge la première/dernière valeur connue à plat) par une extrapolation
zero-shot via TimesFM 2.5 (Google), pour chaque série (geo, variable) :
  - trous internes (entourés de valeurs connues)      → interpolation linéaire
  - trous en fin de série (millésimes pas encore publiés) → forecast avant (TimesFM)
  - trous en début de série (avant le début de la mesure) → forecast arrière
    (série inversée, forecast avant, ré-inversion)
  - séries entièrement vides (EL/SK road_eqs_carmot)  → laissées en NaN
    (rien à extrapoler à partir de zéro point)

Stage 2 (donor_selection) et Stage 3 (scm_estimation) ré-appliquent chacun leur
propre interpolate(..., limit_direction='both') par sécurité sur ce qui reste —
ce stage réduit simplement à quasi zéro ce qui leur reste à flat-fill,
notamment sur TARGET_VAR (env_air_gge) directement consommé par le Stage 3.

Environnement dédié requis (voir scripts/setup_timesfm_env.sh) :
  .venv-timesfm/bin/python src/timesfm_imputation.py
Incompatible avec le .venv principal du pipeline : torch n'a plus de wheel
macOS x86_64 au-delà de la 2.2.2, et cette version bride numpy à <2 — un
conflit avec les autres dépendances du pipeline sous le Python de .venv/.

Note technique — bug scaled_dot_product_attention sur torch 2.2.2 :
Sur torch 2.2.2 (la dernière version disponible pour macOS x86_64 — Apple a
cessé de publier des wheels Intel après cette release), F.scaled_dot_product_
attention renvoie NaN pour toute ligne de requête entièrement masquée (un
contexte court complété par du padding dans un batch), un bug corrigé dans
les versions torch ultérieures mais indisponibles sur cette architecture.
_safe_sdpa ci-dessous le contourne par un softmax manuel équivalent qui met
à zéro les lignes NaN au lieu de les laisser se propager dans le réseau.
"""

import math
import shutil
from datetime import date

import numpy as np
import pandas as pd

from config import (
    MASTER_DATASET_PATH, DATA_ARCHIVE_DIR, IMPUTATION_REPORT_PATH
)

try:
    import torch
    import torch.nn.functional as F
except ImportError as exc:
    raise ImportError(
        "torch n'est pas installé dans cet interpréteur. Ce stage nécessite "
        "l'environnement dédié : exécute d'abord scripts/setup_timesfm_env.sh, "
        "puis lance ce script avec .venv-timesfm/bin/python."
    ) from exc


def _safe_sdpa(query, key, value, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None, **kwargs):
    """Remplacement NaN-safe de F.scaled_dot_product_attention (voir docstring module)."""
    d = query.shape[-1]
    s = scale if scale is not None else 1.0 / math.sqrt(d)
    attn = torch.matmul(query, key.transpose(-2, -1)) * s
    if attn_mask is not None:
        if attn_mask.dtype == torch.bool:
            attn = attn.masked_fill(~attn_mask, torch.finfo(attn.dtype).min)
        else:
            attn = attn + attn_mask
    attn = torch.softmax(attn, dim=-1)
    attn = torch.nan_to_num(attn, nan=0.0)
    return torch.matmul(attn, value)


F.scaled_dot_product_attention = _safe_sdpa

import timesfm  # noqa: E402 (doit suivre le monkeypatch ci-dessus)


# ──────────────────────────────────────────────────────────────────────────────
# IMPUTATION PAR SÉRIE
# ──────────────────────────────────────────────────────────────────────────────

def _prepare_requests(df: pd.DataFrame, year_cols: list) -> tuple:
    """Interpole les trous internes en place et construit les requêtes de
    forecast avant (trailing) / arrière (leading) pour TimesFM.
    """
    n_years = len(year_cols)
    filled = df.copy()
    report_rows = []
    forward_reqs, backward_reqs = [], []

    for i, row in df.iterrows():
        vals = row[year_cols].to_numpy(dtype=float, copy=True)
        isnan = np.isnan(vals)
        if not isnan.any():
            continue

        idx = np.where(~isnan)[0]
        if len(idx) == 0:
            report_rows.append(dict(geo=row["geo"], variable=row["variable"],
                                     action="ignoré (série entièrement vide)",
                                     n_leading=n_years, n_trailing=0, n_interior_interp=0))
            continue

        first, last = idx[0], idx[-1]
        n_leading = int(first)
        n_trailing = int(n_years - 1 - last)

        interior_mask = isnan[first:last + 1]
        n_interior = int(interior_mask.sum())
        if n_interior > 0:
            seg = pd.Series(vals[first:last + 1]).interpolate(method="linear")
            vals[first:last + 1] = seg.to_numpy()

        filled.loc[i, year_cols] = vals

        context = vals[first:last + 1].copy()
        if n_trailing > 0:
            forward_reqs.append((i, context, n_trailing))
        if n_leading > 0:
            backward_reqs.append((i, context[::-1].copy(), n_leading))

        parts = []
        if n_interior:
            parts.append(f"interpolation linéaire ({n_interior} pt)")
        if n_trailing:
            parts.append(f"forecast avant TimesFM ({n_trailing} pt)")
        if n_leading:
            parts.append(f"forecast arrière TimesFM ({n_leading} pt)")
        report_rows.append(dict(geo=row["geo"], variable=row["variable"],
                                 action=" + ".join(parts),
                                 n_leading=n_leading, n_trailing=n_trailing,
                                 n_interior_interp=n_interior))

    return filled, report_rows, forward_reqs, backward_reqs


def _run_timesfm(filled: pd.DataFrame, year_cols: list,
                  forward_reqs: list, backward_reqs: list) -> pd.DataFrame:
    """Charge TimesFM 2.5 et complète les trous de bord (avant/arrière) par batch."""
    n_years = len(year_cols)
    torch.set_float32_matmul_precision("high")

    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
        "google/timesfm-2.5-200m-pytorch", torch_compile=False
    )
    model.compile(timesfm.ForecastConfig(
        max_context=1024,
        max_horizon=256,
        normalize_inputs=True,
        use_continuous_quantile_head=True,
        force_flip_invariance=True,
        infer_is_positive=True,
        fix_quantile_crossing=True,
    ))

    if forward_reqs:
        horizon = max(h for _, _, h in forward_reqs)
        inputs = [c for _, c, _ in forward_reqs]
        point, _ = model.forecast(horizon=horizon, inputs=inputs)
        for (i, _, h), p in zip(forward_reqs, point):
            vals = filled.loc[i, year_cols].to_numpy(dtype=float, copy=True)
            vals[n_years - h:] = p[:h]
            filled.loc[i, year_cols] = vals

    if backward_reqs:
        horizon = max(h for _, _, h in backward_reqs)
        inputs = [c for _, c, _ in backward_reqs]
        point, _ = model.forecast(horizon=horizon, inputs=inputs)
        for (i, _, h), p in zip(backward_reqs, point):
            vals = filled.loc[i, year_cols].to_numpy(dtype=float, copy=True)
            vals[:h] = p[:h][::-1]
            filled.loc[i, year_cols] = vals

    return filled


# ──────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ──────────────────────────────────────────────────────────────────────────────

def main() -> pd.DataFrame:
    print("\n" + "=" * 60)
    print("STAGE OPTIONNEL — Imputation TimesFM du Master Dataset")
    print("=" * 60)

    df = pd.read_csv(MASTER_DATASET_PATH)
    year_cols = sorted([c for c in df.columns if c.isdigit()], key=int)

    n_missing_before = int(df[year_cols].isna().sum().sum())
    print(f"   Cellules manquantes avant imputation : {n_missing_before}")

    DATA_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = DATA_ARCHIVE_DIR / f"master_dataset_final_scm_pre_timesfm_{date.today():%Y%m%d}.csv"
    shutil.copy2(MASTER_DATASET_PATH, backup_path)
    print(f"   [Backup] Version pré-imputation archivée → {backup_path}")

    filled, report_rows, forward_reqs, backward_reqs = _prepare_requests(df, year_cols)
    print(f"   Séries à compléter en avant (trailing) : {len(forward_reqs)}")
    print(f"   Séries à compléter en arrière (leading) : {len(backward_reqs)}")

    if forward_reqs or backward_reqs:
        print("   [TimesFM] Chargement du modèle google/timesfm-2.5-200m-pytorch...")
        filled = _run_timesfm(filled, year_cols, forward_reqs, backward_reqs)

    n_missing_after = int(filled[year_cols].isna().sum().sum())

    filled.to_csv(MASTER_DATASET_PATH, index=False)
    pd.DataFrame(report_rows).to_csv(IMPUTATION_REPORT_PATH, index=False)

    print(f"\n✅ Master dataset complété → {MASTER_DATASET_PATH}")
    print(f"   Rapport détaillé          → {IMPUTATION_REPORT_PATH}")
    print(f"   Cellules manquantes restantes : {n_missing_after} "
          f"(séries sans aucun point de départ, non extrapolables)")

    return filled


if __name__ == "__main__":
    main()

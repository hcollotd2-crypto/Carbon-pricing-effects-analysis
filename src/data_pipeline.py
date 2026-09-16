"""
src/data_pipeline.py — Stage 1 : Ingestion et construction du Master Dataset
=============================================================================
Télécharge les données Eurostat via API et traite le Weekly Oil Bulletin.
Produit : Data/processed/master_dataset_final_scm.csv
"""

import gc
import eurostat
import pandas as pd

from config import (
    PAYS_CIBLES, ANNEE_MIN, FILTRES_EUROSTAT, CODES_EUROSTAT,
    FICHIER_OIL, MASTER_DATASET_PATH, DATA_PROCESSED_DIR
)


# ──────────────────────────────────────────────────────────────────────────────
# FONCTIONS UTILITAIRES
# ──────────────────────────────────────────────────────────────────────────────

def numeriser_annees(df: pd.DataFrame) -> pd.DataFrame:
    """Convertit le contenu et les noms des colonnes d'années en format numérique."""
    cols_annees = [col for col in df.columns if str(col).isdigit()]
    df[cols_annees] = df[cols_annees].apply(pd.to_numeric, errors='coerce')
    df.rename(columns={col: int(col) for col in cols_annees}, inplace=True)
    return df


def filtrer_annees(df: pd.DataFrame) -> pd.DataFrame:
    """Ne conserve que les colonnes geo, variable et les années >= ANNEE_MIN."""
    cols_identifiants = ['geo', 'variable']
    cols_annees = [col for col in df.columns if str(col).isdigit() and int(col) >= ANNEE_MIN]
    return df[cols_identifiants + cols_annees].copy()


# ──────────────────────────────────────────────────────────────────────────────
# TRAITEMENT PAR SOURCE
# ──────────────────────────────────────────────────────────────────────────────

def traiter_eurostat(codes: list, pays: list) -> pd.DataFrame:
    """Télécharge, filtre et assemble les données Eurostat via API."""
    dfs_a_empiler = []

    for code in codes:
        print(f"   [Eurostat] Importation : {code}")
        df = eurostat.get_data_df(code, flags=False)

        if 'geo\\TIME_PERIOD' not in df.columns:
            print(f"   [Eurostat] Colonne geo absente pour {code} — ignoré.")
            continue

        df = df.rename(columns={'geo\\TIME_PERIOD': 'geo'})
        df = df[df['geo'].isin(pays)].copy()

        if code in FILTRES_EUROSTAT:
            df = FILTRES_EUROSTAT[code](df)

        cols_a_garder = ['geo'] + [c for c in df.columns if str(c).isdigit()]
        df = df[cols_a_garder].copy()
        df.insert(1, 'variable', code)
        dfs_a_empiler.append(df)

    master_df = pd.concat(dfs_a_empiler, ignore_index=True)

    # Suppression des colonnes avec >50% de NaN
    seuil_valides = len(master_df) * 0.5
    master_df = master_df.dropna(axis=1, thresh=seuil_valides)

    return filtrer_annees(master_df)


def traiter_oil(filepath, pays: list) -> pd.DataFrame:
    """Traite le fichier Excel du Weekly Oil Bulletin (prix diesel HT annualisé)."""
    print("   [Oil] Traitement Weekly Oil Bulletin...")
    df_raw = pd.read_excel(filepath, sheet_name="Prices wo taxes")
    df = df_raw.dropna(axis=1, how='all').copy()

    col_date = df.columns[0]
    cols_pertinentes = [col_date] + [
        c for c in df.columns
        if any(f"{p}_" in str(c) for p in pays) and 'diesel' in str(c).lower()
    ]
    df = df[cols_pertinentes].rename(columns={col_date: 'Date'})

    df['Date'] = pd.to_datetime(df['Date'], format='%d/%m/%Y', errors='coerce')
    df['year'] = df['Date'].dt.year

    cols_prix = [c for c in df.columns if c not in ['Date', 'year']]
    for c in cols_prix:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', '.'), errors='coerce')

    df_annuel = df.groupby('year')[cols_prix].mean().reset_index().dropna(subset=['year'])
    df_annuel['year'] = df_annuel['year'].astype(int)

    df_long = df_annuel.melt(id_vars=['year'], var_name='nom_colonne', value_name='value')
    df_long['geo'] = df_long['nom_colonne'].str[:2]
    df_long = df_long[df_long['geo'].isin(pays)].copy()
    df_long['variable'] = 'diesel_price_ht'

    df_wide = df_long.pivot(index=['geo', 'variable'], columns='year', values='value').reset_index()
    df_wide.columns.name = None
    df_wide.columns = [str(c) for c in df_wide.columns]

    return filtrer_annees(df_wide)


# ──────────────────────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────────

def main() -> pd.DataFrame:
    print("\n" + "="*60)
    print("STAGE 1 — Pipeline de données SCM")
    print("="*60)

    # 1. Collecte
    df_eurostat = traiter_eurostat(CODES_EUROSTAT, PAYS_CIBLES)
    df_oil = traiter_oil(FICHIER_OIL, PAYS_CIBLES)

    # 2. Sécurisation numérique
    df_eurostat = numeriser_annees(df_eurostat)
    df_oil = numeriser_annees(df_oil)

    # 3. Fusion
    print("   [Fusion] Assemblage du Master Dataset...")
    master_dataset = pd.concat([df_eurostat, df_oil], ignore_index=True)

    # 4. Gestion des doublons de variables (ex: sdg_07_30_1, sdg_07_30_2)
    doublons = master_dataset.duplicated(subset=['geo', 'variable'], keep=False)
    if doublons.any():
        print("   [Fusion] Renommage des variables en double...")
        compteur = master_dataset.groupby(['geo', 'variable']).cumcount() + 1
        master_dataset.loc[doublons, 'variable'] = (
            master_dataset['variable'] + '_' + compteur.astype(str)
        )

    master_dataset.sort_values(by=['geo', 'variable'], inplace=True)
    master_dataset.reset_index(drop=True, inplace=True)

    # 5. Export
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    master_dataset.to_csv(MASTER_DATASET_PATH, index=False)
    print(f"\n✅ Stage 1 terminé — fichier exporté : {MASTER_DATASET_PATH}")
    print(master_dataset.head(5).to_string())

    return master_dataset


if __name__ == "__main__":
    df = main()
    gc.collect()

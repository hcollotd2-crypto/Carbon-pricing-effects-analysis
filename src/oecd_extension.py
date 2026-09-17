"""
src/oecd_extension.py — Extension optionnelle : émissions transport hors UE
=============================================================================
Récupère env_air_gge (GES transport, CRF 1.A.3) pour des pays OCDE hors UE
via l'UNFCCC GHG Data Interface (package `unfccc-di-api`, ZenodoReader —
snapshot archivé, l'API live étant bloquée pour les environnements standards,
cf. https://github.com/pik-primap/unfccc_di_api#warning).

Contexte : le leave-one-out du 2026-09-17 a montré que le résultat SCM
dépend entièrement de l'Allemagne au sein des ~20 pays UE candidats, et
qu'aucune repondération (ridge, prédicteurs structurels) ne corrige cette
dépendance à l'intérieur du même échantillon. Le seul levier restant est
d'élargir à des économies non-européennes réellement différentes.

Candidats retenus (risque carbone faible sur 2005-2023, cf. README) :
  US (USA) — pas de tarification carbone fédérale
  TR (Turquie) — aucun dispositif national en vigueur
  IL (Israël) — aucun dispositif national large en vigueur

Limite connue : le snapshot Zenodo s'arrête en 2021 pour ces trois pays
(1990-2021, série annuelle complète sur cette fenêtre) — 2022 et 2023 sont
absents et seront comblés par le même mécanisme de bord (interpolate
limit_direction='both', valeur 2021 reconduite) que le reste du pipeline,
pas par une vraie observation. À documenter dans toute lecture des résultats.

Sortie : Data/raw/unfccc/transport_ghg_non_eu.csv (format wide identique à
master_dataset_final_scm.csv : geo, variable, années) — un snapshot mis en
cache, pas un appel réseau à chaque exécution du pipeline (cf. note sur la
volatilité de l'API live dans data_pipeline.py).
"""

import pandas as pd
import unfccc_di_api

from config import DATA_RAW_DIR, ANNEE_MIN, PANEL_END

# ISO2 (convention du reste du pipeline) -> ISO3 (convention UNFCCC)
OECD_EXTRA_PAYS = {
    'US': 'USA',   # pas de tarification carbone fédérale
    'TR': 'TUR',   # aucun dispositif national en vigueur sur la période
    'IL': 'ISR',   # aucun dispositif national large en vigueur sur la période
}

OUTPUT_PATH = DATA_RAW_DIR / "unfccc" / "transport_ghg_non_eu.csv"


def fetch_transport_ghg(iso2_to_iso3: dict, year_min: int, year_max: int) -> pd.DataFrame:
    """Interroge le snapshot Zenodo UNFCCC pour la catégorie CRF 1.A.3
    Transport (gaz agrégés, total pour la catégorie), au format wide
    (geo, variable, années) compatible avec master_dataset_final_scm.csv.
    """
    reader = unfccc_di_api.ZenodoReader()
    rows = []

    for iso2, iso3 in iso2_to_iso3.items():
        print(f"   [UNFCCC] Récupération : {iso2} ({iso3})")
        df = reader.query(party_code=iso3)
        sub = df[
            (df['category'] == '1.A.3  Transport')
            & (df['gas'] == 'Aggregate GHGs')
            & (df['classification'] == 'Total for category')
        ].copy()
        sub = sub[sub['year'].apply(lambda y: str(y).isdigit())]
        sub['year'] = sub['year'].astype(int)
        sub = sub[(sub['year'] >= year_min) & (sub['year'] <= year_max)]

        row = {'geo': iso2, 'variable': 'env_air_gge'}
        for _, r in sub.iterrows():
            row[str(int(r['year']))] = float(r['numberValue'])
        rows.append(row)

    return pd.DataFrame(rows)


def main() -> pd.DataFrame:
    print("\n" + "=" * 60)
    print("Extension OCDE — émissions transport hors UE (UNFCCC)")
    print("=" * 60)

    df = fetch_transport_ghg(OECD_EXTRA_PAYS, ANNEE_MIN, PANEL_END)

    missing_years = [
        y for y in range(ANNEE_MIN, PANEL_END + 1)
        if str(y) not in df.columns
    ]
    if missing_years:
        print(f"   ⚠️  Années absentes du snapshot Zenodo pour tous les pays : "
              f"{missing_years} — comblées en aval par interpolation de bord, "
              f"pas de vraie observation.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\n✅ Extension OCDE exportée : {OUTPUT_PATH}")
    print(df.to_string())
    return df


if __name__ == "__main__":
    main()

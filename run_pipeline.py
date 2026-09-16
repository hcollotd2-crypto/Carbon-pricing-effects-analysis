"""
run_pipeline.py — Point d'entrée unique du pipeline SCM (CCE 2014)
===================================================================
Orchestre les 3 stages du projet dans l'ordre :

  Stage 1 — data_pipeline.py     : ingestion Eurostat + Oil Bulletin
                                    → Data/processed/master_dataset_final_scm.csv
  Stage 2 — donor_selection.py   : optimisation alternée donor pool
                                    → Data/processed/optimal_joint_panel.csv
  Stage 3 — scm_estimation.py    : estimation SCM + robustesse + figures
                                    → outputs/figures/scm_results_YYYYMMDD.png
                                    → outputs/figures/scm_gap_YYYYMMDD.png

Usage :
  python run_pipeline.py                  # pipeline complet
  python run_pipeline.py --from stage2    # depuis le Stage 2 (données déjà générées)
  python run_pipeline.py --from stage3    # depuis le Stage 3 (panel déjà sélectionné)
  python run_pipeline.py --only stage3    # Stage 3 uniquement
"""

import sys
import time
import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline SCM — Impact CCE 2014 sur les émissions GES transport"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--from', dest='from_stage',
        choices=['stage1', 'stage2', 'stage3'],
        default='stage1',
        help="Démarrer le pipeline à partir du stage indiqué (défaut : stage1)"
    )
    group.add_argument(
        '--only', dest='only_stage',
        choices=['stage1', 'stage2', 'stage3'],
        help="Exécuter un seul stage"
    )
    return parser.parse_args()


def run_stage(label: str, fn):
    """Exécute un stage avec chronomètre et gestion d'erreur."""
    print(f"\n{'─'*60}")
    t0 = time.time()
    try:
        result = fn()
        elapsed = time.time() - t0
        print(f"✅ {label} terminé en {elapsed:.1f}s")
        return result
    except Exception as e:
        print(f"\n❌ Erreur dans {label} : {e}")
        raise


def main():
    args = parse_args()

    # Détermination des stages à exécuter
    if args.only_stage:
        stages_to_run = {args.only_stage}
    else:
        all_stages = ['stage1', 'stage2', 'stage3']
        start_idx = all_stages.index(args.from_stage)
        stages_to_run = set(all_stages[start_idx:])

    print("=" * 60)
    print("  PIPELINE SCM — IMPACT CCE 2014 (France)")
    print("  Contrôle Synthétique | Émissions GES transport")
    print("=" * 60)
    print(f"  Stages à exécuter : {sorted(stages_to_run)}")

    # Import des modules src/ (résolution relative)
    import importlib.util, pathlib
    src_path = pathlib.Path(__file__).parent / "src"
    sys.path.insert(0, str(src_path))
    sys.path.insert(0, str(pathlib.Path(__file__).parent))

    if 'stage1' in stages_to_run:
        from src import data_pipeline
        run_stage("Stage 1 — Data Pipeline", data_pipeline.main)

    if 'stage2' in stages_to_run:
        from src import donor_selection
        run_stage("Stage 2 — Donor Selection", donor_selection.main)

    if 'stage3' in stages_to_run:
        from src import scm_estimation
        run_stage("Stage 3 — SCM Estimation", scm_estimation.main)

    print(f"\n{'='*60}")
    print("  PIPELINE COMPLET ✅")
    print(f"  Graphiques → outputs/figures/")
    print(f"  Données    → Data/processed/")
    print("=" * 60)


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# scripts/setup_timesfm_env.sh — Environnement dédié pour src/timesfm_imputation.py
# =====================================================================================
# Le stage d'imputation TimesFM (torch + le paquet timesfm) ne peut pas cohabiter
# avec le .venv principal du pipeline :
#   - sur macOS x86_64 (Intel), PyTorch n'a plus publié de wheel au-delà de la 2.2.2
#     (versions ultérieures : Apple Silicon uniquement) ;
#   - torch 2.2.2 impose numpy<2, ce qui entrerait en conflit avec les autres
#     dépendances du pipeline sous le Python de .venv/.
# D'où un environnement Python 3.11 séparé, isolé dans .venv-timesfm/.
#
# Usage :
#   bash scripts/setup_timesfm_env.sh
#   python run_pipeline.py --only impute
#
# Sur Apple Silicon ou Linux, des wheels torch plus récents existent : le pin
# torch==2.2.2 ci-dessous peut être relâché (ex : "torch>=2.2") sans le
# contournement _safe_sdpa documenté dans src/timesfm_imputation.py — à vérifier
# au cas par cas si ce script est adapté à une autre machine.

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON311:-python3.11}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "❌ Python 3.11 introuvable (essayé : $PYTHON_BIN)."
    echo "   Installe-le (ex: 'brew install python@3.11') ou passe son chemin via PYTHON311=..."
    exit 1
fi

echo "→ Création de .venv-timesfm avec $($PYTHON_BIN --version)"
"$PYTHON_BIN" -m venv .venv-timesfm

echo "→ Installation des dépendances (requirements-timesfm.txt)..."
.venv-timesfm/bin/pip install --upgrade pip -q
.venv-timesfm/bin/pip install -q -r requirements-timesfm.txt

echo "✅ Environnement prêt. Lance le stage avec :"
echo "   python run_pipeline.py --only impute"

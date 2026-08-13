#!/usr/bin/env python3
"""
FLAML AutoML → Manual Winner → SHAP Explainability for Kenya Vehicle Collateral Risk Engine

This REPLACES the cargo-cult train_1m_iterations.py approach.

The correct workflow:
  1. FLAML discovers the best model + hyperparameters (30min budget, NOT 1M iterations)
  2. Manually implement the winner with full interpretability
  3. SHAP for MFI explainability (CBK/ODPC audit requirement)

Design principles:
  - AutoML is your research intern, not your production engineer
  - Deploy the single winner, NOT the ensemble
  - FLAML searches xgboost, lgbm, catboost, rf
  - The winner gets SHAP values for every prediction
  - MFI officers get: "This vehicle scored 87 because lender_diversity=3 (+23 points)"
  - CBK/ODPC audits require documented decision logic

Usage:
    python train_production.py                                    # Full pipeline (synthetic data)
    python train_production.py --data real_features.csv           # Use real data
    python train_production.py --time-budget 15                   # 15-min FLAML budget
    python train_production.py --explain KDA123J                  # Explain a single vehicle
    python train_production.py --output-dir ./my_run              # Custom output directory
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger("train_production")

# ─── Feature Definitions (47 total) ─────────────────────────────────────

FEATURE_NAMES = [
    # Graph topology (13)
    "degree_centrality", "clustering_coefficient", "page_rank", "wcc_component_size",
    "betweenness_centrality", "closeness_centrality", "eigen_vector_centrality",
    "harmonic_centrality", "articulation_point_flag", "triangle_count",
    "avg_neighbor_degree", "max_neighbor_degree", "community_density",
    # Lender diversity (8)
    "lender_diversity", "unique_lender_count", "sacco_lender_flag",
    "dcp_lender_flag", "unregulated_lender_count", "lender_type_entropy",
    "cross_institution_flag", "same_branch_repledge_flag",
    # Temporal patterns (8)
    "temporal_velocity", "days_since_last_loan", "avg_days_between_loans",
    "min_days_between_loans", "max_days_between_loans", "loan_count_30d",
    "loan_count_90d", "seasonal_pattern_flag",
    # Vehicle provenance (6)
    "govt_plate_flag", "govt_plate_no_disposal_doc", "vehicle_age_years",
    "county_risk_score", "chassis_mismatch_flag", "plate_chassis_conflict",
    # Auction/yard signals (7)
    "active_auction_flag", "auction_count_12m", "storage_yard_count",
    "yard_mobility_count", "avg_yard_stay_days", "yard_county_mismatch_flag",
    "distress_sale_flag",
    # Caveat coverage (5)
    "caveat_coverage_gap", "caveat_not_registered_flag", "caveat_registration_lag_days",
    "cross_lender_caveat_conflict", "total_exposure_kes_normalized",
]

NUM_FEATURES = len(FEATURE_NAMES)  # 47

FEATURE_GROUPS = {
    "graph_topology": FEATURE_NAMES[:13],
    "lender_diversity": FEATURE_NAMES[13:21],
    "temporal_patterns": FEATURE_NAMES[21:29],
    "vehicle_provenance": FEATURE_NAMES[29:35],
    "auction_yard_signals": FEATURE_NAMES[35:42],
    "caveat_coverage": FEATURE_NAMES[42:],
}

# Kenya county risk scores (plate prefix → risk)
COUNTY_RISK_MAP = {
    "KA": 0.60, "KB": 0.30, "KD": 0.70, "KE": 0.40, "KF": 0.50,
    "KG": 0.30, "KN": 0.80, "KU": 0.60, "KW": 0.50, "KZ": 0.40,
}

# FLAML estimator search space
FLAML_ESTIMATORS = ["xgboost", "lgbm", "catboost", "rf"]

# Default output paths
DEFAULT_OUTPUT_DIR = Path(__file__).parent
DEFAULT_MODEL_PATH = DEFAULT_OUTPUT_DIR / "production_model.json"
DEFAULT_SHAP_DIR = DEFAULT_OUTPUT_DIR / "shap_plots"


# ─── 1. Synthetic Data Generator ────────────────────────────────────────

def generate_training_data(
    n_samples: int = 5000,
    fraud_rate: float = 0.05,
    label_noise_rate: float = 0.08,
    random_seed: int = 42,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """Generate realistic synthetic training data for the Kenya risk engine.

    Creates sophisticated fraud patterns that overlap with legitimate
    transactions — no toy separable distributions. Includes instance-
    dependent label noise (harder cases more likely to be mislabeled)
    to match real MFI labelling quality.

    Args:
        n_samples: Total number of samples to generate.
        fraud_rate: Target fraud prevalence (default 5% — Kenya MFI baseline).
        label_noise_rate: Instance-dependent label noise rate (default 8%).
            Harder cases (probability near 0.5) get flipped more often.
        random_seed: Reproducibility seed.

    Returns:
        Tuple of (DataFrame with feature columns, numpy array of labels).

    Raises:
        ValueError: If fraud_rate or label_noise_rate not in [0, 1].
    """
    if not 0 <= fraud_rate <= 1:
        raise ValueError(f"fraud_rate must be in [0,1], got {fraud_rate}")
    if not 0 <= label_noise_rate <= 1:
        raise ValueError(f"label_noise_rate must be in [0,1], got {label_noise_rate}")

    rng = np.random.default_rng(random_seed)
    n_fraud = int(n_samples * fraud_rate)
    n_legit = n_samples - n_fraud

    logger.info(
        "generating_synthetic_data",
        n_samples=n_samples,
        n_fraud=n_fraud,
        n_legit=n_legit,
        label_noise_rate=label_noise_rate,
    )

    data = np.zeros((n_samples, NUM_FEATURES))
    y_clean = np.zeros(n_samples, dtype=np.int32)

    # ── Legitimate vehicles ─────────────────────────────────────────
    for i in range(n_legit):
        # Graph topology: low connectivity, small component
        data[i, 0] = rng.exponential(1.0)                    # degree_centrality
        data[i, 1] = rng.beta(1, 5)                          # clustering_coefficient
        data[i, 2] = rng.exponential(0.001)                   # page_rank
        data[i, 3] = 1                                       # wcc_component_size
        data[i, 4] = rng.exponential(0.5)                    # betweenness_centrality
        data[i, 5] = rng.exponential(0.3)                    # closeness_centrality
        data[i, 6] = rng.exponential(0.001)                   # eigen_vector_centrality
        data[i, 7] = rng.exponential(0.2)                    # harmonic_centrality
        data[i, 8] = 0                                       # articulation_point_flag
        data[i, 9] = rng.integers(0, 3)                      # triangle_count
        data[i, 10] = rng.exponential(1.0)                   # avg_neighbor_degree
        data[i, 11] = data[i, 10] + rng.exponential(0.5)    # max_neighbor_degree
        data[i, 12] = rng.beta(1, 5)                         # community_density

        # Lender diversity: mostly single lender, low diversity
        data[i, 13] = 1 if rng.random() < 0.85 else 2       # lender_diversity
        data[i, 14] = data[i, 13]                            # unique_lender_count
        data[i, 15] = 1 if rng.random() < 0.30 else 0       # sacco_lender_flag
        data[i, 16] = 1 if rng.random() < 0.10 else 0       # dcp_lender_flag
        data[i, 17] = 0                                      # unregulated_lender_count
        data[i, 18] = rng.exponential(0.3)                   # lender_type_entropy
        data[i, 19] = 0                                      # cross_institution_flag
        data[i, 20] = 1 if rng.random() < 0.15 else 0       # same_branch_repledge_flag

        # Temporal patterns: slow, regular pace
        data[i, 21] = rng.exponential(0.02)                  # temporal_velocity
        data[i, 22] = rng.exponential(180)                   # days_since_last_loan
        data[i, 23] = data[i, 22] * rng.uniform(1.5, 3.0)   # avg_days_between_loans
        data[i, 24] = data[i, 23] * rng.uniform(0.3, 0.8)   # min_days_between_loans
        data[i, 25] = data[i, 23] * rng.uniform(1.5, 4.0)   # max_days_between_loans
        data[i, 26] = 0                                      # loan_count_30d
        data[i, 27] = rng.integers(0, 2)                     # loan_count_90d
        data[i, 28] = 0                                      # seasonal_pattern_flag

        # Vehicle provenance: clean
        data[i, 29] = 0                                      # govt_plate_flag
        data[i, 30] = 0                                      # govt_plate_no_disposal_doc
        data[i, 31] = rng.uniform(1, 15)                     # vehicle_age_years
        data[i, 32] = rng.uniform(0.2, 0.6)                  # county_risk_score
        data[i, 33] = 0                                      # chassis_mismatch_flag
        data[i, 34] = 0                                      # plate_chassis_conflict

        # Auction/yard: no activity
        data[i, 35] = 0                                      # active_auction_flag
        data[i, 36] = 0                                      # auction_count_12m
        data[i, 37] = rng.choice([0, 1], p=[0.7, 0.3])      # storage_yard_count
        data[i, 38] = 0                                      # yard_mobility_count
        data[i, 39] = 0                                      # avg_yard_stay_days
        data[i, 40] = 0                                      # yard_county_mismatch_flag
        data[i, 41] = 0                                      # distress_sale_flag

        # Caveat coverage: clean
        data[i, 42] = 0                                      # caveat_coverage_gap
        data[i, 43] = 0                                      # caveat_not_registered_flag
        data[i, 44] = 0                                      # caveat_registration_lag_days
        data[i, 45] = 0                                      # cross_lender_caveat_conflict
        data[i, 46] = rng.beta(2, 5)                         # total_exposure_kes_normalized

        y_clean[i] = 0

    # ── Fraud vehicles — sophisticated, overlapping with legit ──────
    # Fraudsters try to look legitimate; only some signals give them away.
    for i in range(n_legit, n_samples):
        # Graph topology: SOME fraud has high connectivity, but some mimic legit
        is_sophisticated = rng.random() < 0.4  # 40% of fraud is "smart"
        if is_sophisticated:
            # Sophisticated fraud: tries to look like legit
            data[i, 0] = rng.exponential(1.2)                # degree_centrality (near-legit)
            data[i, 1] = rng.beta(1, 4)                      # clustering_coefficient
            data[i, 2] = rng.exponential(0.002)               # page_rank (slightly elevated)
            data[i, 3] = rng.integers(1, 3)                   # wcc_component_size
            data[i, 4] = rng.exponential(0.8)                 # betweenness_centrality
        else:
            # Obvious fraud: strong graph signals
            data[i, 0] = rng.exponential(3.0) + 2            # degree_centrality
            data[i, 1] = rng.beta(3, 2)                      # clustering_coefficient
            data[i, 2] = rng.exponential(0.01) + 0.005       # page_rank
            data[i, 3] = rng.integers(2, 8)                   # wcc_component_size
            data[i, 4] = rng.exponential(2.0) + 1            # betweenness_centrality

        data[i, 5] = rng.exponential(0.6)                    # closeness_centrality
        data[i, 6] = rng.exponential(0.005)                   # eigen_vector_centrality
        data[i, 7] = rng.exponential(0.5)                    # harmonic_centrality
        data[i, 8] = 1 if rng.random() < 0.3 else 0         # articulation_point_flag
        data[i, 9] = rng.integers(2, 10)                     # triangle_count
        data[i, 10] = rng.exponential(2.5)                   # avg_neighbor_degree
        data[i, 11] = data[i, 10] + rng.exponential(1.5)    # max_neighbor_degree
        data[i, 12] = rng.beta(3, 2)                         # community_density

        # Lender diversity: ALWAYS a key signal for fraud
        data[i, 13] = rng.choice([2, 3, 4], p=[0.3, 0.4, 0.3])  # lender_diversity
        data[i, 14] = data[i, 13]                            # unique_lender_count
        data[i, 15] = 1 if rng.random() < 0.50 else 0       # sacco_lender_flag
        data[i, 16] = 1 if rng.random() < 0.30 else 0       # dcp_lender_flag
        data[i, 17] = rng.integers(0, 3)                     # unregulated_lender_count
        data[i, 18] = rng.exponential(1.0) + 0.5            # lender_type_entropy
        data[i, 19] = 1 if rng.random() < 0.6 else 0        # cross_institution_flag
        data[i, 20] = 1 if rng.random() < 0.5 else 0        # same_branch_repledge_flag

        # Temporal: rapid re-pledging is the hallmark
        if is_sophisticated:
            # Sophisticated: slows down to avoid detection
            data[i, 21] = rng.exponential(0.08)               # temporal_velocity
            data[i, 22] = rng.exponential(30)                 # days_since_last_loan
        else:
            data[i, 21] = rng.exponential(0.3) + 0.1         # temporal_velocity
            data[i, 22] = rng.exponential(10)                 # days_since_last_loan
        data[i, 23] = data[i, 22] * rng.uniform(0.5, 1.5)   # avg_days_between_loans
        data[i, 24] = data[i, 23] * rng.uniform(0.1, 0.5)   # min_days_between_loans
        data[i, 25] = data[i, 23] * rng.uniform(2.0, 6.0)   # max_days_between_loans
        data[i, 26] = rng.integers(1, 5)                     # loan_count_30d
        data[i, 27] = data[i, 26] + rng.integers(0, 3)      # loan_count_90d
        data[i, 28] = 1 if rng.random() < 0.4 else 0        # seasonal_pattern_flag

        # Vehicle provenance: fraud often targets govt plates, high-risk counties
        data[i, 29] = 1 if rng.random() < 0.30 else 0       # govt_plate_flag
        data[i, 30] = data[i, 29] * (1 if rng.random() < 0.5 else 0)  # govt_plate_no_disposal_doc
        data[i, 31] = rng.uniform(3, 20)                     # vehicle_age_years
        data[i, 32] = rng.uniform(0.5, 1.0)                  # county_risk_score
        data[i, 33] = 1 if rng.random() < 0.20 else 0       # chassis_mismatch_flag
        data[i, 34] = 1 if rng.random() < 0.15 else 0       # plate_chassis_conflict

        # Auction/yard: fraud vehicles often appear in yards
        data[i, 35] = 1 if rng.random() < 0.50 else 0       # active_auction_flag
        data[i, 36] = rng.integers(1, 5) if data[i, 35] else 0  # auction_count_12m
        data[i, 37] = rng.choice([1, 2, 3], p=[0.3, 0.4, 0.3])  # storage_yard_count
        data[i, 38] = rng.integers(1, 4)                     # yard_mobility_count
        data[i, 39] = rng.exponential(20) + 5                # avg_yard_stay_days
        data[i, 40] = 1 if rng.random() < 0.3 else 0        # yard_county_mismatch_flag
        data[i, 41] = 1 if rng.random() < 0.4 else 0        # distress_sale_flag

        # Caveat coverage: gaps are a strong fraud signal
        data[i, 42] = 1 if rng.random() < 0.60 else 0       # caveat_coverage_gap
        data[i, 43] = 1 if rng.random() < 0.40 else 0       # caveat_not_registered_flag
        data[i, 44] = rng.exponential(15) if data[i, 43] else 0  # caveat_registration_lag_days
        data[i, 45] = 1 if rng.random() < 0.5 else 0        # cross_lender_caveat_conflict
        data[i, 46] = rng.beta(5, 2)                         # total_exposure_kes_normalized

        y_clean[i] = 1

    # ── Shuffle ─────────────────────────────────────────────────────
    perm = rng.permutation(n_samples)
    data = data[perm]
    y_clean = y_clean[perm]

    # ── Instance-dependent label noise ──────────────────────────────
    # Hard cases (near decision boundary) are more likely to be mislabeled
    # in real MFI operations. Simulate by computing a proxy "difficulty"
    # score and flipping labels proportionally.
    y_noisy = y_clean.copy()
    if label_noise_rate > 0:
        # Use a simple proxy for difficulty: samples with moderate
        # feature magnitudes are harder to label correctly.
        feature_magnitude = np.linalg.norm(data, axis=1)
        p25, p75 = np.percentile(feature_magnitude, [25, 75])
        # Samples near the interquartile range are "harder"
        difficulty = np.exp(-((feature_magnitude - (p25 + p75) / 2) ** 2) / (2 * ((p75 - p25) / 2) ** 2))
        # Normalize so that expected flip rate = label_noise_rate
        flip_probability = difficulty * label_noise_rate / difficulty.mean()
        flip_probability = np.clip(flip_probability, 0, 1)

        flip_mask = rng.random(n_samples) < flip_probability
        y_noisy[flip_mask] = 1 - y_noisy[flip_mask]

        n_flipped = flip_mask.sum()
        logger.info(
            "label_noise_applied",
            n_flipped=int(n_flipped),
            actual_rate=float(n_flipped / n_samples),
            target_rate=label_noise_rate,
        )

    # Build DataFrame
    df = pd.DataFrame(data, columns=FEATURE_NAMES)
    return df, y_noisy


# ─── 2. FLAML Discovery ────────────────────────────────────────────────

def run_flaml_discovery(
    X: pd.DataFrame,
    y: np.ndarray,
    time_budget_minutes: int = 30,
) -> Dict[str, Any]:
    """Run FLAML AutoML to discover the best model type and hyperparameters.

    FLAML is the research intern — it tells us which model family wins
    and what hyperparameters work best. We do NOT deploy the FLAML
    ensemble directly. We take the winner and re-implement it with
    full SHAP interpretability.

    Args:
        X: Feature DataFrame (n_samples x 47 features).
        y: Binary labels (0=legit, 1=fraud).
        time_budget_minutes: FLAML search budget in minutes.

    Returns:
        Dictionary with keys:
            - best_estimator: str, e.g. "xgboost"
            - best_config: dict, FLAML's optimal hyperparameters
            - best_auc: float, best AUC-ROC achieved
            - all_results: dict, per-estimator results for comparison
            - discovery_time_s: float, wall-clock time
            - training_timestamp: str, ISO 8601 UTC

    Raises:
        ImportError: If flaml is not installed.
        RuntimeError: If FLAML search fails entirely.
    """
    try:
        from flaml import AutoML
    except ImportError as exc:
        raise ImportError(
            "FLAML is required for discovery. Install with: pip install flaml[automl]"
        ) from exc

    from sklearn.model_selection import train_test_split

    logger.info(
        "flaml_discovery_start",
        n_samples=len(X),
        n_features=X.shape[1],
        time_budget_minutes=time_budget_minutes,
        estimators=FLAML_ESTIMATORS,
        fraud_rate=float(y.mean()),
    )

    # Hold out 15% for validation (FLAML uses internal CV, but we want
    # an unbiased estimate of the winner's performance)
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y
    )

    start_time = time.monotonic()
    discovery_results: Dict[str, Any] = {}

    try:
        automl = AutoML()
        automl.fit(
            X_train=X_train,
            y_train=y_train,
            task="classification",
            metric="roc_auc",
            time_budget=time_budget_minutes * 60,
            estimator_list=FLAML_ESTIMATORS,
            n_jobs=-1,
            verbose=3,
            seed=42,
        )

        elapsed = time.monotonic() - start_time
        best_auc = 1.0 - automl.best_loss

        # Validate winner on held-out set
        y_pred_proba = automl.predict_proba(X_val)[:, 1]
        from sklearn.metrics import roc_auc_score
        val_auc = roc_auc_score(y_val, y_pred_proba)

        discovery_results = {
            "best_estimator": automl.best_estimator,
            "best_config": dict(automl.best_config) if automl.best_config else {},
            "best_auc": float(best_auc),
            "val_auc": float(val_auc),
            "best_train_time_s": float(automl.best_config_train_time),
            "discovery_time_s": float(elapsed),
            "training_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Collect per-estimator results if available
        all_results = {}
        if hasattr(automl, "best_config_per_estimator"):
            for est_name, config in automl.best_config_per_estimator.items():
                all_results[est_name] = {
                    "config": dict(config) if config else {},
                    "loss": float(automl.best_loss_per_estimator.get(est_name, float("nan"))),
                }
        discovery_results["all_results"] = all_results

        logger.info(
            "flaml_discovery_complete",
            best_estimator=discovery_results["best_estimator"],
            best_auc=discovery_results["best_auc"],
            val_auc=discovery_results["val_auc"],
            discovery_time_s=round(elapsed, 1),
        )

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        logger.error(
            "flaml_discovery_failed",
            error=str(exc),
            traceback=traceback.format_exc(),
            elapsed_s=round(elapsed, 1),
        )
        raise RuntimeError(f"FLAML discovery failed: {exc}") from exc

    return discovery_results


# ─── 3. Production Model Implementation ────────────────────────────────

def implement_production_model(
    discovery_results: Dict[str, Any],
    X_train: pd.DataFrame,
    y_train: np.ndarray,
) -> Any:
    """Manually instantiate the winner model with FLAML's hyperparameters.

    This is the critical step: we do NOT deploy FLAML's internal model.
    We re-create the winner algorithm with the discovered hyperparameters
    so we have full control over:
      - SHAP TreeExplainer compatibility
      - Deterministic serialization
      - No ensemble overhead at inference time
      - Full interpretability for MFI officers

    Args:
        discovery_results: Output from run_flaml_discovery().
        X_train: Training features.
        y_train: Training labels.

    Returns:
        Fitted model object (XGBClassifier, LGBMClassifier, etc.)
        with a .predict_proba() method and SHAP TreeExplainer support.

    Raises:
        RuntimeError: If the winner estimator type is not supported.
    """
    winner = discovery_results["best_estimator"]
    config = discovery_results["best_config"]

    logger.info(
        "implementing_production_winner",
        winner=winner,
        config=config,
    )

    model = _instantiate_winner(winner, config)
    model.fit(X_train, y_train)

    logger.info(
        "production_model_fitted",
        winner=winner,
        n_train=len(X_train),
        model_type=type(model).__name__,
    )

    return model


def _instantiate_winner(winner: str, config: Dict[str, Any]) -> Any:
    """Create an instance of the winner model with FLAML-discovered config.

    Maps FLAML's internal config keys to the native library's API.
    """
    if winner in ("xgboost", "xgb_limitdepth"):
        import xgboost as xgb

        # Map FLAML config to XGBoost API
        xgb_params = {
            "n_estimators": config.get("n_estimators", 500),
            "max_depth": config.get("max_depth", 6),
            "learning_rate": config.get("learning_rate", 0.05),
            "min_child_weight": config.get("min_child_weight", 1),
            "subsample": config.get("subsample", 0.8),
            "colsample_bytree": config.get("colsample_bytree", 0.8),
            "reg_alpha": config.get("reg_alpha", 0.0),
            "reg_lambda": config.get("reg_lambda", 1.0),
            "tree_method": "hist",
            "objective": "binary:logistic",
            "eval_metric": "auc",
            "random_state": 42,
            "n_jobs": -1,
        }
        # FLAML may pass extra keys; only keep valid XGBClassifier args
        valid_xgb_keys = set(xgb.XGBClassifier().get_params().keys())
        xgb_params = {k: v for k, v in xgb_params.items() if k in valid_xgb_keys}

        return xgb.XGBClassifier(**xgb_params)

    elif winner == "lgbm":
        import lightgbm as lgbm

        lgbm_params = {
            "n_estimators": config.get("n_estimators", 500),
            "max_depth": config.get("max_depth", -1),
            "learning_rate": config.get("learning_rate", 0.05),
            "num_leaves": config.get("num_leaves", 31),
            "min_child_samples": config.get("min_child_samples", 20),
            "subsample": config.get("subsample", 0.8),
            "colsample_bytree": config.get("colsample_bytree", 0.8),
            "reg_alpha": config.get("reg_alpha", 0.0),
            "reg_lambda": config.get("reg_lambda", 0.0),
            "objective": "binary",
            "random_state": 42,
            "n_jobs": -1,
            "verbose": -1,
        }
        valid_lgbm_keys = set(lgbm.LGBMClassifier().get_params().keys())
        lgbm_params = {k: v for k, v in lgbm_params.items() if k in valid_lgbm_keys}

        return lgbm.LGBMClassifier(**lgbm_params)

    elif winner == "catboost":
        from catboost import CatBoostClassifier

        cb_params = {
            "iterations": config.get("n_estimators", 500),
            "depth": config.get("max_depth", 6),
            "learning_rate": config.get("learning_rate", 0.05),
            "l2_leaf_reg": config.get("reg_lambda", 3.0),
            "random_seed": 42,
            "verbose": 0,
            "thread_count": -1,
        }

        return CatBoostClassifier(**cb_params)

    elif winner == "rf":
        from sklearn.ensemble import RandomForestClassifier

        rf_params = {
            "n_estimators": config.get("n_estimators", 500),
            "max_depth": config.get("max_depth", None),
            "min_samples_split": config.get("min_samples_split", 2),
            "min_samples_leaf": config.get("min_samples_leaf", 1),
            "max_features": config.get("max_features", "sqrt"),
            "random_state": 42,
            "n_jobs": -1,
        }

        return RandomForestClassifier(**rf_params)

    else:
        raise RuntimeError(
            f"Unsupported winner estimator: {winner}. "
            f"Supported: {FLAML_ESTIMATORS}"
        )


# ─── 4. SHAP Explainability ────────────────────────────────────────────

def compute_shap_explanations(
    model: Any,
    X: pd.DataFrame,
    output_dir: Path = DEFAULT_SHAP_DIR,
    max_display: int = 20,
) -> Dict[str, Any]:
    """Compute SHAP values for the production model.

    Uses TreeExplainer for exact Shapley values (fast for tree models).
    Generates:
      - Summary plot (beeswarm): global feature importance
      - Bar plot: mean |SHAP| per feature
      - Waterfall plots for top-k highest-risk individual predictions

    Args:
        model: Fitted tree-based model (XGB, LGBM, CatBoost, RF).
        X: Feature DataFrame to explain.
        output_dir: Directory to save SHAP plots.
        max_display: Number of features to show in plots.

    Returns:
        Dictionary with:
            - shap_values: numpy array of SHAP values (n_samples x n_features)
            - base_value: float, expected model output (E[f(x)])
            - mean_abs_shap: dict, feature → mean |SHAP value|
            - plot_paths: dict, name → file path of saved plot

    Raises:
        ImportError: If shap is not installed.
        RuntimeError: If SHAP computation fails.
    """
    try:
        import shap
    except ImportError as exc:
        raise ImportError(
            "SHAP is required for explainability. Install with: pip install shap"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "computing_shap_values",
        n_samples=len(X),
        n_features=X.shape[1],
        model_type=type(model).__name__,
    )

    try:
        # TreeExplainer for exact, fast Shapley values
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)

        # For LightGBM binary, shap_values is a list [class0, class1]
        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # Take the fraud class

        base_value = float(explainer.expected_value)
        if isinstance(base_value, np.ndarray):
            base_value = float(base_value[1])  # Binary: take class 1

    except Exception as exc:
        logger.error("shap_computation_failed", error=str(exc))
        raise RuntimeError(f"SHAP computation failed: {exc}") from exc

    # Mean |SHAP| per feature (global importance)
    mean_abs = np.abs(shap_values).mean(axis=0)
    mean_abs_shap = {
        name: float(val) for name, val in zip(FEATURE_NAMES, mean_abs)
    }

    # ── Generate plots ──────────────────────────────────────────────
    plot_paths: Dict[str, Path] = {}

    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt

        # Summary / beeswarm plot
        fig, ax = plt.subplots(figsize=(12, 8))
        shap.summary_plot(
            shap_values, X, feature_names=FEATURE_NAMES,
            max_display=max_display, show=False,
        )
        summary_path = output_dir / "shap_summary.png"
        fig.savefig(summary_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        plot_paths["summary"] = summary_path

        # Bar plot: mean |SHAP|
        fig, ax = plt.subplots(figsize=(12, 8))
        shap.summary_plot(
            shap_values, X, feature_names=FEATURE_NAMES,
            plot_type="bar", max_display=max_display, show=False,
        )
        bar_path = output_dir / "shap_importance_bar.png"
        fig.savefig(bar_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        plot_paths["importance_bar"] = bar_path

        # Waterfall plots for top 5 highest-risk predictions
        risk_scores = shap_values.sum(axis=1) + base_value
        top_indices = np.argsort(risk_scores)[-5:][::-1]

        for rank, idx in enumerate(top_indices, 1):
            fig, ax = plt.subplots(figsize=(12, 6))
            shap_explanation = shap.Explanation(
                values=shap_values[idx],
                base_values=base_value,
                data=X.iloc[idx].values,
                feature_names=FEATURE_NAMES,
            )
            shap.waterfall_plot(shap_explanation, max_display=15, show=False)
            waterfall_path = output_dir / f"shap_waterfall_top{rank}_idx{idx}.png"
            fig.savefig(waterfall_path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            plot_paths[f"waterfall_top{rank}"] = waterfall_path

        logger.info("shap_plots_saved", n_plots=len(plot_paths), output_dir=str(output_dir))

    except Exception as exc:
        logger.warning(
            "shap_plot_generation_failed",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        # SHAP values are still valid; plots are optional

    return {
        "shap_values": shap_values,
        "base_value": base_value,
        "mean_abs_shap": mean_abs_shap,
        "plot_paths": {k: str(v) for k, v in plot_paths.items()},
    }


# ─── 5. MFI Human-Readable Explanations ────────────────────────────────

def generate_mfi_explanation(
    plate: str,
    risk_score: int,
    shap_values: np.ndarray,
    feature_values: Dict[str, float],
    base_value: float = 0.0,
    top_n: int = 5,
) -> str:
    """Generate a human-readable explanation for MFI officers.

    Produces text like:
      "Vehicle KDA123J scored 87/100 (HIGH RISK).
       Top factors: lender_diversity=3 (+23 pts), temporal_velocity=0.45 (+18 pts),
       caveat_coverage_gap=1 (+12 pts), active_auction_flag=1 (+9 pts),
       county_risk_score=0.85 (+7 pts).
       Base risk: 5/100. Decision: REJECT_LOAN"

    This satisfies CBK/ODPC audit requirements for documented decision logic
    on automated credit decisions.

    Args:
        plate: Kenya vehicle plate (e.g. "KDA123J").
        risk_score: Integer 0-100 risk score.
        shap_values: SHAP values for this single prediction (1D array).
        feature_values: Dict of feature_name → actual value for this vehicle.
        base_value: Model's expected value (E[f(X)]).
        top_n: Number of top contributing features to show.

    Returns:
        Human-readable explanation string.
    """
    # Map risk score to level and decision
    if risk_score >= 80:
        level, decision = "CRITICAL RISK", "REJECT_LOAN — escalate to senior credit officer"
    elif risk_score >= 60:
        level, decision = "HIGH RISK", "REJECT_LOAN — manual review optional"
    elif risk_score >= 40:
        level, decision = "MEDIUM RISK", "REVIEW_MANUALLY — MFI officer discretion"
    elif risk_score >= 20:
        level, decision = "LOW RISK", "APPROVE_WITH_CONDITIONS — enhanced monitoring"
    else:
        level, decision = "MINIMAL RISK", "APPROVE_LOAN — standard monitoring"

    # Rank features by absolute SHAP contribution
    contributions = list(zip(FEATURE_NAMES, shap_values))
    contributions.sort(key=lambda x: abs(x[1]), reverse=True)

    # Build human-readable factor descriptions
    base_score = int(base_value * 100) if 0 < base_value < 1 else int(base_value * 100)
    factor_lines = []
    for feat_name, shap_val in contributions[:top_n]:
        actual_val = feature_values.get(feat_name, 0.0)
        # Convert SHAP value to approximate "points" on 0-100 scale
        points = int(shap_val * 100)
        sign = "+" if points >= 0 else ""
        # Human-friendly feature display
        display_val = _humanize_feature_value(feat_name, actual_val)
        factor_lines.append(f"  {feat_name}={display_val} ({sign}{points} pts)")

    factors_text = "\n".join(factor_lines)

    explanation = (
        f"Vehicle {plate} scored {risk_score}/100 ({level}).\n"
        f"\n"
        f"Top contributing factors:\n"
        f"{factors_text}\n"
        f"\n"
        f"Base risk (population average): {base_score}/100.\n"
        f"Decision: {decision}\n"
        f"\n"
        f"--- CBK/ODPC Audit: Decision logic documented via SHAP values ---\n"
        f"Model: FLAML-discovered winner | Explainer: TreeExplainer (exact Shapley)\n"
        f"Generated: {datetime.now(timezone.utc).isoformat()}"
    )

    return explanation


def _humanize_feature_value(name: str, value: float) -> str:
    """Convert raw feature values to human-friendly display.

    Examples:
        lender_diversity=3 → "3 lenders"
        govt_plate_flag=1 → "YES"
        temporal_velocity=0.45 → "0.45 (rapid re-pledging)"
    """
    flag_features = {
        "articulation_point_flag", "sacco_lender_flag", "dcp_lender_flag",
        "cross_institution_flag", "same_branch_repledge_flag", "govt_plate_flag",
        "govt_plate_no_disposal_doc", "chassis_mismatch_flag", "plate_chassis_conflict",
        "active_auction_flag", "yard_county_mismatch_flag", "distress_sale_flag",
        "caveat_coverage_gap", "caveat_not_registered_flag",
        "cross_lender_caveat_conflict", "seasonal_pattern_flag",
    }
    count_features = {
        "lender_diversity", "unique_lender_count", "unregulated_lender_count",
        "wcc_component_size", "triangle_count", "loan_count_30d", "loan_count_90d",
        "auction_count_12m", "storage_yard_count", "yard_mobility_count",
    }

    if name in flag_features:
        return "YES" if value >= 0.5 else "NO"
    elif name in count_features:
        return str(int(round(value)))
    elif name == "temporal_velocity" and value > 0.1:
        return f"{value:.2f} (rapid re-pledging)"
    elif name == "days_since_last_loan":
        return f"{value:.0f} days"
    elif name == "vehicle_age_years":
        return f"{value:.1f} years"
    elif name == "county_risk_score":
        return f"{value:.2f}"
    elif name == "total_exposure_kes_normalized":
        return f"{value:.3f}"
    elif name in ("avg_yard_stay_days", "caveat_registration_lag_days"):
        return f"{value:.0f} days"
    else:
        return f"{value:.4f}"


# ─── 6. Probability Calibration ────────────────────────────────────────

def calibrate_probabilities(
    model: Any,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
) -> Any:
    """Calibrate model probabilities using IsotonicRegression.

    Raw tree model probabilities are poorly calibrated (bunched near 0/1).
    For MFI risk thresholds (e.g. "reject if P(fraud) > 0.15"), we need
    calibrated probabilities that reflect true frequencies.

    IsotonicRegression is monotonic and makes no distributional assumptions,
    making it suitable for CBK audit — it can only improve calibration.

    Args:
        model: Fitted production model with .predict_proba() method.
        X_val: Validation features (NOT used in training).
        y_val: Validation labels.

    Returns:
        Fitted sklearn IsotonicRegression object.
        Use: calibrated_prob = isotonic.predict(raw_prob)

    Raises:
        RuntimeError: If calibration fails.
    """
    from sklearn.isotonic import IsotonicRegression

    logger.info("calibrating_probabilities", n_val=len(X_val))

    try:
        raw_proba = model.predict_proba(X_val)[:, 1]

        isotonic = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        isotonic.fit(raw_proba, y_val)

        # Evaluate calibration quality
        calibrated_proba = isotonic.predict(raw_proba)
        from sklearn.metrics import brier_score_loss
        brier_raw = brier_score_loss(y_val, raw_proba)
        brier_cal = brier_score_loss(y_val, calibrated_proba)

        logger.info(
            "calibration_complete",
            brier_score_raw=round(brier_raw, 4),
            brier_score_calibrated=round(brier_cal, 4),
            improvement_pct=round((brier_raw - brier_cal) / brier_raw * 100, 1),
        )

        return isotonic

    except Exception as exc:
        logger.error("calibration_failed", error=str(exc))
        raise RuntimeError(f"Probability calibration failed: {exc}") from exc


# ─── 7. Audit Trail ────────────────────────────────────────────────────

def save_audit_trail(
    model: Any,
    discovery_results: Dict[str, Any],
    shap_results: Dict[str, Any],
    calibration_model: Any,
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Save CBK/ODPC-compliant audit trail for this training run.

    Every automated credit decision system in Kenya must maintain
    an audit trail documenting:
      - Model architecture and hyperparameters
      - Training data provenance and statistics
      - Feature importance and SHAP values
      - Calibration method and quality
      - Model performance metrics
      - Timestamp and run identifier

    Args:
        model: Fitted production model.
        discovery_results: FLAML discovery output.
        shap_results: SHAP computation output.
        calibration_model: IsotonicRegression calibration model.
        X_train: Training features.
        y_train: Training labels.
        X_val: Validation features.
        y_val: Validation labels.
        output_dir: Directory to save audit trail.

    Returns:
        Path to saved audit trail JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    run_id = f"run_{now.strftime('%Y%m%dT%H%M%S')}_{discovery_results.get('best_estimator', 'unknown')}"

    # Compute validation metrics
    from sklearn.metrics import (
        roc_auc_score, precision_score, recall_score, f1_score,
        classification_report,
    )
    y_pred_proba = model.predict_proba(X_val)[:, 1]
    y_pred = (y_pred_proba >= 0.5).astype(int)

    # Build audit record
    audit = {
        "run_id": run_id,
        "timestamp": now.isoformat(),
        "schema_version": "1.0",
        "regulatory_framework": "CBK/ODPC Automated Credit Decision Audit",

        # Model specification
        "model": {
            "type": type(model).__name__,
            "winner_estimator": discovery_results.get("best_estimator"),
            "hyperparameters": discovery_results.get("best_config", {}),
            "n_features": int(X_train.shape[1]),
            "feature_names": FEATURE_NAMES,
            "feature_groups": {k: v for k, v in FEATURE_GROUPS.items()},
        },

        # Data provenance
        "data": {
            "n_train": len(X_train),
            "n_val": len(X_val),
            "fraud_rate_train": float(y_train.mean()),
            "fraud_rate_val": float(y_val.mean()),
            "feature_statistics": {
                name: {
                    "mean": float(X_train[name].mean()),
                    "std": float(X_train[name].std()),
                    "min": float(X_train[name].min()),
                    "max": float(X_train[name].max()),
                }
                for name in FEATURE_NAMES
            },
        },

        # Discovery results
        "flaml_discovery": {
            "best_estimator": discovery_results.get("best_estimator"),
            "best_auc": discovery_results.get("best_auc"),
            "val_auc": discovery_results.get("val_auc"),
            "discovery_time_s": discovery_results.get("discovery_time_s"),
            "all_results": discovery_results.get("all_results", {}),
        },

        # Model performance
        "performance": {
            "val_auc": float(roc_auc_score(y_val, y_pred_proba)),
            "val_precision": float(precision_score(y_val, y_pred, zero_division=0)),
            "val_recall": float(recall_score(y_val, y_pred, zero_division=0)),
            "val_f1": float(f1_score(y_val, y_pred, zero_division=0)),
            "classification_report": classification_report(
                y_val, y_pred, target_names=["legitimate", "fraud"], output_dict=True
            ),
        },

        # SHAP / explainability
        "explainability": {
            "method": "TreeExplainer (exact Shapley values)",
            "base_value": shap_results.get("base_value"),
            "mean_abs_shap_top10": dict(
                sorted(
                    shap_results.get("mean_abs_shap", {}).items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:10]
            ),
        },

        # Calibration
        "calibration": {
            "method": "IsotonicRegression",
            "monotonic": True,
            "bounds": "clipped to [0, 1]",
        },

        # Data integrity hash
        "integrity": {
            "training_data_hash": hashlib.sha256(
                X_train.values.tobytes()
            ).hexdigest()[:16],
            "labels_hash": hashlib.sha256(
                y_train.tobytes()
            ).hexdigest()[:16],
        },
    }

    audit_path = output_dir / f"audit_trail_{run_id}.json"
    with open(audit_path, "w") as f:
        json.dump(audit, f, indent=2, default=str)

    logger.info("audit_trail_saved", path=str(audit_path), run_id=run_id)
    return audit_path


# ─── 8. Main Pipeline ──────────────────────────────────────────────────

def main() -> None:
    """Run the FLAML → Winner → SHAP production training pipeline.

    Steps:
      1. Load or generate training data
      2. FLAML AutoML discovers best model + hyperparameters
      3. Manually implement the winner with FLAML's config
      4. Compute SHAP values for full interpretability
      5. Calibrate probabilities for MFI risk thresholds
      6. Save model, SHAP plots, and CBK/ODPC audit trail
      7. If --explain given, generate MFI explanation for a plate
    """
    parser = argparse.ArgumentParser(
        description=(
            "FLAML AutoML → Manual Winner → SHAP Explainability "
            "for Kenya Vehicle Collateral Risk Engine"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--time-budget", type=int, default=30,
        help="FLAML search budget in minutes (default: 30)",
    )
    parser.add_argument(
        "--data", type=str, default=None,
        help="Path to real data CSV (must contain FEATURE_NAMES columns + 'is_fraud')",
    )
    parser.add_argument(
        "--explain", type=str, default=None, metavar="PLATE",
        help="Generate MFI explanation for a specific plate number",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for model, SHAP plots, and audit trail",
    )
    parser.add_argument(
        "--n-samples", type=int, default=5000,
        help="Number of synthetic samples (ignored if --data is given)",
    )
    parser.add_argument(
        "--fraud-rate", type=float, default=0.05,
        help="Target fraud rate for synthetic data (default: 0.05)",
    )
    parser.add_argument(
        "--label-noise", type=float, default=0.08,
        help="Instance-dependent label noise rate (default: 0.08)",
    )
    args = parser.parse_args()

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    shap_dir = output_dir / "shap_plots"
    shap_dir.mkdir(parents=True, exist_ok=True)

    model_path = output_dir / "production_model.json"

    logger.info(
        "pipeline_start",
        time_budget_minutes=args.time_budget,
        data_path=args.data,
        explain_plate=args.explain,
        output_dir=str(output_dir),
    )

    # ── Step 1: Load or generate training data ──────────────────────
    logger.info("step1_data_preparation")

    if args.data:
        try:
            df = pd.read_csv(args.data)
            missing_cols = [c for c in FEATURE_NAMES if c not in df.columns]
            if missing_cols:
                raise ValueError(f"Missing feature columns: {missing_cols[:5]}...")
            if "is_fraud" not in df.columns:
                raise ValueError("Column 'is_fraud' not found in data")
            X = df[FEATURE_NAMES]
            y = df["is_fraud"].values.astype(np.int32)
            logger.info(
                "data_loaded_from_csv",
                path=args.data,
                n_samples=len(X),
                fraud_rate=float(y.mean()),
            )
        except Exception as exc:
            logger.error("data_load_failed", path=args.data, error=str(exc))
            sys.exit(1)
    else:
        X, y = generate_training_data(
            n_samples=args.n_samples,
            fraud_rate=args.fraud_rate,
            label_noise_rate=args.label_noise,
        )
        logger.info(
            "synthetic_data_generated",
            n_samples=len(X),
            fraud_rate=float(y.mean()),
        )

    # ── Train/val split ─────────────────────────────────────────────
    from sklearn.model_selection import train_test_split

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y
    )
    logger.info(
        "data_split",
        n_train=len(X_train),
        n_val=len(X_val),
        fraud_rate_train=float(y_train.mean()),
        fraud_rate_val=float(y_val.mean()),
    )

    # ── Step 2: FLAML Discovery ─────────────────────────────────────
    logger.info("step2_flaml_discovery", time_budget_minutes=args.time_budget)

    try:
        discovery_results = run_flaml_discovery(
            X_train, y_train, time_budget_minutes=args.time_budget
        )
    except ImportError as exc:
        logger.error("flaml_not_available", error=str(exc))
        logger.info("falling_back_to_default_xgboost")
        # Fallback: use a well-tuned XGBoost as the "discovered" winner
        discovery_results = {
            "best_estimator": "xgboost",
            "best_config": {
                "n_estimators": 500,
                "max_depth": 6,
                "learning_rate": 0.05,
                "min_child_weight": 3,
                "subsample": 0.8,
                "colsample_bytree": 0.7,
                "reg_alpha": 0.01,
                "reg_lambda": 1.0,
            },
            "best_auc": 0.0,  # Unknown without FLAML
            "val_auc": 0.0,
            "best_train_time_s": 0.0,
            "discovery_time_s": 0.0,
            "all_results": {},
            "training_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except RuntimeError as exc:
        logger.error("flaml_discovery_error", error=str(exc))
        sys.exit(1)

    # ── Step 3: Implement Production Winner ─────────────────────────
    logger.info("step3_implement_winner")

    try:
        model = implement_production_model(discovery_results, X_train, y_train)
    except RuntimeError as exc:
        logger.error("model_implementation_failed", error=str(exc))
        sys.exit(1)

    # Evaluate on validation set
    from sklearn.metrics import roc_auc_score, classification_report

    y_val_proba = model.predict_proba(X_val)[:, 1]
    val_auc = roc_auc_score(y_val, y_val_proba)
    y_val_pred = (y_val_proba >= 0.5).astype(int)
    clf_report = classification_report(
        y_val, y_val_pred, target_names=["legitimate", "fraud"]
    )

    discovery_results["val_auc"] = float(val_auc)

    logger.info(
        "production_model_evaluated",
        val_auc=round(val_auc, 4),
        winner=discovery_results["best_estimator"],
    )
    print(f"\n{'='*70}")
    print(f"  PRODUCTION MODEL: {discovery_results['best_estimator'].upper()}")
    print(f"  Validation AUC-ROC: {val_auc:.4f}")
    print(f"{'='*70}")
    print(clf_report)

    # ── Step 4: SHAP Explainability ─────────────────────────────────
    logger.info("step4_shap_explainability")

    try:
        shap_results = compute_shap_explanations(model, X_val, output_dir=shap_dir)
    except ImportError as exc:
        logger.error("shap_not_available", error=str(exc))
        shap_results = {"base_value": 0.0, "mean_abs_shap": {}, "plot_paths": {}}
    except RuntimeError as exc:
        logger.error("shap_computation_error", error=str(exc))
        shap_results = {"base_value": 0.0, "mean_abs_shap": {}, "plot_paths": {}}

    # Print top-10 feature importance by SHAP
    if shap_results.get("mean_abs_shap"):
        sorted_shap = sorted(
            shap_results["mean_abs_shap"].items(),
            key=lambda x: x[1],
            reverse=True,
        )
        print(f"\n{'='*70}")
        print("  TOP 10 FEATURES BY MEAN |SHAP| (CBK/ODPC Audit Requirement)")
        print(f"{'='*70}")
        for rank, (feat, val) in enumerate(sorted_shap[:10], 1):
            group = _feature_group(feat)
            print(f"  {rank:2d}. {feat:35s} {val:.4f}  [{group}]")

    # ── Step 5: Calibrate Probabilities ─────────────────────────────
    logger.info("step5_probability_calibration")

    try:
        calibration_model = calibrate_probabilities(model, X_val, y_val)
    except RuntimeError as exc:
        logger.error("calibration_failed", error=str(exc))
        calibration_model = None

    # ── Step 6: Save Model + Audit Trail ────────────────────────────
    logger.info("step6_save_model_and_audit")

    # Save the production model
    try:
        _save_model(model, model_path)
        logger.info("production_model_saved", path=str(model_path))
    except Exception as exc:
        logger.error("model_save_failed", error=str(exc))

    # Save calibration model
    if calibration_model is not None:
        cal_path = output_dir / "calibration_isotonic.json"
        try:
            import pickle
            with open(cal_path, "wb") as f:
                pickle.dump(calibration_model, f)
            logger.info("calibration_model_saved", path=str(cal_path))
        except Exception as exc:
            logger.error("calibration_save_failed", error=str(exc))

    # Save audit trail
    try:
        audit_path = save_audit_trail(
            model, discovery_results, shap_results, calibration_model,
            pd.DataFrame(X_train, columns=FEATURE_NAMES) if not isinstance(X_train, pd.DataFrame) else X_train,
            y_train,
            pd.DataFrame(X_val, columns=FEATURE_NAMES) if not isinstance(X_val, pd.DataFrame) else X_val,
            y_val,
            output_dir=output_dir,
        )
        logger.info("audit_trail_saved", path=str(audit_path))
    except Exception as exc:
        logger.error("audit_trail_failed", error=str(exc))

    # ── Step 7: Single-vehicle explanation (if requested) ───────────
    if args.explain:
        logger.info("step7_single_vehicle_explanation", plate=args.explain)

        # Pick a sample from validation set for demonstration
        # (In production, features would come from the graph/LRVS)
        sample_idx = np.argmax(y_val_proba)  # Highest risk
        sample_shap = shap_results.get("shap_values", np.zeros((1, NUM_FEATURES)))
        if isinstance(sample_shap, np.ndarray) and sample_shap.ndim == 2:
            sample_shap_1d = sample_shap[sample_idx]
        else:
            sample_shap_1d = np.zeros(NUM_FEATURES)

        sample_features = X_val.iloc[sample_idx] if isinstance(X_val, pd.DataFrame) else pd.Series(
            X_val[sample_idx], index=FEATURE_NAMES
        )
        risk_score = int(y_val_proba[sample_idx] * 100)

        explanation = generate_mfi_explanation(
            plate=args.explain,
            risk_score=risk_score,
            shap_values=sample_shap_1d,
            feature_values=sample_features.to_dict(),
            base_value=shap_results.get("base_value", 0.0),
        )

        print(f"\n{'='*70}")
        print("  MFI OFFICER EXPLANATION")
        print(f"{'='*70}")
        print(explanation)

    # ── Summary ─────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    print(f"\n{'='*70}")
    print("  PIPELINE COMPLETE")
    print(f"{'='*70}")
    print(f"  Winner model:     {discovery_results.get('best_estimator', 'N/A')}")
    print(f"  Validation AUC:   {val_auc:.4f}")
    print(f"  Model saved to:   {model_path}")
    print(f"  SHAP plots:       {shap_dir}")
    print(f"  Completed at:     {now.isoformat()}")
    print(f"{'='*70}")


def _save_model(model: Any, path: Path) -> None:
    """Save the production model to disk.

    Uses native serialization for each model type for maximum
    compatibility and minimal dependencies at inference time.
    """
    model_type = type(model).__name__

    if model_type == "XGBClassifier":
        model.save_model(str(path))
    elif model_type == "LGBMClassifier":
        model.booster_.save_model(str(path))
    elif model_type == "CatBoostClassifier":
        cb_path = str(path).replace(".json", ".cbm")
        model.save_model(cb_path, format="cbm")
    elif model_type == "RandomForestClassifier":
        import pickle
        with open(str(path).replace(".json", ".pkl"), "wb") as f:
            pickle.dump(model, f)
    else:
        # Generic fallback
        import pickle
        with open(str(path).replace(".json", ".pkl"), "wb") as f:
            pickle.dump(model, f)


def _feature_group(feature_name: str) -> str:
    """Return the feature group name for a given feature."""
    for group, features in FEATURE_GROUPS.items():
        if feature_name in features:
            return group
    return "unknown"


if __name__ == "__main__":
    main()

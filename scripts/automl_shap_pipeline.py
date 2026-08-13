"""
FLAML AutoML → SHAP Explainability Pipeline for Kenya Risk Engine

Two-phase approach:
  Phase 1: FLAML AutoML discovers the best model + hyperparameters (research)
  Phase 2: Manually implement winner with full SHAP explainability (production)

Why NOT pure AutoML for production:
  1. MFI officers need reasons: "This vehicle scored 87 because lender_diversity=3"
  2. CBK/ODPC audits require documented decision logic for automated credit decisions
  3. AutoML ensembles cost 3x compute at inference time
  4. Feature engineering is the moat, not model choice

Workflow:
  Step 1: FLAML searches xgboost, lgbm, catboost, rf for 1 hour
  Step 2: Record best model, best hyperparameters, best AUC
  Step 3: Manually implement winner with full SHAP values
  Step 4: Generate MFI-ready explanations for every prediction
  Step 5: Audit trail for CBK/ODPC compliance

Usage:
    python automl_shap_pipeline.py                              # Full pipeline
    python automl_shap_pipeline.py --phase discovery             # Phase 1 only (FLAML)
    python automl_shap_pipeline.py --phase production            # Phase 2 only (SHAP)
    python automl_shap_pipeline.py --time-budget 60              # 60-minute FLAML budget
    python automl_shap_pipeline.py --explain KDA123J             # Explain a single vehicle
    python automl_shap_pipeline.py --compare                    # Compare all estimators
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger("automl_shap_pipeline")


# ─── Feature Definitions ─────────────────────────────────────────────

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


# ─── Training Data Generator ─────────────────────────────────────────

def generate_training_data(n_samples: int = 5000, fraud_rate: float = 0.05) -> tuple:
    """Generate realistic training data with organic-style noise."""
    np.random.seed(42)
    n_fraud = int(n_samples * fraud_rate)
    n_legit = n_samples - n_fraud

    X = np.zeros((n_samples, NUM_FEATURES))
    y = np.zeros(n_samples, dtype=int)

    # Legitimate vehicles
    for i in range(n_legit):
        X[i, FEATURE_NAMES.index("degree_centrality")] = np.random.exponential(1.0)
        X[i, FEATURE_NAMES.index("lender_diversity")] = 1 if np.random.random() < 0.85 else 2
        X[i, FEATURE_NAMES.index("unique_lender_count")] = 1
        X[i, FEATURE_NAMES.index("temporal_velocity")] = np.random.exponential(0.02)
        X[i, FEATURE_NAMES.index("days_since_last_loan")] = np.random.exponential(180)
        X[i, FEATURE_NAMES.index("vehicle_age_years")] = np.random.uniform(1, 15)
        X[i, FEATURE_NAMES.index("county_risk_score")] = np.random.uniform(0.2, 0.6)
        X[i, FEATURE_NAMES.index("govt_plate_flag")] = 0
        X[i, FEATURE_NAMES.index("active_auction_flag")] = 0
        X[i, FEATURE_NAMES.index("storage_yard_count")] = np.random.choice([0, 1], p=[0.7, 0.3])
        X[i, FEATURE_NAMES.index("caveat_coverage_gap")] = 0
        X[i, FEATURE_NAMES.index("chassis_mismatch_flag")] = 0
        X[i, FEATURE_NAMES.index("total_exposure_kes_normalized")] = np.random.beta(2, 5)
        y[i] = 0

    # Fraud vehicles (elevated features)
    for i in range(n_legit, n_samples):
        X[i, FEATURE_NAMES.index("degree_centrality")] = np.random.exponential(3.0) + 2
        X[i, FEATURE_NAMES.index("wcc_component_size")] = np.random.randint(2, 8)
        X[i, FEATURE_NAMES.index("lender_diversity")] = np.random.choice([2, 3, 4], p=[0.4, 0.4, 0.2])
        X[i, FEATURE_NAMES.index("unique_lender_count")] = X[i, FEATURE_NAMES.index("lender_diversity")]
        X[i, FEATURE_NAMES.index("temporal_velocity")] = np.random.exponential(0.3) + 0.1
        X[i, FEATURE_NAMES.index("days_since_last_loan")] = np.random.exponential(10)
        X[i, FEATURE_NAMES.index("loan_count_30d")] = np.random.randint(1, 5)
        X[i, FEATURE_NAMES.index("vehicle_age_years")] = np.random.uniform(3, 20)
        X[i, FEATURE_NAMES.index("county_risk_score")] = np.random.uniform(0.5, 1.0)
        X[i, FEATURE_NAMES.index("govt_plate_flag")] = np.random.choice([0, 1], p=[0.7, 0.3])
        X[i, FEATURE_NAMES.index("active_auction_flag")] = np.random.choice([0, 1], p=[0.5, 0.5])
        X[i, FEATURE_NAMES.index("storage_yard_count")] = np.random.choice([1, 2, 3], p=[0.3, 0.4, 0.3])
        X[i, FEATURE_NAMES.index("caveat_coverage_gap")] = np.random.choice([0, 1], p=[0.3, 0.7])
        X[i, FEATURE_NAMES.index("chassis_mismatch_flag")] = np.random.choice([0, 1], p=[0.8, 0.2])
        X[i, FEATURE_NAMES.index("cross_institution_flag")] = 1
        X[i, FEATURE_NAMES.index("total_exposure_kes_normalized")] = np.random.beta(5, 2)
        y[i] = 1

    # Add label noise (5% symmetric) for realistic AUC
    noise_idx = np.random.choice(n_samples, int(n_samples * 0.05), replace=False)
    y[noise_idx] = 1 - y[noise_idx]

    perm = np.random.permutation(n_samples)
    return X[perm], y[perm]


# ─── Phase 1: FLAML Discovery ────────────────────────────────────────

def phase1_discovery(
    X: np.ndarray,
    y: np.ndarray,
    time_budget_minutes: int = 60,
) -> Dict:
    """Phase 1: Use FLAML AutoML to discover the best model + hyperparameters.
    
    This is RESEARCH, not production. We search:
      - xgboost (our current model)
      - xgb_limitdepth (XGBoost with depth limit)
      - lgbm (LightGBM — often 1-2% better than XGBoost)
      - catboost (CatBoost — handles categoricals natively)
      - rf (Random Forest — baseline)
    
    Time budget: 60 minutes by default.
    """
    try:
        from flaml import AutoML
    except ImportError:
        logger.error("flaml_not_installed", hint="pip install flaml")
        print("\n  FLAML not installed. Install with: pip install flaml")
        return {"error": "flaml_not_installed"}

    print(f"\n{'='*70}")
    print(f" Phase 1: FLAML AutoML Discovery")
    print(f" Time budget: {time_budget_minutes} minutes")
    print(f" Searching: xgboost, xgb_limitdepth, lgbm, catboost, rf")
    print(f"{'='*70}\n")

    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train/test split for evaluation
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.2, random_state=42, stratify=y
    )

    # Run FLAML
    start = time.time()
    automl = AutoML()
    automl.fit(
        X_train=X_train,
        y_train=y_train,
        task="classification",
        metric="roc_auc",
        time_budget=time_budget_minutes * 60,
        estimator_list=["xgboost", "xgb_limitdepth", "lgbm", "catboost", "rf"],
        n_jobs=-1,
        verbose=3,
        eval_method="holdout",
    )
    elapsed = time.time() - start

    best_auc = 1 - automl.best_loss

    # Evaluate on held-out test set
    from sklearn.metrics import roc_auc_score
    y_pred_proba = automl.predict_proba(X_test)[:, 1]
    test_auc = roc_auc_score(y_test, y_pred_proba)

    results = {
        "phase": "discovery",
        "best_estimator": automl.best_estimator,
        "best_config": automl.best_config,
        "best_auc_cv": best_auc,
        "test_auc": test_auc,
        "training_time_s": elapsed,
        "time_budget_minutes": time_budget_minutes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print(f"\n  Discovery Results:")
    print(f"    Best estimator:   {automl.best_estimator}")
    print(f"    Best CV AUC:      {best_auc:.4f}")
    print(f"    Test AUC:         {test_auc:.4f}")
    print(f"    Training time:    {elapsed:.1f}s")
    print(f"    Best config:      {json.dumps(automl.best_config, indent=2)}")

    # Save discovery results
    output_path = Path("/home/z/my-project/scripts/automl_discovery_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info("discovery_complete", **results)
    return results


# ─── Phase 2: Production Model with SHAP ─────────────────────────────

def phase2_production(
    X: np.ndarray,
    y: np.ndarray,
    discovery_results: Optional[Dict] = None,
) -> Dict:
    """Phase 2: Implement the AutoML winner with full SHAP explainability.
    
    This is PRODUCTION. We implement the best model found in Phase 1
    with:
      - Full SHAP values for every prediction
      - MFI-ready text explanations
      - CBK/ODPC audit trail
      - Feature importance ranking
    """
    from sklearn.model_selection import train_test_split, StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, classification_report

    print(f"\n{'='*70}")
    print(f" Phase 2: Production Model with SHAP Explainability")
    print(f"{'='*70}\n")

    # Determine which model to use
    best_estimator = "xgboost"  # Default
    best_config = {}
    if discovery_results:
        best_estimator = discovery_results.get("best_estimator", "xgboost")
        best_config = discovery_results.get("best_config", {})

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.2, random_state=42, stratify=y
    )

    # Implement the winner model
    model = _build_model(best_estimator, best_config, y_train)

    print(f"  Training {best_estimator} on {len(X_train)} samples...")
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # Evaluate
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    test_auc = roc_auc_score(y_test, y_pred_proba)
    y_pred = model.predict(X_test)
    report = classification_report(y_test, y_pred, target_names=["legitimate", "fraud"])

    print(f"  Test AUC: {test_auc:.4f}")
    print(f"\n{report}")

    # SHAP values for explainability
    shap_results = _compute_shap(model, X_test, best_estimator)

    # Feature importance
    if hasattr(model, "feature_importances_"):
        importance = model.feature_importances_
        importance_dict = dict(zip(FEATURE_NAMES, importance.tolist()))
        sorted_features = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)
    else:
        sorted_features = list(zip(FEATURE_NAMES, shap_results.get("mean_abs_shap", [0]*NUM_FEATURES)))
        importance_dict = dict(sorted_features)

    print(f"\n  Top 10 Features (by importance):")
    for name, imp in sorted_features[:10]:
        print(f"    {name:40s} {imp:.4f}")

    # Save model
    model_path = Path("/home/z/my-project/scripts/risk_model_production.json")
    scaler_path = Path("/home/z/my-project/scripts/risk_model_scaler_production.json")

    if hasattr(model, "save_model"):
        model.save_model(str(model_path))

    with open(scaler_path, "w") as f:
        json.dump({
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
        }, f)

    # Generate sample SHAP explanations
    explanations = _generate_mfi_explanations(
        model, scaler, shap_results, X_test[:5], y_pred_proba[:5]
    )

    results = {
        "phase": "production",
        "estimator": best_estimator,
        "config": best_config,
        "test_auc": test_auc,
        "model_path": str(model_path),
        "scaler_path": str(scaler_path),
        "top_features": sorted_features[:10],
        "shap_summary": {
            "mean_abs_shap": shap_results.get("mean_abs_shap_summary", {}),
        },
        "sample_explanations": explanations,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Save results
    output_path = Path("/home/z/my-project/scripts/automl_production_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info("production_complete", estimator=best_estimator, test_auc=f"{test_auc:.4f}")
    return results


def _build_model(estimator: str, config: Dict, y_train: np.ndarray):
    """Build the model based on AutoML discovery results."""
    pos_weight = len(y_train[y_train == 0]) / max(1, len(y_train[y_train == 1]))

    if estimator in ("xgboost", "xgb_limitdepth"):
        from xgboost import XGBClassifier
        return XGBClassifier(
            n_estimators=config.get("n_estimators", 300),
            max_depth=config.get("max_depth", 6),
            learning_rate=config.get("learning_rate", 0.05),
            subsample=config.get("subsample", 0.8),
            colsample_bytree=config.get("colsample_bytree", 0.7),
            scale_pos_weight=pos_weight,
            eval_metric="auc",
            early_stopping_rounds=30,
            random_state=42,
        )
    elif estimator == "lgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(
            n_estimators=config.get("n_estimators", 300),
            max_depth=config.get("max_depth", 6),
            learning_rate=config.get("learning_rate", 0.05),
            subsample=config.get("subsample", 0.8),
            colsample_bytree=config.get("colsample_bytree", 0.7),
            scale_pos_weight=pos_weight,
            objective="binary",
            random_state=42,
        )
    elif estimator == "catboost":
        from catboost import CatBoostClassifier
        return CatBoostClassifier(
            iterations=config.get("iterations", 300),
            depth=config.get("depth", 6),
            learning_rate=config.get("learning_rate", 0.05),
            scale_pos_weight=pos_weight,
            eval_metric="AUC",
            verbose=0,
            random_seed=42,
        )
    elif estimator == "rf":
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(
            n_estimators=config.get("n_estimators", 300),
            max_depth=config.get("max_depth", 10),
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
    else:
        from xgboost import XGBClassifier
        return XGBClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.05,
            scale_pos_weight=pos_weight, eval_metric="auc",
            random_state=42,
        )


def _compute_shap(model, X_test: np.ndarray, estimator: str) -> Dict:
    """Compute SHAP values for full explainability."""
    try:
        import shap
    except ImportError:
        logger.warning("shap_not_installed", hint="pip install shap")
        return {"mean_abs_shap": [0] * NUM_FEATURES}

    try:
        print(f"\n  Computing SHAP values (TreeExplainer)...")
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test[:100])  # Sample for speed

        # Handle LightGBM returning list of arrays
        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # Positive class

        mean_abs_shap = np.mean(np.abs(shap_values), axis=0)
        mean_abs_shap_dict = dict(zip(FEATURE_NAMES, mean_abs_shap.tolist()))

        print(f"  SHAP computed for {len(X_test[:100])} samples")
        print(f"\n  Top 10 Features (by mean |SHAP|):")
        sorted_shap = sorted(mean_abs_shap_dict.items(), key=lambda x: x[1], reverse=True)
        for name, val in sorted_shap[:10]:
            print(f"    {name:40s} {val:.6f}")

        return {
            "mean_abs_shap": mean_abs_shap.tolist(),
            "mean_abs_shap_summary": {k: round(v, 6) for k, v in mean_abs_shap_dict.items()},
        }
    except Exception as e:
        logger.warning("shap_failed", error=str(e))
        return {"mean_abs_shap": [0] * NUM_FEATURES}


def _generate_mfi_explanations(
    model, scaler, shap_results, X_samples, probas
) -> List[Dict]:
    """Generate MFI-ready text explanations for sample predictions.
    
    Format: "This vehicle scored 87 because:
      - lender_diversity = 3 (contributes +23 points)
      - temporal_velocity = 2 loans/week (contributes +18 points)
      - govt_plate_flag = 1 (contributes +15 points)"
    """
    explanations = []
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_samples)

        if isinstance(shap_values, list):
            shap_values = shap_values[1]

        for i in range(len(X_samples)):
            score = int(probas[i] * 100)
            sv = shap_values[i]

            # Sort by absolute SHAP value (biggest contributors first)
            contributors = sorted(
                zip(FEATURE_NAMES, sv),
                key=lambda x: abs(x[1]),
                reverse=True,
            )[:5]

            level = "CRITICAL" if score >= 80 else "HIGH" if score >= 60 else "MEDIUM" if score >= 40 else "LOW"
            recommendation = "REJECT_LOAN" if score >= 60 else "REVIEW_MANUALLY" if score >= 40 else "APPROVE_LOAN"

            explanation = {
                "vehicle_index": i,
                "risk_score": score,
                "risk_level": level,
                "recommendation": recommendation,
                "top_contributors": [
                    {
                        "feature": name,
                        "shap_value": round(float(val), 4),
                        "direction": "increases risk" if val > 0 else "decreases risk",
                        "contribution_points": round(abs(val) * 100, 1),
                    }
                    for name, val in contributors
                ],
                "mfi_text": f"This vehicle scored {score} ({level}) because:\n" +
                           "\n".join(
                               f"  - {name} = {X_samples[i][FEATURE_NAMES.index(name)]:.2f} "
                               f"(contributes {'+' if val > 0 else ''}{round(val*100, 1)} points)"
                               for name, val in contributors
                           ),
                "audit_trail": {
                    "model_type": type(model).__name__,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "regulatory_basis": "CBK Prudential Guidelines + Kenya Data Protection Act",
                },
            }
            explanations.append(explanation)

    except Exception as e:
        logger.warning("explanation_failed", error=str(e))

    return explanations


# ─── Full Pipeline ────────────────────────────────────────────────────

def run_full_pipeline(time_budget_minutes: int = 60) -> Dict:
    """Run the complete AutoML → SHAP pipeline."""
    print(f"\n{'='*70}")
    print(f" FLAML AutoML → SHAP Pipeline")
    print(f" Phase 1: Discovery (FLAML, {time_budget_minutes}min budget)")
    print(f" Phase 2: Production (SHAP explainability)")
    print(f"{'='*70}")

    # Generate or load data
    print("\n  Generating training data with 5% label noise...")
    X, y = generate_training_data(n_samples=5000, fraud_rate=0.05)
    print(f"    Samples: {len(X)}, Features: {X.shape[1]}, Fraud: {y.sum()} ({y.mean():.1%})")

    # Phase 1: Discovery
    discovery = phase1_discovery(X, y, time_budget_minutes=time_budget_minutes)

    if "error" in discovery:
        print("\n  FLAML failed. Using default XGBoost config for production.")
        discovery = None

    # Phase 2: Production with SHAP
    production = phase2_production(X, y, discovery_results=discovery)

    print(f"\n{'='*70}")
    print(f" Pipeline Complete")
    print(f"{'='*70}")

    if discovery and "error" not in discovery:
        print(f"  Discovery: {discovery['best_estimator']} (CV AUC: {discovery['best_auc_cv']:.4f})")
    print(f"  Production: {production['estimator']} (Test AUC: {production['test_auc']:.4f})")
    print(f"  Model saved: {production['model_path']}")

    return {
        "discovery": discovery,
        "production": production,
    }


# ─── Explain a Single Vehicle ────────────────────────────────────────

def explain_vehicle(plate: str, model_path: str = None) -> Dict:
    """Generate a full SHAP explanation for a single vehicle."""
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier

    model_path = model_path or "/home/z/my-project/scripts/risk_model_production.json"
    scaler_path = model_path.replace(".json", "_scaler_production.json")

    if not Path(model_path).exists():
        # Try the organic model
        model_path = "/home/z/my-project/scripts/risk_model_organic.json"
        scaler_path = "/home/z/my-project/scripts/risk_model_scaler_organic.json"

    if not Path(model_path).exists():
        # Try the real model
        model_path = "/home/z/my-project/scripts/risk_model_real.json"
        scaler_path = "/home/z/my-project/scripts/risk_model_scaler_real.json"

    model = XGBClassifier()
    model.load_model(model_path)

    # Build feature vector (placeholder — in production this comes from Neo4j)
    feature_vector = np.zeros((1, NUM_FEATURES))

    # Scale
    try:
        with open(scaler_path) as f:
            scaler_params = json.load(f)
        scaler = StandardScaler()
        scaler.mean_ = np.array(scaler_params["mean"])
        scaler.scale_ = np.array(scaler_params["scale"])
        feature_vector = scaler.transform(feature_vector)
    except Exception:
        pass

    # Predict
    proba = model.predict_proba(feature_vector)[0, 1]
    score = int(proba * 100)

    # SHAP
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(feature_vector)
        if isinstance(shap_values, list):
            shap_values = shap_values[1]

        contributors = sorted(
            zip(FEATURE_NAMES, shap_values[0]),
            key=lambda x: abs(x[1]),
            reverse=True,
        )[:5]
    except Exception:
        contributors = list(zip(FEATURE_NAMES[:5], [0]*5))

    level = "CRITICAL" if score >= 80 else "HIGH" if score >= 60 else "MEDIUM" if score >= 40 else "LOW"
    recommendation = "REJECT_LOAN" if score >= 60 else "REVIEW_MANUALLY" if score >= 40 else "APPROVE_LOAN"

    result = {
        "plate": plate,
        "risk_score": score,
        "risk_level": level,
        "recommendation": recommendation,
        "top_contributors": [
            {"feature": name, "shap_contribution": round(float(val), 4)}
            for name, val in contributors
        ],
        "audit_trail": {
            "model_path": model_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "regulatory_basis": "CBK Prudential Guidelines + Kenya DPA",
        },
    }

    print(f"\n  Vehicle: {plate}")
    print(f"  Risk Score: {score}/100 ({level})")
    print(f"  Recommendation: {recommendation}")
    print(f"\n  Top Contributors:")
    for name, val in contributors:
        direction = "↑ risk" if val > 0 else "↓ risk"
        print(f"    {name:40s} {val:+.4f} ({direction})")

    return result


# ─── Compare All Estimators ───────────────────────────────────────────

def compare_estimators(X: np.ndarray, y: np.ndarray) -> Dict:
    """Run a quick comparison of all estimators without FLAML."""
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    from sklearn.preprocessing import StandardScaler

    print(f"\n{'='*70}")
    print(f" Estimator Comparison (5-fold CV, no AutoML)")
    print(f"{'='*70}\n")

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    estimators = {}

    # XGBoost
    try:
        from xgboost import XGBClassifier
        estimators["xgboost"] = XGBClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.05,
            scale_pos_weight=len(y[y==0])/max(1, len(y[y==1])),
            eval_metric="auc", random_state=42,
        )
    except ImportError:
        pass

    # LightGBM
    try:
        from lightgbm import LGBMClassifier
        estimators["lgbm"] = LGBMClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.05,
            scale_pos_weight=len(y[y==0])/max(1, len(y[y==1])),
            objective="binary", random_state=42,
        )
    except ImportError:
        pass

    # CatBoost
    try:
        from catboost import CatBoostClassifier
        estimators["catboost"] = CatBoostClassifier(
            iterations=300, depth=6, learning_rate=0.05,
            scale_pos_weight=len(y[y==0])/max(1, len(y[y==1])),
            eval_metric="AUC", verbose=0, random_seed=42,
        )
    except ImportError:
        pass

    # Random Forest
    from sklearn.ensemble import RandomForestClassifier
    estimators["rf"] = RandomForestClassifier(
        n_estimators=300, max_depth=10, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    results = {}

    for name, model in estimators.items():
        start = time.time()
        scores = cross_val_score(model, X_scaled, y, cv=skf, scoring="roc_auc", n_jobs=-1)
        elapsed = time.time() - start
        results[name] = {
            "mean_auc": scores.mean(),
            "std_auc": scores.std(),
            "time_s": elapsed,
        }
        print(f"    {name:15s}  AUC: {scores.mean():.4f} ± {scores.std():.4f}  ({elapsed:.1f}s)")

    best = max(results.items(), key=lambda x: x[1]["mean_auc"])
    print(f"\n  Winner: {best[0]} (AUC: {best[1]['mean_auc']:.4f})")

    return results


# ─── Main ────────────────────────────────────────────────────────────

def main():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    parser = argparse.ArgumentParser(description="FLAML AutoML → SHAP Pipeline")
    parser.add_argument("--phase", choices=["discovery", "production", "full"],
                        default="full", help="Pipeline phase")
    parser.add_argument("--time-budget", type=int, default=60,
                        help="FLAML time budget in minutes")
    parser.add_argument("--explain", type=str, default="",
                        help="Explain a single vehicle by plate")
    parser.add_argument("--compare", action="store_true",
                        help="Compare all estimators")
    parser.add_argument("--data", type=str, default="",
                        help="Path to training data CSV")
    args = parser.parse_args()

    # Single vehicle explanation
    if args.explain:
        explain_vehicle(args.explain)
        return

    # Load data
    if args.data:
        df = pd.read_csv(args.data)
        X = df[FEATURE_NAMES].values
        y = df["is_fraud"].values
    else:
        X, y = generate_training_data()

    # Compare estimators
    if args.compare:
        compare_estimators(X, y)
        return

    # Phase-specific execution
    if args.phase == "discovery":
        phase1_discovery(X, y, time_budget_minutes=args.time_budget)
    elif args.phase == "production":
        # Try to load discovery results
        discovery_path = Path("/home/z/my-project/scripts/automl_discovery_results.json")
        discovery = None
        if discovery_path.exists():
            with open(discovery_path) as f:
                discovery = json.load(f)
        phase2_production(X, y, discovery_results=discovery)
    else:
        run_full_pipeline(time_budget_minutes=args.time_budget)


if __name__ == "__main__":
    main()

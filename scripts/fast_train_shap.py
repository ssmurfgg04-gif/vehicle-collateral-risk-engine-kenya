#!/usr/bin/env python3
"""
Fast FLAML → Manual Winner → SHAP pipeline.
Uses the organic fraud labels from organic_fraud_labels.py output.
Time budget: 2 minutes for FLAML search, then manual winner + SHAP.
"""

import json
import os
import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

# Load organic labels
LABELS_PATH = "/home/z/my-project/data/labels/organic_labels_20260814.csv"
VEHICLES_PATH = "/home/z/my-project/scripts/scrapers/data/all_vehicles_organic.json"
FRAUD_LABELS_PATH = "/home/z/my-project/scripts/scrapers/data/organic_fraud_labels.json"
OUTPUT_DIR = Path("/home/z/my-project/scripts/shap_plots")
OUTPUT_DIR.mkdir(exist_ok=True)
MODEL_DIR = Path("/home/z/my-project/scripts")

print()
print("=" * 70)
print(" FLAML AutoML → Manual Winner → SHAP Pipeline")
print("=" * 70)
print()

# ─── Step 1: Load Data ─────────────────────────────────────────────────────
print("[1/6] Loading organic vehicle data...")
with open(VEHICLES_PATH) as f:
    vehicles = json.load(f)

with open(FRAUD_LABELS_PATH) as f:
    fraud_labels = json.load(f)

print(f"  Loaded {len(vehicles)} vehicles, {len(fraud_labels)} fraud groups")

# ─── Step 2: Build Feature Matrix ──────────────────────────────────────────
print("[2/6] Building feature matrix...")

from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import cross_val_score, StratifiedKFold

rows = []
for v in vehicles:
    plate = v.get("normalized_plate", "")
    is_fraud = 1 if plate in fraud_labels else 0
    fraud_info = fraud_labels.get(plate, {})
    
    make = v.get("make", "")
    model = v.get("model", "")
    source = v.get("source", "")
    county = v.get("county_code", "")
    year = v.get("year", 2020)
    price = v.get("reserve_price_kes", 0) or 0
    confidence = v.get("confidence", 0.5)
    plate_cat = v.get("plate_category", "")
    listing_type = v.get("listing_type", "")
    
    row = {
        "normalized_plate": plate,
        "is_fraud": is_fraud,
        "fraud_confidence": fraud_info.get("confidence", 0.0),
        "n_overlap_sources": fraud_info.get("n_sources", 1),
        # Vehicle features
        "year": year,
        "vehicle_age": 2025 - year,
        "price_kes": price,
        "price_log": np.log1p(price),
        "confidence": confidence,
        # Plate features
        "is_govt_plate": 1 if plate_cat == "GOVERNMENT" else 0,
        "county_first_char": ord(county[0]) if county else 0,
        "county_second_char": ord(county[1]) if len(county) > 1 else 0,
        # Source features
        "source_is_bank": 1 if "bank" in source else 0,
        "source_is_mfi": 1 if "micro" in source else 0,
        "source_is_sacco": 1 if "sacco" in source else 0,
        "source_is_auction": 1 if "auction" in source or "warfare" in source else 0,
        "source_is_govt": 1 if "kra" in source or "gazette" in source or "govt" in source or "disposal" in source else 0,
        # Listing features
        "is_repossession": 1 if "REPOSSESSION" in listing_type else 0,
        "is_disposal": 1 if "DISPOSAL" in listing_type else 0,
        "is_auction_sale": 1 if "AUCTION" in listing_type else 0,
        # Interaction features
        "govt_no_doc_risk": (1 if plate_cat == "GOVERNMENT" else 0) * (1 - confidence),
        "price_per_year": price / max(year - 2000, 1),
        "multi_source_flag": 1 if is_fraud else 0,
    }
    rows.append(row)

df = pd.DataFrame(rows)
print(f"  Feature matrix: {df.shape[0]} rows × {df.shape[1]} columns")

# Features for model (drop plate and target)
feature_cols = [c for c in df.columns if c not in ("normalized_plate", "is_fraud")]
X = df[feature_cols].values.astype(np.float64)
y = df["is_fraud"].values.astype(np.int32)

# Replace any NaN/inf
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

print(f"  Features: {len(feature_cols)}, Fraud rate: {y.mean():.1%}")

# ─── Step 3: FLAML AutoML Search ───────────────────────────────────────────
print("[3/6] Running FLAML AutoML search (2min budget)...")
from flaml import AutoML

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

automl = AutoML()
t0 = time.time()
try:
    automl.fit(
        X_train=X, y_train=y,
        task="classification",
        time_budget=120,  # 2 minutes
        estimator_list=["lgbm", "rf", "xgboost"],
        metric="roc_auc",
        n_jobs=-1,
        verbose=0,
    )
    flaml_time = time.time() - t0
    best_estimator = automl.best_estimator
    best_config = automl.best_config
    best_val_score = 1 - automl.best_loss  # FLAML minimizes loss
    
    print(f"  FLAML completed in {flaml_time:.1f}s")
    print(f"  Best estimator: {best_estimator}")
    print(f"  Best AUC: {best_val_score:.4f}")
    print(f"  Best config: {json.dumps(best_config, indent=2, default=str)[:500]}")
except Exception as e:
    print(f"  FLAML failed: {e}")
    print("  Falling back to XGBoost direct training...")
    best_estimator = "xgboost"
    best_val_score = 0.0
    flaml_time = 0

# ─── Step 4: Train Manual Winner ───────────────────────────────────────────
print(f"[4/6] Training manual winner ({best_estimator}) with cross-validation...")

from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier

if best_estimator == "xgboost":
    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        verbosity=0,
    )
elif best_estimator == "lgbm":
    model = LGBMClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        verbose=-1,
    )
else:
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=10,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=-1,
    )

# Cross-validate
cv_aucs = cross_val_score(model, X, y, cv=skf, scoring="roc_auc")
print(f"  CV AUC: {cv_aucs.mean():.4f} ± {cv_aucs.std():.4f}")
print(f"  Per-fold: {[f'{a:.4f}' for a in cv_aucs]}")

# Train on full data for SHAP
model.fit(X, y)

# Save model
try:
    if hasattr(model, "save_model"):
        model.save_model(str(MODEL_DIR / "production_model.json"))
    else:
        import pickle
        with open(MODEL_DIR / "production_model.pkl", "wb") as f:
            pickle.dump(model, f)
    print(f"  Model saved to {MODEL_DIR}")
except Exception as e:
    print(f"  Model save error: {e}")

# ─── Step 5: SHAP Explainability ───────────────────────────────────────────
print("[5/6] Computing SHAP values...")

import shap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Configure fonts
import matplotlib.font_manager as fm
try:
    fm.fontManager.addfont('/usr/share/fonts/truetype/chinese/NotoSansSC[wght].ttf')
except Exception:
    pass
plt.rcParams['font.sans-serif'] = ['Noto Sans SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

try:
    # TreeExplainer for tree models
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)
    
    if isinstance(shap_values, list):
        shap_values = shap_values[1]  # Take positive class for binary
    
    # SHAP summary plot
    plt.figure(figsize=(12, 8))
    shap.summary_plot(shap_values, X, feature_names=feature_cols, show=False, max_display=20)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "shap_summary.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  SHAP summary saved: {OUTPUT_DIR / 'shap_summary.png'}")
    
    # SHAP bar plot (feature importance)
    plt.figure(figsize=(10, 8))
    shap.summary_plot(shap_values, X, feature_names=feature_cols, plot_type="bar", show=False, max_display=20)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "shap_importance_bar.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  SHAP importance bar saved: {OUTPUT_DIR / 'shap_importance_bar.png'}")
    
    # Top 5 waterfall plots for highest-risk vehicles
    risk_scores = model.predict_proba(X)[:, 1]
    top_indices = np.argsort(risk_scores)[-5:][::-1]
    
    for rank, idx in enumerate(top_indices):
        plt.figure(figsize=(10, 6))
        shap.waterfall_plot(shap.Explanation(
            values=shap_values[idx],
            base_values=explainer.expected_value if not isinstance(explainer.expected_value, list) else explainer.expected_value[1],
            data=X[idx],
            feature_names=feature_cols,
        ), show=False, max_display=15)
        plate = df.iloc[idx]["normalized_plate"]
        score = risk_scores[idx]
        plt.title(f"Vehicle {plate} — Risk Score: {score:.3f} (Rank #{rank+1})")
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / f"shap_waterfall_top{rank+1}_idx{idx}.png", dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Waterfall plot saved: top{rank+1} ({plate}, score={score:.3f})")
    
except Exception as e:
    print(f"  SHAP computation error: {e}")
    import traceback
    traceback.print_exc()

# ─── Step 6: Feature Importance Report ─────────────────────────────────────
print("[6/6] Generating feature importance report...")

try:
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    else:
        importances = np.zeros(len(feature_cols))
    
    feat_imp = sorted(zip(feature_cols, importances), key=lambda x: -x[1])
    
    report = {
        "model_type": best_estimator,
        "cv_auc_mean": float(cv_aucs.mean()),
        "cv_auc_std": float(cv_aucs.std()),
        "cv_folds": [float(a) for a in cv_aucs],
        "flaml_search_time_s": flaml_time,
        "flaml_best_estimator": best_estimator,
        "flaml_best_auc": float(best_val_score),
        "n_features": len(feature_cols),
        "n_records": len(df),
        "fraud_rate": float(y.mean()),
        "top_10_features": [(f, float(i)) for f, i in feat_imp[:10]],
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    
    report_path = MODEL_DIR / "training_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Report saved: {report_path}")
    
    print()
    print("=" * 70)
    print(" Training Complete")
    print("=" * 70)
    print(f"  Model:          {best_estimator}")
    print(f"  CV AUC:         {cv_aucs.mean():.4f} ± {cv_aucs.std():.4f}")
    print(f"  FLAML time:     {flaml_time:.1f}s")
    print(f"  Records:        {len(df)}")
    print(f"  Features:       {len(feature_cols)}")
    print(f"  Fraud rate:     {y.mean():.1%}")
    print()
    print("  Top 10 Features:")
    for i, (feat, imp) in enumerate(feat_imp[:10]):
        print(f"    {i+1:2d}. {feat:35s} {imp:.4f}")
    print()
    
except Exception as e:
    print(f"  Report error: {e}")

print("Done!")

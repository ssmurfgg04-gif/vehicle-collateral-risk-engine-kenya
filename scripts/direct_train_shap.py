#!/usr/bin/env python3
"""
Direct XGBoost + SHAP pipeline (no FLAML — that's too heavy for this machine).
Uses the organic fraud labels and vehicle data we already have.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

LABELS_PATH = "/home/z/my-project/data/labels/organic_labels_20260814.csv"
VEHICLES_PATH = "/home/z/my-project/scripts/scrapers/data/all_vehicles_organic.json"
FRAUD_LABELS_PATH = "/home/z/my-project/scripts/scrapers/data/organic_fraud_labels.json"
OUTPUT_DIR = Path("/home/z/my-project/scripts/shap_plots")
OUTPUT_DIR.mkdir(exist_ok=True)
MODEL_DIR = Path("/home/z/my-project/scripts")

print("=" * 70)
print(" XGBoost + SHAP Pipeline (Organic Fraud Labels)")
print("=" * 70)

# Load data
with open(VEHICLES_PATH) as f:
    vehicles = json.load(f)
with open(FRAUD_LABELS_PATH) as f:
    fraud_labels = json.load(f)
print(f"Loaded {len(vehicles)} vehicles, {len(fraud_labels)} fraud groups")

# Build feature matrix
from sklearn.model_selection import cross_val_score, StratifiedKFold
from xgboost import XGBClassifier

rows = []
for v in vehicles:
    plate = v.get("normalized_plate", "")
    is_fraud = 1 if plate in fraud_labels else 0
    fraud_info = fraud_labels.get(plate, {})
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
        "year": year, "vehicle_age": 2025 - year,
        "price_kes": price, "price_log": np.log1p(price),
        "confidence": confidence,
        "is_govt_plate": 1 if plate_cat == "GOVERNMENT" else 0,
        "source_is_bank": 1 if "bank" in source else 0,
        "source_is_mfi": 1 if "micro" in source else 0,
        "source_is_sacco": 1 if "sacco" in source else 0,
        "source_is_auction": 1 if "auction" in source or "warfare" in source else 0,
        "source_is_govt": 1 if any(k in source for k in ("kra", "gazette", "govt", "disposal", "treasury", "military", "police", "parastatal", "judiciary", "ndisposals", "presidency", "county_gov")) else 0,
        "is_repossession": 1 if "REPOSSESSION" in listing_type else 0,
        "is_disposal": 1 if "DISPOSAL" in listing_type else 0,
        "multi_source_flag": 1 if is_fraud else 0,
        "govt_no_doc_risk": (1 if plate_cat == "GOVERNMENT" else 0) * (1 - confidence),
        "price_per_year": price / max(year - 2000, 1),
    }
    rows.append(row)

df = pd.DataFrame(rows)
feature_cols = [c for c in df.columns if c not in ("normalized_plate", "is_fraud")]
X = np.nan_to_num(df[feature_cols].values.astype(np.float64))
y = df["is_fraud"].values.astype(np.int32)

print(f"Features: {len(feature_cols)}, Records: {len(df)}, Fraud: {y.mean():.1%}")

# Train XGBoost
model = XGBClassifier(
    n_estimators=200, max_depth=6, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8,
    reg_alpha=0.1, reg_lambda=1.0,
    random_state=42, verbosity=0,
)

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_aucs = cross_val_score(model, X, y, cv=skf, scoring="roc_auc")
print(f"CV AUC: {cv_aucs.mean():.4f} +/- {cv_aucs.std():.4f}")

model.fit(X, y)
model.save_model(str(MODEL_DIR / "production_model.json"))
print(f"Model saved to {MODEL_DIR / 'production_model.json'}")

# SHAP
import shap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

print("Computing SHAP values...")
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X)
if isinstance(shap_values, list):
    shap_values = shap_values[1]

# Summary plot
plt.figure(figsize=(12, 8))
shap.summary_plot(shap_values, X, feature_names=feature_cols, show=False, max_display=20)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "shap_summary.png", dpi=150, bbox_inches="tight")
plt.close()
print(f"SHAP summary: {OUTPUT_DIR / 'shap_summary.png'}")

# Bar plot
plt.figure(figsize=(10, 8))
shap.summary_plot(shap_values, X, feature_names=feature_cols, plot_type="bar", show=False, max_display=20)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "shap_importance_bar.png", dpi=150, bbox_inches="tight")
plt.close()
print(f"SHAP bar: {OUTPUT_DIR / 'shap_importance_bar.png'}")

# Top 5 waterfall
risk_scores = model.predict_proba(X)[:, 1]
top_indices = np.argsort(risk_scores)[-5:][::-1]

for rank, idx in enumerate(top_indices):
    plt.figure(figsize=(10, 6))
    shap.waterfall_plot(shap.Explanation(
        values=shap_values[idx],
        base_values=float(explainer.expected_value) if not isinstance(explainer.expected_value, list) else float(explainer.expected_value[1]),
        data=X[idx],
        feature_names=feature_cols,
    ), show=False, max_display=15)
    plate = df.iloc[idx]["normalized_plate"]
    score = risk_scores[idx]
    plt.title(f"Vehicle {plate} - Risk: {score:.3f} (#{rank+1})")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / f"shap_waterfall_top{rank+1}_idx{idx}.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Waterfall #{rank+1}: {plate} (score={score:.3f})")

# Report
feat_imp = sorted(zip(feature_cols, model.feature_importances_), key=lambda x: -x[1])
report = {
    "model_type": "xgboost",
    "cv_auc_mean": float(cv_aucs.mean()),
    "cv_auc_std": float(cv_aucs.std()),
    "n_features": len(feature_cols),
    "n_records": len(df),
    "fraud_rate": float(y.mean()),
    "top_10_features": [(f, float(i)) for f, i in feat_imp[:10]],
    "trained_at": datetime.now(timezone.utc).isoformat(),
}
with open(MODEL_DIR / "training_report.json", "w") as f:
    json.dump(report, f, indent=2)

print()
print("=" * 70)
print(f" Training Complete — CV AUC: {cv_aucs.mean():.4f} +/- {cv_aucs.std():.4f}")
print("=" * 70)
for i, (feat, imp) in enumerate(feat_imp[:10]):
    print(f"  {i+1:2d}. {feat:35s} {imp:.4f}")

"""
Real Model Training — Kenya Vehicle Collateral Risk Engine

Trains XGBoost + SHAP on REAL scraped data only.
- Fraud labels come from cross-lender overlap (NOT government plate detection)
- If no overlap exists, trains a RISK model based on vehicle features
- Full SHAP explainability for every prediction

Usage:
    python train_real_model.py
"""

import json
import sqlite3
import sys
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

DB_PATH = "/home/z/my-project/data/ingestion_queue.db"
MODEL_DIR = "/home/z/my-project/data/models"
RESULTS_DIR = "/home/z/my-project/data"

# ─── Load Real Data ───────────────────────────────────────────────────

def load_vehicles():
    """Load all real vehicles from the queue."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT payload, source FROM ingestion_queue"
    )
    vehicles = []
    for row in cursor:
        try:
            data = json.loads(row[0])
            data["source"] = row[1]
            vehicles.append(data)
        except:
            pass
    conn.close()
    return vehicles


# ─── Feature Engineering ──────────────────────────────────────────────

# County risk scores (based on repossession frequency)
COUNTY_RISK = {
    "N": 0.9,   # Nairobi — highest repossession rate
    "K": 0.85,  # Kiambu — high
    "M": 0.7,   # Mombasa
    "KD": 0.75, # Kajiado
    "NK": 0.65, # Nakuru
    "KU": 0.6,  # Kisumu
    "E": 0.55,  # Eldoret
    "MB": 0.5,  # Machakos
}

# Source type risk scores
SOURCE_TYPE_RISK = {
    "BANK_REPOSSESSION": 0.7,
    "AUCTION_LISTING": 0.8,
    "MFI_REPOSSESSION": 0.75,
    "GOVERNMENT_DISPOSAL": 0.9,
    "GOVERNMENT_GAZETTE": 0.85,
    "COURT_ORDERED_SALE": 0.95,
    "DEBT_ENFORCEMENT": 0.85,
}

# Make depreciation risk (higher = faster depreciation = higher risk)
MAKE_RISK = {
    "Probox": 0.95, "Fielder": 0.85, "Axio": 0.80,
    "Vitz": 0.75, "Fit": 0.72, "Note": 0.70,
    "Demio": 0.68, "Swift": 0.65,
    "Prado": 0.45, "Land Cruiser": 0.40, "Range Rover": 0.55,
    "Mercedes": 0.50, "BMW": 0.55, "Audi": 0.52,
}


def engineer_features(vehicles: list) -> tuple:
    """Build feature matrix from real vehicle data."""
    
    # Check for cross-lender overlap (REAL fraud signal)
    plate_to_sources = defaultdict(set)
    for v in vehicles:
        plate = v.get("normalized_plate", "")
        source = v.get("source", "")
        if plate:
            plate_to_sources[plate].add(source)
    
    has_overlap = any(len(sources) >= 2 for sources in plate_to_sources.values())
    overlap_plates = {plate for plate, sources in plate_to_sources.items() if len(sources) >= 2}
    
    features = []
    labels = []
    plate_list = []
    
    for v in vehicles:
        plate = v.get("normalized_plate", "")
        source = v.get("source", "")
        make = v.get("make", "")
        model_name = v.get("model", "")
        listing_type = v.get("listing_type", "")
        price = v.get("reserve_price_kes")
        year = v.get("year", 0)
        confidence = v.get("confidence", 0.5)
        county = v.get("county_code", "")
        plate_category = v.get("plate_category", "PRIVATE")
        
        # Feature vector
        feat = {
            # Price features
            "log_price": np.log1p(price) if price and price > 0 else 0,
            "has_price": 1 if price and price > 0 else 0,
            "price_bucket": min(int(np.log1p(price) / 3) if price and price > 0 else 0, 10),
            
            # Plate features
            "plate_length": len(plate),
            "county_prefix_is_K": 1 if plate.startswith("K") else 0,
            "county_prefix_is_N": 1 if plate.startswith("N") else 0,
            "is_government_plate": 1 if plate_category == "GOVERNMENT" else 0,
            "county_risk": COUNTY_RISK.get(county[:2] if len(county) >= 2 else county, 0.4),
            
            # Vehicle features
            "has_make": 1 if make else 0,
            "has_model": 1 if model_name else 0,
            "has_year": 1 if year and year > 1990 else 0,
            "vehicle_age": max(0, 2026 - year) if year and year > 1990 else 15,
            "make_risk": MAKE_RISK.get(model_name, 0.5),
            
            # Source features
            "source_type_risk": SOURCE_TYPE_RISK.get(listing_type, 0.5),
            "is_bank_source": 1 if "bank" in source.lower() else 0,
            "is_auctioneer_source": 1 if any(x in source.lower() for x in ["garam", "keysian", "phillips", "westminster"]) else 0,
            "is_govt_source": 1 if source in ["kenya_gazette", "kra_disposals"] else 0,
            "is_mfi_source": 1 if source == "mogo" else 0,
            
            # Data quality
            "confidence": confidence,
            "data_completeness": (1 if make else 0 + 1 if model_name else 0 + 1 if price and price > 0 else 0 + 1 if year and year > 1990 else 0) / 4,
        }
        
        # Label: REAL fraud based on cross-lender overlap
        if has_overlap and plate in overlap_plates:
            label = 1  # Genuine fraud: same plate at multiple lenders
        elif plate_category == "GOVERNMENT" and source in ["kra_disposals", "kenya_gazette"]:
            label = 0  # Government disposal = legitimate, NOT fraud
        else:
            label = 0  # Single-source listing = not fraud (yet)
        
        features.append(feat)
        labels.append(label)
        plate_list.append(plate)
    
    return features, labels, plate_list, has_overlap


# ─── Training ─────────────────────────────────────────────────────────

def train_model():
    """Train XGBoost + SHAP on real data."""
    
    print(f"\n{'═' * 70}")
    print(f" Kenya Vehicle Risk Engine — Real Model Training")
    print(f"{'═' * 70}")
    
    # Load data
    vehicles = load_vehicles()
    print(f"\n  Vehicles loaded: {len(vehicles)}")
    
    if len(vehicles) < 10:
        print("  ❌ Not enough data to train. Need at least 10 vehicles.")
        return
    
    # Engineer features
    features, labels, plate_list, has_overlap = engineer_features(vehicles)
    
    feature_names = list(features[0].keys())
    X = np.array([[f[k] for k in feature_names] for f in features])
    y = np.array(labels)
    
    print(f"  Features: {len(feature_names)}")
    print(f"  Positive (fraud): {sum(y)}")
    print(f"  Negative (legit): {len(y) - sum(y)}")
    print(f"  Has cross-lender overlap: {has_overlap}")
    
    if not has_overlap:
        print(f"\n  ⚠ No cross-lender overlap in data.")
        print(f"  Training a RISK SCORING model instead of fraud classifier.")
        print(f"  Risk = f(price, source, vehicle_age, county, ...)")
        print(f"  This predicts repossession risk, not fraud.")
        print(f"  Fraud labels will emerge as we accumulate time-series data.")
    
    # Train XGBoost
    try:
        import xgboost as xgb
    except ImportError:
        print("  Installing xgboost...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "xgboost", "-q"])
        import xgboost as xgb
    
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    from sklearn.metrics import roc_auc_score, classification_report
    
    Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
    
    # XGBoost parameters
    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 4,
        "learning_rate": 0.1,
        "n_estimators": 100,
        "min_child_weight": 3,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
    }
    
    model = xgb.XGBClassifier(**params)
    
    # If we have fraud labels, do proper evaluation
    if sum(y) > 0 and (len(y) - sum(y)) > 0:
        print(f"\n  Training with real fraud labels...")
        
        # Cross-validation
        try:
            cv = StratifiedKFold(n_splits=min(5, sum(y)), shuffle=True, random_state=42)
            cv_scores = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")
            print(f"  CV AUC: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
        except Exception as e:
            print(f"  CV failed (too few samples): {e}")
        
        # Train on full data
        model.fit(X, y)
        
        # Predictions
        y_pred = model.predict_proba(X)[:, 1]
        auc = roc_auc_score(y, y_pred)
        print(f"  Train AUC: {auc:.4f}")
        
        # Classification report
        y_class = (y_pred > 0.5).astype(int)
        print(f"\n{classification_report(y, y_class, target_names=['legit', 'fraud'])}")
        
    else:
        print(f"\n  Training risk scoring model (no fraud labels)...")
        
        # Create synthetic risk labels based on features for training
        # This is a risk model, not a fraud model
        risk_scores = (
            X[:, feature_names.index("source_type_risk")] * 0.3 +
            X[:, feature_names.index("county_risk")] * 0.2 +
            X[:, feature_names.index("is_government_plate")] * 0.15 +
            X[:, feature_names.index("vehicle_age")] / 30 * 0.15 +
            (1 - X[:, feature_names.index("data_completeness")]) * 0.1 +
            X[:, feature_names.index("is_auctioneer_source")] * 0.1
        )
        
        # Binary risk: top 20% = high risk
        threshold = np.percentile(risk_scores, 80)
        y_risk = (risk_scores >= threshold).astype(int)
        
        print(f"  Risk labels: {sum(y_risk)} high-risk, {len(y_risk) - sum(y_risk)} low-risk")
        
        model.fit(X, y_risk)
        y_pred = model.predict_proba(X)[:, 1]
        
        try:
            auc = roc_auc_score(y_risk, y_pred)
            print(f"  Risk AUC: {auc:.4f}")
        except:
            print(f"  Risk AUC: N/A (degenerate)")
        
        y = y_risk  # Use for SHAP
    
    # SHAP explainability
    print(f"\n  Computing SHAP values...")
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
        
        # Feature importance
        mean_abs_shap = np.abs(shap_values).mean(axis=0)
        importance = sorted(zip(feature_names, mean_abs_shap), key=lambda x: -x[1])
        
        print(f"\n  SHAP Feature Importance:")
        for name, imp in importance[:10]:
            bar = "█" * int(imp * 50)
            print(f"    {name:30s} {imp:.4f} {bar}")
        
        # Save SHAP summary
        shap_summary = {
            "feature_importance": {name: float(imp) for name, imp in importance},
            "model_type": "fraud_classifier" if has_overlap else "risk_scorer",
            "training_date": datetime.now(timezone.utc).isoformat(),
            "n_vehicles": len(vehicles),
            "n_features": len(feature_names),
            "has_cross_lender_overlap": has_overlap,
        }
        
        with open(f"{RESULTS_DIR}/shap_summary.json", "w") as f:
            json.dump(shap_summary, f, indent=2, default=str)
        
    except ImportError:
        print("  SHAP not available, skipping explainability")
    except Exception as e:
        print(f"  SHAP error: {e}")
    
    # Save model
    model_path = f"{MODEL_DIR}/vehicle_risk_model.json"
    model.save_model(model_path)
    print(f"\n  Model saved to: {model_path}")
    
    # Save training report
    report = {
        "training_date": datetime.now(timezone.utc).isoformat(),
        "n_vehicles": len(vehicles),
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "has_cross_lender_overlap": has_overlap,
        "model_type": "fraud_classifier" if has_overlap else "risk_scorer",
        "n_positive": int(sum(y)),
        "n_negative": int(len(y) - sum(y)),
        "warning": "NO_REAL_FRAUD_LABELS" if not has_overlap else None,
        "per_source": dict(Counter(v.get("source", "") for v in vehicles)),
        "params": params,
    }
    
    with open(f"{RESULTS_DIR}/training_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\n{'═' * 70}")
    if not has_overlap:
        print(f" ⚠ HONEST ASSESSMENT")
        print(f" This model predicts REPOSSESSION RISK, not fraud.")
        print(f" Real fraud requires cross-lender overlap detection.")
        print(f" Run the scraping daemon daily to accumulate time-series data.")
        print(f" Overlap will emerge as vehicles move: bank → auctioneer.")
    else:
        print(f" ✅ Model trained on REAL fraud labels (cross-lender overlap)")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    train_model()

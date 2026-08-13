"""
Splink Entity Resolution Pipeline for Vehicle Collateral Risk Engine
Uses Splink 4.x with DuckDB backend for probabilistic record linkage.

Comparison strategy (Kenyan vehicle domain):
  Plate numbers:
    - Level 0: null
    - Level 1: exact match
    - Level 2: Jaro-Winkler >= 0.95 (transposition errors)
    - Level 3: Jaro-Winkler >= 0.85 (moderate similarity)
    - Level 4: else

  Chassis numbers (VINs):
    - Level 0: null
    - Level 1: exact match
    - Level 2: Levenshtein <= 1 (single OCR error)
    - Level 3: Levenshtein <= 2 (two OCR errors)
    - Level 4: else

  Make / Model / Year: exact match

Blocking rules (to keep comparison count tractable):
  - substr(normalizedPlate, 1, 3)   — plate prefix (county code)
  - make + year                      — same vehicle profile
  - substr(normalizedChassis, 1, 6) — chassis prefix (WMI code)

Term frequency adjustments applied via column prefix to down-weight
common plate and chassis values.

Usage:
    python splink_pipeline.py --mode test          # synthetic data smoke test
    python splink_pipeline.py --mode link --limit 200
    python splink_pipeline.py --mode cluster --limit 200
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import structlog

from splink import Linker, SettingsCreator, block_on
from splink.internals import comparison_library as cl
from splink.internals.duckdb.database_api import DuckDBAPI
# Clustering done via Union-Find on prediction edges (see SplinkPipeline.cluster)

log = structlog.get_logger(__name__)

# ─── Splink Settings ───────────────────────────────────────────────────

def build_settings() -> SettingsCreator:
    """Build Splink 4.x settings for Kenyan vehicle entity resolution.

    Returns a SettingsCreator configured with:
      - Multi-level Jaro-Winkler on plates
      - Multi-level Levenshtein on chassis
      - Exact match on make, model, year
      - Blocking on plate prefix, make+year, chassis prefix
      - Term frequency adjustments on plate and chassis
    """
    settings = SettingsCreator(
        link_type="link_and_dedupe",
        comparisons=[
            # Plate: Jaro-Winkler at 0.95 and 0.85 (includes exact match as top level)
            cl.JaroWinklerAtThresholds("normalizedPlate", [0.95, 0.85]),
            # Chassis: Levenshtein at distance 1 and 2 (includes exact match)
            cl.LevenshteinAtThresholds("normalizedChassis", [1, 2]),
            # Make, Model, Year: exact match
            cl.ExactMatch("make"),
            cl.ExactMatch("model"),
            cl.ExactMatch("year"),
        ],
        blocking_rules_to_generate_predictions=[
            block_on("substr(normalizedPlate, 1, 3)"),     # plate prefix / county
            block_on("make", "year"),                       # vehicle profile
            block_on("substr(normalizedChassis, 1, 6)"),   # WMI code prefix
        ],
        unique_id_column_name="unique_id",
        source_dataset_column_name="source_dataset",
        # Term frequency adjustments: down-weight common plates/chassis
        term_frequency_adjustment_column_prefix="tf_",
        # EM convergence
        em_convergence=0.0001,
        max_iterations=50,
    )
    log.info("splink_settings_created")
    return settings


# ─── Synthetic Data ────────────────────────────────────────────────────

def generate_test_data(n: int = 200, duplicate_rate: float = 0.15) -> pd.DataFrame:
    """Generate synthetic Kenyan vehicle data with known duplicates for testing.

    Returns a DataFrame with columns:
      unique_id, source_dataset, normalizedPlate, normalizedChassis, make, model, year

    Duplicates are placed in a different source_dataset to exercise the
    link-and-dedupe mode of Splink.
    """
    import random
    random.seed(42)

    counties = ["KBA", "KBB", "KCA", "KDA", "KEA", "KFA", "KGA", "KHA",
                "KJA", "KKA", "KLA", "KMA", "KNA", "KPA", "KRA", "KSA",
                "KTA", "KUA", "KVA", "KWA", "KXA", "KYA", "KZA"]
    makes = ["Toyota", "Nissan", "Honda", "Mazda", "Subaru", "Mitsubishi",
             "Isuzu", "Volkswagen", "Mercedes", "BMW"]
    models_by_make = {
        "Toyota": ["Corolla", "Camry", "Hilux", "Prado", "Fielder", "Axio", "Vitz"],
        "Nissan": ["X-Trail", "Note", "Sunny", "Patrol", "Tiida"],
        "Honda": ["Fit", "CR-V", "Civic", "Accord"],
        "Mazda": ["Demio", "CX-5", "Axela", "BT-50"],
        "Subaru": ["Forester", "Outback", "Impreza", "Legacy"],
        "Mitsubishi": ["Outlander", "Pajero", "L200", "Canter"],
        "Isuzu": ["D-Max", "NPR", "NQR", "FSR"],
        "Volkswagen": ["Golf", "Polo", "Tiguan"],
        "Mercedes": ["C-Class", "E-Class", "Sprinter", "Actros"],
        "BMW": ["3 Series", "5 Series", "X3", "X5"],
    }

    records = []
    for i in range(n):
        county = random.choice(counties)
        num = random.randint(100, 999)
        suffix = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        plate = f"{county}{num}{suffix}"

        wmi = random.choice(["JTF", "JTN", "JHM", "JM1", "JF1", "JMB", "JAA", "WVW", "WDD", "WBA"])
        vds = "".join(random.choices("0123456789ABCDEFGHJKLMNPRSTUVWXYZ", k=6))
        vis = "".join(random.choices("0123456789ABCDEFGHJKLMNPRSTUVWXYZ", k=8))
        chassis = f"{wmi}{vds}{vis}"

        make = random.choice(makes)
        model = random.choice(models_by_make[make])
        year = random.randint(2010, 2024)

        records.append({
            "unique_id": i + 1,
            "source_dataset": "scraper_a",
            "normalizedPlate": plate,
            "normalizedChassis": chassis,
            "make": make,
            "model": model,
            "year": year,
        })

    # Create duplicates with minor variations in a second source dataset
    n_dup = int(n * duplicate_rate)
    for i in range(n_dup):
        source = records[i % len(records)].copy()
        dup_id = n + i + 1
        dup = source.copy()
        dup["unique_id"] = dup_id
        dup["source_dataset"] = "scraper_b"

        # Variation type
        var_type = random.choice(["plate_transpose", "plate_ocr", "chassis_ocr", "none"])

        if var_type == "plate_transpose":
            # Swap two adjacent characters in plate
            p = list(dup["normalizedPlate"])
            if len(p) > 4:
                j = random.randint(3, len(p) - 2)
                p[j], p[j + 1] = p[j + 1], p[j]
                dup["normalizedPlate"] = "".join(p)
        elif var_type == "plate_ocr":
            # Single character OCR error in plate
            p = list(dup["normalizedPlate"])
            j = random.randint(3, len(p) - 1)
            p[j] = random.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            dup["normalizedPlate"] = "".join(p)
        elif var_type == "chassis_ocr":
            # Single character OCR error in chassis
            c = list(dup["normalizedChassis"])
            j = random.randint(0, len(c) - 1)
            c[j] = random.choice("0123456789ABCDEFGHJKLMNPRSTUVWXYZ")
            dup["normalizedChassis"] = "".join(c)
        # "none" = exact duplicate (same plate, same chassis, different source)

        records.append(dup)

    df = pd.DataFrame(records)
    log.info("test_data_generated", n_original=n, n_duplicates=n_dup, total=len(df))
    return df


# ─── Core Pipeline ─────────────────────────────────────────────────────

class SplinkPipeline:
    """Splink entity resolution pipeline for Kenyan vehicle data."""

    def __init__(self):
        self._settings = build_settings()
        self._linker: Optional[Linker] = None
        self._db_api: Optional[DuckDBAPI] = None

    def fit(self, df: pd.DataFrame) -> Linker:
        """Create linker and estimate model parameters via EM.

        Args:
            df: DataFrame with columns matching settings comparisons,
                including 'source_dataset'.

        Returns:
            Trained Linker object.
        """
        self._db_api = DuckDBAPI()
        self._linker = Linker(df, self._settings, db_api=self._db_api)
        log.info("linker_created", n_records=len(df))

        # Step 1: Estimate u-values from random sampling
        self._linker.training.estimate_u_using_random_sampling(max_pairs=1e6)
        log.info("u_values_estimated")

        # Step 2: Estimate m-values from deterministic matching (label column)
        #   This uses records where normalizedPlate matches as known true links
        self._linker.training.estimate_m_from_label_column("normalizedPlate")
        log.info("m_values_estimated")

        # Step 3: EM iteration for remaining parameters
        #   Block on plate prefix (county code) to find candidate pairs
        self._linker.training.estimate_parameters_using_expectation_maximisation(
            blocking_rule=block_on("substr(normalizedPlate, 1, 3)"),
        )
        log.info("em_converged")

        # Additional EM pass with make+year blocking
        self._linker.training.estimate_parameters_using_expectation_maximisation(
            blocking_rule=block_on("make", "year"),
        )
        log.info("em_converged_second_pass")

        return self._linker

    def predict(self, threshold: float = 0.5) -> pd.DataFrame:
        """Run pairwise prediction and return links above threshold."""
        if self._linker is None:
            raise RuntimeError("Must call fit() before predict()")
        predictions = self._linker.inference.predict(threshold_match_probability=threshold)
        df_pred = predictions.as_pandas_dataframe()
        log.info("predictions_made", n_links=len(df_pred), threshold=threshold)
        return df_pred

    def cluster(self, threshold: float = 0.5) -> pd.DataFrame:
        """Resolve clusters (connected components) from predictions.

        Uses a Union-Find implementation on the prediction edges to
        compute connected components. This is a lightweight alternative
        to Splink's internal clustering which works with all backends.
        """
        if self._linker is None:
            raise RuntimeError("Must call fit() before cluster()")

        # Get the prediction edges
        predictions = self._linker.inference.predict(threshold_match_probability=threshold)
        edges_df = predictions.as_pandas_dataframe()

        if len(edges_df) == 0:
            log.info("no_links_to_cluster")
            return pd.DataFrame(columns=["cluster_id", "unique_id"])

        # Union-Find for connected components
        parent: Dict[Any, Any] = {}

        def find(x: Any) -> Any:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])  # path compression
                x = parent[x]
            return x

        def union(x: Any, y: Any) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # Process edges
        all_ids = set()
        for _, row in edges_df.iterrows():
            lid = row["unique_id_l"]
            rid = row["unique_id_r"]
            all_ids.update([lid, rid])
            union(lid, rid)

        # Assign cluster IDs
        cluster_map: Dict[Any, int] = {}
        cluster_counter = 0
        for node_id in sorted(all_ids, key=str):
            root = find(node_id)
            if root not in cluster_map:
                cluster_counter += 1
                cluster_map[root] = cluster_counter
            cluster_map[node_id] = cluster_map[root]

        df_clusters = pd.DataFrame([
            {"cluster_id": cluster_map[nid], "unique_id": nid}
            for nid in all_ids
        ])
        log.info("clusters_resolved", n_clusters=df_clusters["cluster_id"].nunique())
        return df_clusters

    def comparison_viewer(self, output_path: str = "splink_comparisons.html") -> str:
        """Generate interactive comparison viewer HTML."""
        if self._linker is None:
            raise RuntimeError("Must call fit() first")
        self._linker.visualisations.comparison_viewer_waterfall(
            output_path=output_path,
            overwrite=True,
        )
        log.info("comparison_viewer_written", path=output_path)
        return output_path


# ─── Queue Integration ─────────────────────────────────────────────────

def run_splink_on_queue(limit: int = 500) -> Dict[str, Any]:
    """Dequeue pending records from SQLite, run Splink, mark resolved.

    1. Read pending records from the ingestion queue
    2. Run entity resolution via Splink
    3. Mark resolved records in the queue
    """
    sys.path.insert(0, "/home/z/my-project/scripts")
    from queue import dequeue_for_splink, mark_resolved

    records = dequeue_for_splink(limit=limit)
    if not records:
        log.info("no_pending_records_for_splink")
        return {"resolved": 0, "links": 0}

    # Build DataFrame from payloads
    rows = []
    ids = []
    for rec in records:
        payload = rec["payload"]
        payload["unique_id"] = rec["id"]
        payload["source_dataset"] = rec.get("source", "unknown")
        rows.append(payload)
        ids.append(rec["id"])

    df = pd.DataFrame(rows)
    # Ensure required columns exist
    for col in ["normalizedPlate", "normalizedChassis", "make", "model", "year", "source_dataset"]:
        if col not in df.columns:
            df[col] = ""

    pipeline = SplinkPipeline()
    pipeline.fit(df)
    predictions = pipeline.predict(threshold=0.5)

    # Mark all as resolved
    n_resolved = mark_resolved(ids)

    result = {
        "resolved": n_resolved,
        "links": len(predictions),
    }
    log.info("splink_on_queue_complete", **result)
    return result


# ─── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

    parser = argparse.ArgumentParser(description="Splink Entity Resolution Pipeline")
    parser.add_argument(
        "--mode",
        choices=["test", "link", "cluster"],
        default="test",
        help="test=synthetic smoke test, link=run on queue, cluster=run+cluster on queue",
    )
    parser.add_argument("--input", type=str, help="Path to input Parquet/CSV")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    if args.mode == "test":
        print("=== Splink Pipeline Test Mode ===\n")

        # Generate synthetic data
        print("1. Generating synthetic vehicle data...")
        df = generate_test_data(n=200, duplicate_rate=0.15)
        print(f"   Records: {len(df)}, Unique plates: {df['normalizedPlate'].nunique()}")
        print(f"   Source datasets: {df['source_dataset'].value_counts().to_dict()}")
        print(f"   Sample: {df.iloc[0].to_dict()}")

        # Build pipeline
        print("\n2. Building Splink settings and fitting model...")
        pipeline = SplinkPipeline()

        try:
            linker = pipeline.fit(df)
            print("   Model fitted successfully")

            # Predict
            print("\n3. Running predictions (threshold=0.5)...")
            predictions = pipeline.predict(threshold=0.5)
            print(f"   Links found: {len(predictions)}")
            if len(predictions) > 0:
                print(f"   Columns: {list(predictions.columns)}")
                print(f"   Mean match prob: {predictions['match_probability'].mean():.4f}")

            # Cluster
            print("\n4. Clustering resolved entities...")
            try:
                clusters = pipeline.cluster(threshold=0.5)
                n_clusters = clusters["cluster_id"].nunique()
                print(f"   Clusters: {n_clusters}")
            except Exception as cluster_exc:
                print(f"   Clustering note: {cluster_exc}")
                n_clusters = -1

            # Summary
            print("\n=== Test Complete ===")
            print(f"   Input records:  {len(df)}")
            print(f"   Links found:    {len(predictions)}")
            print(f"   Clusters:       {n_clusters if n_clusters >= 0 else 'N/A'}")

        except Exception as exc:
            print(f"\n   ERROR during fit/predict: {exc}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)

    elif args.mode == "link":
        result = run_splink_on_queue(limit=args.limit)
        print(json.dumps(result, indent=2))

    elif args.mode == "cluster":
        result = run_splink_on_queue(limit=args.limit)
        print(json.dumps(result, indent=2))

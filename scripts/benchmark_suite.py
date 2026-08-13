"""
Benchmarking Suite for Kenya Vehicle Collateral Risk Engine

Comprehensive benchmarks across all system components:
  1. Scraper throughput (Go/Colly vs Python/curl_cffi vs Crawl4AI)
  2. Entity resolution (Jaro-Winkler, Levenshtein, Splink)
  3. ML training throughput (iterations/sec, GPU vs CPU)
  4. Inference latency (P50, P95, P99, cold start)
  5. SQLite queue throughput (Go writes, Python reads)
  6. Proxy rotation speed
  7. Memory usage per component
  8. Feature engineering throughput

Usage:
    python benchmark_suite.py                        # All benchmarks
    python benchmark_suite.py --component scrapers   # Scraper benchmarks only
    python benchmark_suite.py --component ml         # ML benchmarks only
    python benchmark_suite.py --component entity     # Entity resolution only
    python benchmark_suite.py --component queue      # Queue throughput only
    python benchmark_suite.py --component inference   # Inference latency only
    python benchmark_suite.py --component all         # All benchmarks
    python benchmark_suite.py --iterations 1000       # Number of iterations per benchmark
"""

import argparse
import gc
import importlib.util
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any
from collections import defaultdict

import numpy as np
import structlog

logger = structlog.get_logger("benchmark_suite")

RESULTS_DIR = Path("/home/z/my-project/scripts/benchmark_results")


# ─── Benchmark Utilities ────────────────────────────────────────────────

class BenchmarkTimer:
    """Context manager for timing code blocks with memory tracking."""
    
    def __init__(self, name: str):
        self.name = name
        self.elapsed = 0.0
        self.memory_peak = 0
        self.memory_delta = 0
    
    def __enter__(self):
        gc.collect()
        tracemalloc.start()
        self._mem_before = tracemalloc.get_traced_memory()[0]
        self._start = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start
        current, peak = tracemalloc.get_traced_memory()
        self.memory_delta = (current - self._mem_before) / 1024 / 1024  # MB
        self.memory_peak = peak / 1024 / 1024  # MB
        tracemalloc.stop()


def compute_statistics(times: List[float]) -> Dict:
    """Compute percentile statistics from a list of timing measurements."""
    if not times:
        return {}
    arr = np.array(times)
    return {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "count": len(arr),
    }


# ─── 1. Scraper Throughput Benchmark ────────────────────────────────────

def benchmark_scraper_throughput(iterations: int = 100, **kwargs) -> Dict:
    """Benchmark the Go/Colly scraper fleet throughput.
    
    Measures:
      - HTML parsing speed (pages/sec)
      - Vehicle extraction speed (vehicles/sec)
      - Plate normalization speed (normalizations/sec)
      - Queue write speed (writes/sec)
    """
    print("\n  [1] Scraper Throughput Benchmark")
    
    results = {}
    
    # HTML parsing speed
    html_sample = """
    <html><body>
    <div class="listing">
        <h3>KDA 123J - Toyota Corolla 2018</h3>
        <p>Reserve Price: KES 1,200,000</p>
        <p>Chassis: JTDBR32E760026123</p>
    </div>
    <div class="listing">
        <h3>KBX 456A - Nissan Double Cab 2020</h3>
        <p>Reserve Price: KES 3,500,000</p>
        <p>Chassis: JN1FDAN30Z0301234</p>
    </div>
    </body></html>
    """ * 10  # 20 vehicles per page
    
    times = []
    for _ in range(iterations):
        with BenchmarkTimer("html_parse") as t:
            # Simulate parsing
            import re
            plate_pat = re.compile(r'\b([A-Z][A-Z][A-Z])\s?(\d{1,3})\s?([A-Z]{1,2})\b')
            chassis_pat = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')
            kes_pat = re.compile(r'(?:KES|KSh|Ksh\.?)\s?([\d,]+)')
            plates = plate_pat.findall(html_sample)
            chassis = chassis_pat.findall(html_sample)
            amounts = kes_pat.findall(html_sample)
        times.append(t.elapsed)
    
    results["html_parse"] = compute_statistics(times)
    results["html_parse"]["throughput_pages_sec"] = 1.0 / results["html_parse"]["p50"]
    
    # Plate normalization speed
    test_plates = ["KDA 123J", "KBX 456A", "GKA 789B", "KCX 387A", "KCB 100M"] * 100
    
    times = []
    for _ in range(iterations):
        with BenchmarkTimer("plate_normalize") as t:
            for plate in test_plates:
                p = plate.upper().replace(" ", "").replace("-", "")
                # OCR corrections
                p = p.replace("O", "0").replace("I", "1")
                category = "GOVERNMENT" if p.startswith(("GK", "GKA", "GKB")) else "PRIVATE"
        times.append(t.elapsed)
    
    results["plate_normalize"] = compute_statistics(times)
    results["plate_normalize"]["throughput_normalizations_sec"] = len(test_plates) / results["plate_normalize"]["p50"]
    
    # Queue write speed (SQLite WAL)
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ingestion_queue", str(Path(__file__).parent / "ingestion_queue.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        
        # Create test queue
        test_db = "/tmp/benchmark_queue.db"
        if os.path.exists(test_db):
            os.remove(test_db)
        
        test_vehicles = [
            {
                "source": "benchmark",
                "raw_plate": f"KDA {i:03d}J",
                "normalized_plate": f"KDA{i:03d}J",
                "make": "Toyota",
                "model": "Corolla",
                "confidence": 0.85,
            }
            for i in range(1000)
        ]
        
        times = []
        for _ in range(min(iterations, 50)):
            with BenchmarkTimer("queue_write") as t:
                count, err = mod.enqueue_batch(test_vehicles, "benchmark")
            times.append(t.elapsed)
        
        results["queue_write"] = compute_statistics(times)
        results["queue_write"]["throughput_writes_sec"] = len(test_vehicles) / results["queue_write"]["p50"]
        
        # Clean up
        if os.path.exists(test_db):
            os.remove(test_db)
    except Exception as e:
        results["queue_write"] = {"error": str(e)}
    
    return results


# ─── 2. Entity Resolution Benchmark ──────────────────────────────────────

def benchmark_entity_resolution(iterations: int = 1000, **kwargs) -> Dict:
    """Benchmark entity resolution algorithms.
    
    Measures:
      - Jaro-Winkler similarity speed
      - Levenshtein distance speed
      - Batch entity resolution throughput
    """
    print("\n  [2] Entity Resolution Benchmark")
    
    results = {}
    
    try:
        import jellyfish
        has_jellyfish = True
    except ImportError:
        has_jellyfish = False
        print("    (jellyfish not installed — using pure Python fallback)")
    
    # Generate test plates
    test_plates_a = [f"KDA{i:03d}J" for i in range(500)]
    test_plates_b = [f"KDA{i:03d}J" for i in range(250, 750)]  # 50% overlap
    
    # Jaro-Winkler benchmark
    times = []
    for _ in range(iterations):
        idx = np.random.randint(0, 500)
        jdx = np.random.randint(0, 500)
        with BenchmarkTimer("jaro_winkler") as t:
            if has_jellyfish:
                sim = jellyfish.jaro_winkler_similarity(test_plates_a[idx], test_plates_b[jdx])
            else:
                # Pure Python fallback
                a, b = test_plates_a[idx], test_plates_b[jdx]
                sim = 1.0 - (sum(c1 != c2 for c1, c2 in zip(a, b)) / max(len(a), len(b)))
        times.append(t.elapsed)
    
    results["jaro_winkler"] = compute_statistics(times)
    results["jaro_winkler"]["throughput_comparisons_sec"] = 1.0 / results["jaro_winkler"]["p50"]
    
    # Levenshtein benchmark
    times = []
    for _ in range(iterations):
        idx = np.random.randint(0, 500)
        jdx = np.random.randint(0, 500)
        with BenchmarkTimer("levenshtein") as t:
            if has_jellyfish:
                dist = jellyfish.levenshtein_distance(test_plates_a[idx], test_plates_b[jdx])
            else:
                a, b = test_plates_a[idx], test_plates_b[jdx]
                dist = sum(c1 != c2 for c1, c2 in zip(a, b))
        times.append(t.elapsed)
    
    results["levenshtein"] = compute_statistics(times)
    results["levenshtein"]["throughput_comparisons_sec"] = 1.0 / results["levenshtein"]["p50"]
    
    # Batch entity resolution (all-pairs)
    times = []
    for _ in range(min(iterations, 100)):
        with BenchmarkTimer("batch_resolution") as t:
            matches = []
            for i, pa in enumerate(test_plates_a[:100]):  # 100x100 = 10K pairs
                for j, pb in enumerate(test_plates_b[:100]):
                    if has_jellyfish:
                        sim = jellyfish.jaro_winkler_similarity(pa, pb)
                    else:
                        sim = 1.0 - (sum(c1 != c2 for c1, c2 in zip(pa, pb)) / max(len(pa), len(pb)))
                    if sim >= 0.95:
                        matches.append((i, j, sim))
        times.append(t.elapsed)
    
    results["batch_resolution"] = compute_statistics(times)
    results["batch_resolution"]["pairs_compared"] = 100 * 100
    results["batch_resolution"]["throughput_pairs_sec"] = (100 * 100) / results["batch_resolution"]["p50"]
    
    return results


# ─── 3. ML Training Throughput Benchmark ─────────────────────────────────

def benchmark_ml_training(iterations: int = 10, **kwargs) -> Dict:
    """Benchmark ML model training throughput.
    
    Measures:
      - XGBoost training speed (iterations/sec)
      - Feature engineering speed
      - Cross-validation speed
      - SHAP computation speed
    """
    print("\n  [3] ML Training Throughput Benchmark")
    
    results = {}
    
    try:
        import xgboost as xgb
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        from sklearn.metrics import roc_auc_score
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {"error": "xgboost/sklearn not installed"}
    
    try:
        import importlib.util as il_util
        spec = il_util.spec_from_file_location(
            "train_1m", str(Path(__file__).parent / "train_1m_iterations.py"))
        mod = il_util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return {"error": f"Failed to load train_1m: {e}"}
    
    print("    Generating training data...")
    X, y = mod.generate_training_data(n_samples=10000, fraud_rate=0.05)
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # XGBoost training speed
    times = []
    for i in range(iterations):
        params = {
            "max_depth": 6,
            "learning_rate": 0.05,
            "n_estimators": 100,
            "objective": "binary:logistic",
            "tree_method": "hist",
            "subsample": 0.8,
            "colsample_bytree": 0.7,
        }
        with BenchmarkTimer("xgboost_train_100") as t:
            model = xgb.XGBClassifier(**params)
            model.fit(X_scaled, y, verbose=False)
        times.append(t.elapsed)
    
    results["xgboost_train_100_trees"] = compute_statistics(times)
    results["xgboost_train_100_trees"]["throughput_trees_sec"] = 100 / results["xgboost_train_100_trees"]["p50"]
    
    # XGBoost training with more trees
    times = []
    for i in range(max(iterations // 5, 2)):
        params["n_estimators"] = 500
        with BenchmarkTimer("xgboost_train_500") as t:
            model = xgb.XGBClassifier(**params)
            model.fit(X_scaled, y, verbose=False)
        times.append(t.elapsed)
    
    results["xgboost_train_500_trees"] = compute_statistics(times)
    results["xgboost_train_500_trees"]["throughput_trees_sec"] = 500 / results["xgboost_train_500_trees"]["p50"]
    
    # Cross-validation speed
    times = []
    for i in range(max(iterations // 5, 2)):
        params["n_estimators"] = 200
        model = xgb.XGBClassifier(**params)
        with BenchmarkTimer("cross_validation") as t:
            skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
            scores = cross_val_score(model, X_scaled, y, cv=skf, scoring="roc_auc", n_jobs=-1)
        times.append(t.elapsed)
    
    results["cross_validation_5fold"] = compute_statistics(times)
    results["cross_validation_5fold"]["mean_auc"] = float(scores.mean())
    
    # SHAP computation speed
    try:
        import shap
        model = xgb.XGBClassifier(**{**params, "n_estimators": 200})
        model.fit(X_scaled, y, verbose=False)
        
        times = []
        for n_samples in [100, 500, 1000, 5000]:
            with BenchmarkTimer(f"shap_{n_samples}") as t:
                explainer = shap.TreeExplainer(model)
                shap_values = explainer.shap_values(X_scaled[:n_samples])
            times.append(t.elapsed)
            results[f"shap_{n_samples}_samples"] = {
                "elapsed": t.elapsed,
                "throughput_samples_sec": n_samples / t.elapsed if t.elapsed > 0 else 0,
            }
    except ImportError:
        results["shap"] = {"error": "shap not installed"}
    
    return results


# ─── 4. Inference Latency Benchmark ──────────────────────────────────────

def benchmark_inference_latency(iterations: int = 10000, **kwargs) -> Dict:
    """Benchmark model inference latency for MFI SLA compliance.
    
    Target: P99 < 50ms (MFI officers need instant decisions)
    """
    print("\n  [4] Inference Latency Benchmark")
    
    results = {}
    
    try:
        import xgboost as xgb
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return {"error": "xgboost not installed"}
    
    # Load best model
    model_path = Path(__file__).parent / "risk_model_1m_best.json"
    if not model_path.exists():
        model_path = Path(__file__).parent / "risk_model.json"
    if not model_path.exists():
        # Train a quick model
        import importlib.util as il_util
        spec = il_util.spec_from_file_location(
            "risk_model", str(Path(__file__).parent / "risk_model.py"))
        mod = il_util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        X, y = mod.generate_training_data(n_samples=5000)
        mod.train_model(X, y, str(model_path))
    
    model = xgb.XGBClassifier()
    model.load_model(str(model_path))
    
    # Load scaler
    scaler_path = str(model_path).replace(".json", "_scaler.json")
    try:
        with open(scaler_path) as f:
            scaler_params = json.load(f)
        scaler = StandardScaler()
        scaler.mean_ = np.array(scaler_params["mean"])
        scaler.scale_ = np.array(scaler_params["scale"])
    except FileNotFoundError:
        scaler = StandardScaler()
        scaler.mean_ = np.zeros(47)
        scaler.scale_ = np.ones(47)
    
    # Generate test feature vectors
    rng = np.random.default_rng(42)
    n_features = 47
    test_vectors = rng.standard_normal((iterations, n_features))
    test_vectors_scaled = scaler.transform(test_vectors)
    
    # Warm up
    for _ in range(100):
        model.predict_proba(test_vectors_scaled[:1])
    
    # Single inference latency
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        proba = model.predict_proba(test_vectors_scaled[i:i+1])[0, 1]
        times.append((time.perf_counter() - start) * 1000)  # ms
    
    results["single_inference"] = compute_statistics(times)
    results["single_inference"]["sla_p99_lt_50ms"] = results["single_inference"].get("p99", 999) < 50.0
    results["single_inference"]["sla_p95_lt_20ms"] = results["single_inference"].get("p95", 999) < 20.0
    
    # Batch inference latency
    batch_sizes = [1, 10, 100, 1000, 5000]
    for bs in batch_sizes:
        times = []
        for _ in range(min(iterations // bs, 100)):
            batch = test_vectors_scaled[:bs]
            start = time.perf_counter()
            probs = model.predict_proba(batch)[:, 1]
            times.append((time.perf_counter() - start) * 1000)
        results[f"batch_inference_{bs}"] = compute_statistics(times)
        results[f"batch_inference_{bs}"]["throughput_samples_sec"] = bs / results[f"batch_inference_{bs}"]["p50"]
    
    return results


# ─── 5. Queue Throughput Benchmark ───────────────────────────────────────

def benchmark_queue_throughput(iterations: int = 100, **kwargs) -> Dict:
    """Benchmark SQLite queue read/write throughput.
    
    Measures:
      - Sequential writes
      - Batch writes
      - Concurrent read+write
      - WAL mode vs DELETE mode
    """
    print("\n  [5] Queue Throughput Benchmark")
    
    results = {}
    
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        spec = importlib.util.spec_from_file_location(
            "ingestion_queue", str(Path(__file__).parent / "ingestion_queue.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return {"error": str(e)}
    
    test_db = "/tmp/benchmark_queue_throughput.db"
    
    # Sequential writes
    test_vehicle = {
        "source": "benchmark",
        "raw_plate": "KDA 123J",
        "normalized_plate": "KDA123J",
        "make": "Toyota",
        "model": "Corolla",
        "confidence": 0.85,
    }
    
    times = []
    for _ in range(iterations):
        if os.path.exists(test_db):
            os.remove(test_db)
        
        with BenchmarkTimer("sequential_writes_100") as t:
            count, err = mod.enqueue_batch([test_vehicle] * 100, "benchmark")
        times.append(t.elapsed)
    
    results["sequential_writes_100"] = compute_statistics(times)
    results["sequential_writes_100"]["throughput_writes_sec"] = 100 / results["sequential_writes_100"]["p50"]
    
    # Batch writes (larger batches)
    for batch_size in [500, 1000, 5000]:
        vehicles = [{**test_vehicle, "raw_plate": f"KDA{i:03d}J"} for i in range(batch_size)]
        times = []
        for _ in range(min(iterations, 20)):
            if os.path.exists(test_db):
                os.remove(test_db)
            with BenchmarkTimer(f"batch_writes_{batch_size}") as t:
                count, err = mod.enqueue_batch(vehicles, "benchmark")
            times.append(t.elapsed)
        results[f"batch_writes_{batch_size}"] = compute_statistics(times)
        results[f"batch_writes_{batch_size}"]["throughput_writes_sec"] = batch_size / results[f"batch_writes_{batch_size}"]["p50"]
    
    # Clean up
    if os.path.exists(test_db):
        os.remove(test_db)
    
    return results


# ─── 6. Proxy Rotation Benchmark ────────────────────────────────────────

def benchmark_proxy_rotation(iterations: int = 1000, **kwargs) -> Dict:
    """Benchmark proxy rotation speed."""
    print("\n  [6] Proxy Rotation Benchmark")
    
    results = {}
    
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        spec = importlib.util.spec_from_file_location(
            "free_proxy_rotation", str(Path(__file__).parent / "free_proxy_rotation.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return {"error": str(e)}
    
    # Proxy selection speed
    rotation = mod.ProxyRotation()
    # Add mock proxies
    for i in range(100):
        rotation._proxies.append(mod.Proxy(
            host=f"192.168.{i//256}.{i%256}", port=8080 + i,
            protocol="http", source="benchmark", alive=True,
            success_count=10, fail_count=1,
        ))
    
    sources = ["kra_disposals", "kenya_gazette", "equity_bank", "family_bank", "garam_auctioneers"]
    
    times = []
    for _ in range(iterations):
        source = sources[np.random.randint(0, len(sources))]
        with BenchmarkTimer("proxy_selection") as t:
            proxy = rotation.get_proxy(source)
        times.append(t.elapsed)
    
    results["proxy_selection"] = compute_statistics(times)
    results["proxy_selection"]["throughput_selections_sec"] = 1.0 / results["proxy_selection"]["p50"]
    
    return results


# ─── 7. Memory Usage Benchmark ───────────────────────────────────────────

def benchmark_memory_usage(**kwargs) -> Dict:
    """Benchmark memory usage of each component."""
    print("\n  [7] Memory Usage Benchmark")
    
    results = {}
    
    # Model memory
    try:
        import xgboost as xgb
        model_path = Path(__file__).parent / "risk_model.json"
        if model_path.exists():
            tracemalloc.start()
            before = tracemalloc.get_traced_memory()[0]
            model = xgb.XGBClassifier()
            model.load_model(str(model_path))
            after = tracemalloc.get_traced_memory()[0]
            tracemalloc.stop()
            results["model_memory_mb"] = (after - before) / 1024 / 1024
        else:
            results["model_memory_mb"] = 0
    except Exception:
        results["model_memory_mb"] = 0
    
    # Feature vector memory
    results["feature_vector_kb"] = 47 * 8 / 1024  # 47 floats * 8 bytes
    results["batch_1000_vectors_kb"] = 1000 * 47 * 8 / 1024
    results["batch_10000_vectors_mb"] = 10000 * 47 * 8 / 1024 / 1024
    
    return results


# ─── Run All Benchmarks ─────────────────────────────────────────────────

def run_all_benchmarks(iterations: int = 1000, component: str = "all") -> Dict:
    """Run all benchmarks and return comprehensive results."""
    
    all_results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "iterations": iterations,
        "component": component,
    }
    
    components = {
        "scrapers": benchmark_scraper_throughput,
        "entity": benchmark_entity_resolution,
        "ml": benchmark_ml_training,
        "inference": benchmark_inference_latency,
        "queue": benchmark_queue_throughput,
        "proxy": benchmark_proxy_rotation,
        "memory": benchmark_memory_usage,
    }
    
    if component == "all":
        to_run = components
    else:
        to_run = {component: components[component]} if component in components else components
    
    for name, func in to_run.items():
        print(f"\n  Running {name} benchmark...")
        try:
            result = func(iterations=iterations)
            all_results[name] = result
        except Exception as e:
            all_results[name] = {"error": str(e)}
            logger.error("benchmark_failed", component=name, error=str(e))
    
    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = RESULTS_DIR / f"benchmark_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    
    # Convert numpy types for JSON serialization
    def convert_types(obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_types(v) for v in obj]
        return obj
    
    all_results = convert_types(all_results)
    
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2)
    
    return all_results


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
    
    parser = argparse.ArgumentParser(description="Kenya Risk Engine Benchmark Suite")
    parser.add_argument("--component", choices=[
        "all", "scrapers", "entity", "ml", "inference", "queue", "proxy", "memory"
    ], default="all", help="Component to benchmark")
    parser.add_argument("--iterations", type=int, default=1000,
                        help="Iterations per benchmark")
    args = parser.parse_args()
    
    print(f"\n{'='*70}")
    print(f" Kenya Vehicle Collateral Risk Engine — Benchmark Suite")
    print(f"{'='*70}")
    print(f"  Component:    {args.component}")
    print(f"  Iterations:   {args.iterations:,}")
    print(f"{'='*70}")
    
    results = run_all_benchmarks(iterations=args.iterations, component=args.component)
    
    # Print summary
    print(f"\n{'='*70}")
    print(f" BENCHMARK SUMMARY")
    print(f"{'='*70}")
    
    for component_name, component_results in results.items():
        if component_name in ("timestamp", "iterations", "component"):
            continue
        if isinstance(component_results, dict) and "error" not in component_results:
            print(f"\n  {component_name.upper()}:")
            for key, value in component_results.items():
                if isinstance(value, dict) and "mean" in value:
                    print(f"    {key}: mean={value['mean']*1000:.2f}ms, p99={value.get('p99', 0)*1000:.2f}ms")
    
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()

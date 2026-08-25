"""Synthetic resource benchmark for the partitioned factor pipeline."""

from __future__ import annotations

import argparse
import json
import resource
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import numpy as np
import pandas as pd

from backend.app.services.factors import factor_library_payload
from backend.app.workers.feature_materialization import (
    definition_fingerprint,
    materialize_partitioned_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=int, default=200)
    parser.add_argument("--rows-per-symbol", type=int, default=1913)
    parser.add_argument("--factors", type=int, default=87)
    args = parser.parse_args()

    library = factor_library_payload()[: args.factors]
    definitions = [
        SimpleNamespace(
            id=uuid5(NAMESPACE_URL, item["slug"]),
            slug=item["slug"],
            version=1,
            implementation=item["implementation"],
            parameters=item["parameters"],
        )
        for item in library
    ]
    count = args.symbols * args.rows_per_symbol
    symbol_codes = np.repeat([f"{index + 1:06d}" for index in range(args.symbols)], args.rows_per_symbol)
    dates = np.tile(pd.bdate_range("2018-01-01", periods=args.rows_per_symbol).to_numpy(), args.symbols)
    position = np.tile(np.arange(args.rows_per_symbol), args.symbols)
    asset = np.repeat(np.arange(args.symbols), args.rows_per_symbol)
    close = 8.0 + asset * 0.03 + position * 0.004 + np.sin(position / 17) * 0.25
    frame = pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol_codes,
            "open": close * 0.998,
            "high": close * 1.012,
            "low": close * 0.988,
            "close": close,
            "volume": 1_000_000 + (position % 100) * 10_000 + asset * 100,
            "amount": close * (1_000_000 + (position % 100) * 10_000 + asset * 100),
            "universe_member": True,
            "universe_rank": (asset % 200) + 1,
        }
    )

    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source, output, checkpoint = root / "source.parquet", root / "output.parquet", root / "parts"
        checkpoint.mkdir()
        frame.to_parquet(source, index=False)
        del frame
        fingerprint = definition_fingerprint("benchmark", definitions)
        result = materialize_partitioned_snapshot(
            source, output, checkpoint, definitions, fingerprint, {}
        )
        output_size = output.stat().st_size
    elapsed = time.perf_counter() - started
    peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        json.dumps(
            {
                "rows": count,
                "symbols": args.symbols,
                "factors": args.factors,
                "elapsed_seconds": round(elapsed, 3),
                "peak_rss_mib": round(peak_kib / 1024, 1),
                "output_mib": round(output_size / 1024 / 1024, 1),
                "computed_partitions": result.computed_partitions,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

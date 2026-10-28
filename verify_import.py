#!/usr/bin/env python3
"""
FHIR Import Verify & Repair Script
Checks that every resource in the NDJSON files exists on the HAPI FHIR server
(by resource ID) and, with --repair, uploads the missing ones with PUT in
transaction bundles. Safe to re-run: PUT by ID overwrites rather than duplicates.
"""

import argparse
import gzip
import json
import os
import sys
from typing import Dict, Iterator, List, Set

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class FHIRImportVerifier:
    """Compares local NDJSON files with the resources stored on a FHIR server."""

    def __init__(
        self,
        fhir_base_url: str = "http://localhost:8080/fhir",
        check_batch_size: int = 500,
        repair_batch_size: int = 500,
    ):
        self.fhir_base_url = fhir_base_url.rstrip("/")
        self.check_batch_size = check_batch_size
        self.repair_batch_size = repair_batch_size
        self.session = requests.Session()

        # HAPI returns 5xx when the database drops a pooled connection (seen
        # with Neon); retrying makes it use a fresh connection.
        retry = Retry(
            total=6,
            backoff_factor=2,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=None,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def read_batches(self, path: str) -> Iterator[List[Dict]]:
        """Yield resources from an NDJSON(.gz) file in batches."""
        opener = gzip.open if path.endswith(".gz") else open
        batch = []
        with opener(path, "rt") as f:
            for line in f:
                if line.strip():
                    batch.append(json.loads(line))
                if len(batch) == self.check_batch_size:
                    yield batch
                    batch = []
        if batch:
            yield batch

    def existing_ids(self, resource_type: str, ids: List[str]) -> Set[str]:
        """Return which of the given IDs exist on the server."""
        # POST _search keeps long _id lists out of the URL
        response = self.session.post(
            f"{self.fhir_base_url}/{resource_type}/_search",
            data={"_id": ",".join(ids), "_elements": "id", "_count": str(len(ids))},
            headers={"Accept": "application/fhir+json"},
            timeout=300,
        )
        response.raise_for_status()
        return {e["resource"]["id"] for e in response.json().get("entry", [])}

    def upload(self, resources: List[Dict]):
        """PUT resources by ID in transaction bundles."""
        for i in range(0, len(resources), self.repair_batch_size):
            bundle = {
                "resourceType": "Bundle",
                "type": "transaction",
                "entry": [
                    {
                        "resource": r,
                        "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"},
                    }
                    for r in resources[i : i + self.repair_batch_size]
                ],
            }
            response = self.session.post(
                self.fhir_base_url,
                json=bundle,
                headers={"Content-Type": "application/fhir+json"},
                timeout=600,
            )
            response.raise_for_status()

    def verify_file(self, path: str, repair: bool) -> Dict:
        """Check one file; optionally upload its missing resources."""
        total, missing = 0, []
        for batch in self.read_batches(path):
            found = self.existing_ids(batch[0]["resourceType"], [r["id"] for r in batch])
            missing.extend(r for r in batch if r["id"] not in found)
            total += len(batch)

        repaired = 0
        if repair and missing:
            self.upload(missing)
            repaired = len(missing)

        return {"total": total, "missing": len(missing), "repaired": repaired}


def main():
    parser = argparse.ArgumentParser(
        description="Verify NDJSON resources exist on a HAPI FHIR server and repair gaps"
    )
    parser.add_argument(
        "--fhir-url",
        default="http://localhost:8080/fhir",
        help="FHIR server base URL (default: http://localhost:8080/fhir)",
    )
    parser.add_argument(
        "--fhir-dir",
        default="./input_data/fhir",
        help="Directory containing NDJSON files (default: ./input_data/fhir)",
    )
    parser.add_argument("--files", nargs="+", help="Specific files to check (default: all)")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Upload missing resources (default: only report them)",
    )
    args = parser.parse_args()

    files = args.files or sorted(
        f
        for f in os.listdir(args.fhir_dir)
        if f.endswith((".ndjson", ".ndjson.gz")) and not f.startswith(".")
    )
    if not files:
        print(f"No NDJSON files found in {args.fhir_dir}")
        sys.exit(1)

    verifier = FHIRImportVerifier(args.fhir_url)
    mode = "verify + repair" if args.repair else "verify only"
    print(f"Checking {len(files)} files against {args.fhir_url} ({mode})")
    print("-" * 78)
    print(f"  {'File':<44} {'Total':>10} {'Missing':>10} {'Repaired':>10}")

    totals = {"total": 0, "missing": 0, "repaired": 0}
    for filename in files:
        result = verifier.verify_file(os.path.join(args.fhir_dir, filename), args.repair)
        for key in totals:
            totals[key] += result[key]
        print(
            f"  {filename:<44} {result['total']:>10} {result['missing']:>10} {result['repaired']:>10}",
            flush=True,
        )

    print("-" * 78)
    print(f"  {'TOTAL':<44} {totals['total']:>10} {totals['missing']:>10} {totals['repaired']:>10}")

    unresolved = totals["missing"] - totals["repaired"]
    if unresolved:
        print(f"\n{unresolved} resources missing. Re-run with --repair to upload them.")
        sys.exit(1)
    print("\nAll resources present.")


if __name__ == "__main__":
    main()

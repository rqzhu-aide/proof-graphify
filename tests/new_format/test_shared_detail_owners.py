"""Exercise Python acceptance against the same shared-owner pages checked by JS."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared"))
from paper_core.publish import _Scan, _visible_failures, _reader_failures, _reader_fields


class SharedDetailOwnerTests(unittest.TestCase):
    def test_distinct_owners_reader_placement_and_tampering(self):
        result = subprocess.run(
            [shutil.which("node") or "node", str(ROOT / "shared/paper_core/renderer/shared_detail_test.mjs"), "--json"],
            capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        for case in json.loads(result.stdout):
            with self.subTest(case=case["name"]):
                scan = _Scan()
                scan.feed(case["html"])
                scan.close()
                failures = _visible_failures(scan, case["projection"], build=case["build"])
                # These JS fixtures carry hand-authored math fragments rather than
                # Python's generated fragments. Exercise the owned acceptance
                # checks independently of that unrelated rendering convention.
                reader_failures = _reader_failures(scan, case["projection"])
                owner_failures = [failure for failure in reader_failures if "owner" in failure
                                  or "missing or duplicated" in failure or "unexpected reader field" in failure]
                if case["valid"]:
                    self.assertEqual(failures + owner_failures, [])
                elif case["name"] == "reader-moved-to-unmatched-owner":
                    self.assertTrue(any("different owner" in failure for failure in owner_failures))
                else:
                    self.assertTrue(any("visible assessment" in failure for failure in failures), failures)
                if case["name"] == "reader-only-for-matching-owner":
                    expected = _reader_fields(case["projection"])
                    self.assertTrue(any(key[1] == "legacy" for key in expected))


if __name__ == "__main__":
    unittest.main()

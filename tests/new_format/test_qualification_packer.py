"""Execute the documented packer: isolation gates grades and bytes stay evidence."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

from support import Fixture
from paper_core import review

DOC = Path(__file__).resolve().parents[2] / "stat-proof-check/references/database-qualification.md"


class QualificationPackerTests(unittest.TestCase):
    def pack(self, *, isolation=True, omit_isolation=False, outcomes=("pass", "pass"), classes=("valid", "invalid")):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fx = Fixture(root)
            evidence_dir = root / "work/qualification/calibration-1"
            evidence_dir.mkdir(parents=True)
            grading = {
                "request_id": "req_packer", "qualification_id": "qua_packer", "reviewer": "fixture-checker",
                "profile": {"provider": "fixture", "model": "fixture", "effort": None, "tools": [],
                            "context_isolation": "Synthetic packer test, no reviewer dispatched"},
                "protocol_version": "item-audit/1", "limitations": ["Mechanical fixture only"], "cases": [],
            }
            if not omit_isolation:
                grading["calibration_isolated"] = isolation
            preserved = {}
            for index, (case_class, outcome) in enumerate(zip(classes, outcomes)):
                raw = (f'{{ "case": {index}, "response": "original bytes" }}\r\n').encode()
                filename = f"response-{index}.json"
                (evidence_dir / filename).write_bytes(raw)
                preserved[hashlib.sha256(raw).hexdigest()] = raw
                grading["cases"].append({"case_id": f"case-{index}", "class": case_class,
                                         "outcome": outcome, "response_path": filename})
            evidence_bytes = (json.dumps(grading, indent=3) + "\n").encode()
            (evidence_dir / "qualification-grading.json").write_bytes(evidence_bytes)
            preserved[hashlib.sha256(evidence_bytes).hexdigest()] = evidence_bytes
            snippet = re.findall(r"```python\n(.*?)\n```", DOC.read_text(encoding="utf-8"), re.S)[0]
            previous = Path.cwd()
            try:
                os.chdir(root)
                exec(compile(snippet, str(DOC), "exec"), {})
            finally:
                os.chdir(previous)
            receipt = json.loads((evidence_dir / "receipt.json").read_bytes())
            decoded = {b["sha256"]: base64.b64decode(b["data"]) for b in receipt["blobs"]}
            self.assertEqual(preserved, decoded)
            body = receipt["edits"][0]["body"]
            self.assertNotIn("calibration_isolated", body)
            self.assertEqual(evidence_bytes, decoded[body["evidence_blob"]])
            # The generated receipt uses the existing qualification contract unchanged.
            with fx.open() as db:
                review.record_qualification(db, receipt=receipt)
                self.assertEqual(body, db.head("qualifications", "qua_packer").body)
            return copy.deepcopy(body)

    def test_only_explicit_isolation_with_balanced_passing_grades_qualifies(self):
        for value in (False, None, 0, 1, "true", "false", [], {"isolated": True}):
            with self.subTest(isolation=value):
                self.assertIs(self.pack(isolation=value)["qualified"], False)
        self.assertIs(self.pack(omit_isolation=True)["qualified"], False)
        self.assertIs(self.pack(isolation=True)["qualified"], True)

    def test_isolation_does_not_replace_balanced_passing_cases(self):
        for outcomes in (("fail", "pass"), ("pass", "inconclusive")):
            with self.subTest(outcomes=outcomes):
                self.assertIs(self.pack(outcomes=outcomes)["qualified"], False)
        self.assertIs(self.pack(classes=("valid",), outcomes=("pass",))["qualified"], False)
        self.assertIs(self.pack(classes=("invalid",), outcomes=("pass",))["qualified"], False)


if __name__ == "__main__":
    unittest.main()

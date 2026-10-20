"""Current role delivery, context limits, and separately retained legacy identity."""
import json
import re
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO = SKILL_ROOT.parent
REFERENCES = SKILL_ROOT / "references"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
from paper_core import CORE_VERSION, PROTOCOL_VERSION
from paper_core.assistance import ROLE_REFERENCES, worker_guidance


class SkillStructureTests(unittest.TestCase):
    def test_current_release_surfaces_agree(self):
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        manifest = json.loads((SKILL_ROOT / "scripts/paper_core/bundle-manifest.json").read_text(encoding="utf-8"))
        skill_version = re.search(r'(?m)^\s+version: "([^"]+)"$', skill).group(1)
        self.assertEqual(re.search(r'(?m)^\| `stat-proof-check` \| v([^ |]+)', readme).group(1), skill_version)
        self.assertEqual(manifest["core_version"], CORE_VERSION)
        self.assertEqual(manifest["protocol_version"], PROTOCOL_VERSION)

    def test_legacy_runtime_keeps_its_own_identity(self):
        script = (SKILL_ROOT / "scripts/proofcheck.py").read_text(encoding="utf-8")
        examples = json.loads((SKILL_ROOT / "assets/templates/AUDIT_RECORD_EXAMPLES.json").read_text(encoding="utf-8"))
        report = (SKILL_ROOT / "assets/templates/FINAL_REPORT.md").read_text(encoding="utf-8")
        self.assertEqual(re.search(r'(?m)^SKILL_VERSION\s*=\s*"([^"]+)"', script).group(1), "1.5")
        self.assertEqual(examples["skill_version"], "1.5")
        self.assertEqual(examples["manifest_report_deliverables_example"]["protocol"]["skill_version"], "1.5")
        self.assertEqual(re.search(r'(?m)^- Skill version:\s+(\S+)', report).group(1), "1.5")

    def test_explicit_invocation_policy_is_retained(self):
        metadata = (SKILL_ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        self.assertRegex(metadata, r"allow_implicit_invocation:\s*false")
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Use only when explicitly invoked as $stat-proof-check", skill)

    def test_dispatch_contract_includes_scientific_core_without_coordinator_material(self):
        private = {"database-audit.md", "controller-workflow.md", "database-qualification.md",
                   "review-mapping.md", "coordinator-protocol.md", "graph-records.md"}
        for mode in ("primary", "independent"):
            guide = worker_guidance(mode)
            self.assertEqual(guide["reference_files"], list(ROLE_REFERENCES[mode]))
            self.assertTrue({"mathematical-checking.md", "evidence-and-verdicts.md"} <= set(guide["reference_files"]))
            self.assertFalse(private.intersection(guide["reference_files"]))
            for name in guide["reference_files"]:
                self.assertTrue((REFERENCES / name).is_file(), name)

    def test_routine_instructions_and_generated_shape_do_not_exceed_selected_baseline(self):
        # Existing entrypoint included conservatively, even when a delegated worker
        # receives only its brief. Actual packets/scaffolds are measured separately.
        entry = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        # Reviewed 3.3.5 readsets, reduced from 5913/6084 by consolidating repetition.
        # Retain the scientific and response contracts added since the 3.0.11 baseline;
        # keep all assigned references in the measurement and allow no growth margin.
        limits = {"primary": 5671, "independent": 5854}
        for mode, limit in limits.items():
            materials = [entry, *( (REFERENCES / name).read_text(encoding="utf-8")
                                  for name in ROLE_REFERENCES[mode]),
                         json.dumps(worker_guidance(mode), indent=2)]
            words = sum(len(material.split()) for material in materials)
            self.assertLessEqual(words, limit, (mode, words, limit))

    def test_current_reference_links_resolve(self):
        names = set(sum((list(paths) for paths in ROLE_REFERENCES.values()), [])) | {
            "database-audit.md", "controller-workflow.md", "graph-records.md",
            "coordinator-protocol.md", "review-mapping.md", "database-compatibility.md", "supplied-route-review.md"}
        for path in [SKILL_ROOT / "SKILL.md", *(REFERENCES / name for name in names)]:
            for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if "://" not in link and not link.startswith("#"):
                    self.assertTrue((path.parent / link.split("#", 1)[0]).exists(), (path.name, link))


if __name__ == "__main__":
    unittest.main()

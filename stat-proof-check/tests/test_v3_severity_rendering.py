"""Real coherent publication covers rated cards, uncertainty and legacy saved prose."""
from html.parser import HTMLParser
import re

from support import Fixture, R, TempCase, edit, node_available
from paper_core import finalization, projection, publish, review


LEGACY_TEXT = " ".join(f"Saved legacy observation {i}: the original detailed mathematical explanation remains available." for i in range(1, 13))
MINOR_DESCRIPTION = ("The sentence reverses the tuning relationship.\n"
    r"\[\lambda_n(\tau)=n^{-1/[2(\tau+2)]},\qquad"
    r"\frac{\partial}{\partial\tau}\log\lambda_n(\tau)="
    r"\frac{\log n}{2(\tau+2)^2}>0\quad(n>1,\ 0<\tau\le1).\]")


def badge_contrast(css):
    """Resolve the current badge rules statically and measure sRGB contrast."""
    # Print deliberately uses light tokens in either theme. Those rules must
    # not override screen colors in this small static screen-contrast probe.
    for match in reversed(list(re.finditer(r'@media\s+print\s*\{', css))):
        end, depth = match.end(), 1
        while depth and end < len(css):
            depth += (css[end] == "{") - (css[end] == "}")
            end += 1
        css = css[:match.start()] + css[end:]
    rules = re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', css, flags=re.S))
    colors = ("red", "orange", "yellow", "green", "gray")
    variables = {"light": {}, "dark": {}}
    for selector, body in rules:
        if "proof-reader" in selector or "svg.proof-audit" in selector:
            theme = "dark" if 'data-theme="dark"' in selector else "light"
            variables[theme].update(re.findall(r'(--[\w-]+):([^;}]+)', body))

    def luminance(value):
        rgb = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
        return sum(w * x for w, x in zip((0.2126, 0.7152, 0.0722), linear))

    rows = []
    for theme in variables:
        for color in colors:
            properties = {}
            for selector, body in rules:
                if "proof-state-badge" not in selector or ".s-" + color not in selector:
                    continue
                if 'data-theme="dark"' in selector and theme != "dark":
                    continue
                properties.update({key: value for key, value in re.findall(r'([\w-]+):([^;}]+)', body)
                                   if key in ("color", "background")})
            foreground, background = [variables[theme][value[4:-1]] if value.startswith("var(") else value
                                      for value in (properties["color"], properties["background"])]
            high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
            rows.append({"theme": theme, "color": color, "foreground": foreground, "background": background,
                         "ratio": (high + 0.05) / (low + 0.05)})
    return rows


def build_severity_fixture(root):
    """Only software test data; the examination prose is explicitly synthetic."""
    fx = Fixture(root, title="Synthetic severity UI validation").primary()
    with fx.open() as db:
        edits = []
        for name, label in (("severe", "Theorem 5: Severe"), ("checked", "Proposition 6: Checked"),
                            ("unresolved", "Lemma 7: Unresolved"), ("legacy", "Lemma 8: Legacy")):
            edits += [fx.item_edit(f"itm_{name}", "theorem", label, "anc_thm", "anc_thm_proof"),
                      fx.argument_edit(f"arg_{name}", f"itm_{name}", f"grp_{name}", "anc_thm_proof"),
                      fx.group_edit(f"grp_{name}", f"arg_{name}", f"itm_{name}", "anc_thm_proof"),
                      edit("create", "target_specs", f"tgt_{name}", {
                          "target": R("items", f"itm_{name}"), "statement_ref": {"collection": "items", "id": f"itm_{name}", "version": 1},
                          "statement": None, "scope_id": None, "evidence_refs": ["anc_thm"],
                          "state": "registered", "fidelity_ref": None}),
                      edit("create", "proof_boundaries", f"bnd_{name}", {
                          "target": R("items", f"itm_{name}"), "argument_ids": [f"arg_{name}"],
                          "anchor_refs": [db.head("anchors", "anc_thm_proof").pinned],
                          "source_review_ref": db.head("source_reviews", "srv_boundaries").pinned,
                          "state": "complete"})]
        fx.apply(db, edits)
        audit = db.head("audits", fx.audit_id)
        names = ("lem", "thm", "severe", "checked", "unresolved", "legacy")
        fx.apply(db, [edit("replace", "audits", audit.id,
            dict(audit.body, independent_required=False, targets=[R("items", f"itm_{n}") for n in names]), audit.version)],
            "audits:" + fx.audit_id, mode="primary")
        fx.apply(db, [fx.check_edit(f"chk_comp_{name}", R("arguments", f"arg_{name}"), "composition",
                     outcome="inconclusive" if name == "unresolved" else "supported", evidence=["anc_thm_proof"])
                     for name in names[2:]], mode="primary")
        packet = fx.packet(db, *[f"items:itm_{name}" for name in names[2:]], mode="primary")
        observations = [edit("create", "observations", f"obs_{name}", {
            "target": R("target_specs", f"tgt_{name}"), "result": "matched", "reviewer": "fixture",
            "note": "Synthetic source comparison for UI validation.", "evidence_refs": ["anc_thm"],
            "context_kind": "exact_target"}) for name in names[2:]]
        observations += [edit("create", "observations", f"obs_item_{name}", {
            "target": R("items", f"itm_{name}"), "result": "matched", "reviewer": "fixture",
            "note": "Synthetic source comparison for UI validation.", "evidence_refs": ["anc_thm"]})
            for name in names[2:]]
        review.compare(db, batch=fx.batch(observations, packet["packet_id"]))
        definitions = [("minor", "lem", "presentation", MINOR_DESCRIPTION,
            "Within the stated range, correcting the sentence leaves the displayed bound unchanged."),
            ("moderate", "thm", "proof_gap", r"The local expansion omits one term.\[R_n=A_n+B_n+O(n^{-1}).\]",
             "The already available same-assumption bound controls the omitted term and preserves the principal rate."),
            ("severe", "severe", "statement_refutation", r"The claimed variance bound includes distributions with\[\mathbb{E}[X^2]=\infty.\]",
             "The displayed guarantee fails on part of the stated class; a finite second moment would restrict its scope."),
            ("severe", "unresolved", "inconclusive", "The supplied proof does not establish whether the needed external condition holds.",
             "This is an unresolved limitation; no defect severity is established."),
            (None, "legacy", "presentation", LEGACY_TEXT, "The saved legacy issue remains unrated; its full text is retained.")]
        findings = []
        for rating, name, category, description, impact in definitions:
            body = {"audit_id": fx.audit_id, "target": R("arguments", f"arg_{name}"), "category": category,
                    "lifecycle": "open", "description": description, "impact_reason": impact,
                    "evidence_refs": ["anc_thm_proof"], "check_refs": [db.head("checks", f"chk_comp_{name}").pinned],
                    "affected_uses": [], "resolution": None}
            if rating is not None:
                body["severity"] = rating
            findings.append(edit("create", "findings", f"fnd_{name}", body))
        fx.apply(db, findings, *[f"items:itm_{name}" for name in names], mode="primary")
    return fx


class _Cards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.statuses = {}
        self.math_count = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "data-issue-ref" in values:
            self.statuses.setdefault(values["data-issue-ref"], set()).add(values["data-review-status"])
        if tag == "math":
            self.math_count += 1


class SeverityRenderingTests(TempCase):
    def test_audit_badge_text_contrast_in_both_themes(self):
        css = (publish.RENDERER.parent / "scientific_reader.css").read_text(encoding="utf-8")
        for row in badge_contrast(css):
            with self.subTest(theme=row["theme"], color=row["color"]):
                self.assertGreaterEqual(row["ratio"], 4.5, row)

    def test_frozen_report_acceptance_keeps_cards_math_and_full_legacy_text(self):
        if not node_available():
            self.skipTest("Existing global Node.js is unavailable")
        fx = build_severity_fixture(self.path("fixture"))
        with fx.open(write=False) as db:
            projected = projection.build_projection(db, audit_id=fx.audit_id)
            statuses = {n["item_ref"]["id"]: n["assessment"]["review_display"]["status"] for n in projected["nodes"]}
            self.assertEqual({"itm_lem": "minor", "itm_thm": "moderate", "itm_severe": "severe",
                              "itm_checked": "checked", "itm_unresolved": "unresolved", "itm_legacy": "unrated"}, statuses)
            finalization.finalize_audit(db, audit_id=fx.audit_id, output=self.path("frozen"))
        result = publish.publish_frozen(self.path("frozen"), output=self.path("report.html"))
        self.assertEqual("published", result["state"])
        self.assertEqual("pass", result["receipt"]["renderer"]["python_acceptance"]["status"])
        page = self.path("report.html").read_text(encoding="utf-8")
        cards = _Cards()
        cards.feed(page)
        self.assertEqual({"fnd_lem": {"minor"}, "fnd_thm": {"moderate"}, "fnd_severe": {"severe"},
                          "fnd_unresolved": {"unresolved"}, "fnd_legacy": {"unrated"}}, cards.statuses)
        self.assertGreaterEqual(cards.math_count, 3)
        self.assertIn(LEGACY_TEXT, page)
        self.assertIn("Assessment details and saved finding", page)
        self.assertIn("Exact target support:", page)
        from paper_core.finalization import load_finalization
        snapshot, frozen = load_finalization(self.path("frozen"))
        payload = publish.frozen_render_input(snapshot, snapshot_sha256=frozen["snapshot_sha256"])
        accepted = publish.mechanical_acceptance(page.encode(), payload["projection"], build=payload["build"])
        self.assertEqual("pass", accepted["status"], accepted)
        mutations = {
            "severity": page.replace('data-review-status="minor"', 'data-review-status="severe"'),
            "card": re.sub(r'<section class="proof-issue-card[^>]*>.*?</section>', '', page, count=1, flags=re.S),
            "math": re.sub(r'<math\b[^>]*>.*?</math>', '', page, flags=re.S),
        }
        for name, altered in mutations.items():
            with self.subTest(tamper=name):
                self.assertNotEqual(page, altered)
                self.assertEqual("fail", publish.mechanical_acceptance(altered.encode(), payload["projection"], build=payload["build"])["status"])

        # Historical projections have no derived severity, even when their saved
        # logical assessments use the former red/amber/green vocabulary.
        def without_display(value):
            if isinstance(value, dict):
                return {key: without_display(part) for key, part in value.items()
                        if key not in ("review_display", "finding_displays")}
            return [without_display(part) for part in value] if isinstance(value, list) else value

        historical = without_display(payload)
        history_dir = self.path("historical")
        history_dir.mkdir()
        history_page, receipt = publish.render_payload(historical, workdir=history_dir)
        self.assertEqual("pass", receipt["python_acceptance"]["status"])
        self.assertIn(b'Saved assessment, not rated', history_page)
        self.assertNotIn(b'data-review-status="checked"', history_page)
        self.assertNotIn(b'data-review-status="severe"', history_page)
        self.assertIn(b'Exact target support:', history_page)

    def test_export_selector_selection_retains_severity_colors_in_both_themes(self):
        css = (publish.RENDERER.parent / "scientific_reader.css").read_text(encoding="utf-8")
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        # This is the existing exporter's selector-family admission rule.
        admitted = re.compile(r'(^|,)\s*(svg|:root|\[data-theme|\[data-preset|\.c-|\.t-|\.a-|\.m-)')
        retained = "\n".join(selector + "{" + body + "}" for selector, body in
                             re.findall(r'([^{}]+)\{([^{}]*)\}', css) if admitted.search(selector))
        for color in ("orange", "yellow", "red", "green", "gray"):
            self.assertIn(f"svg.proof-audit .proof-node.s-{color}", retained)
            self.assertIn(f"svg.proof-audit .proof-edge.s-{color}", retained)
            self.assertIn(f"svg.proof-audit .proof-arrowhead.s-{color}", retained)
        orange = re.findall(r'--state-orange:([^;}]+)', retained)
        yellow = re.findall(r'--state-yellow:([^;}]+)', retained)
        self.assertEqual(2, len(orange))
        self.assertEqual(2, len(yellow))
        self.assertTrue(all(a != b for a, b in zip(orange, yellow)))

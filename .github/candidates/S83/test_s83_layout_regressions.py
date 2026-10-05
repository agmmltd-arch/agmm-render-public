"""Text-only regressions for the actual S83 hosted layout failure."""
from __future__ import annotations

import html.parser
import re
import unittest
from pathlib import Path

from assert_s83_layout import validate

ROOT = Path(__file__).resolve().parent


class Nodes(html.parser.HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.paths = []

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get("class", "").split())
        self.paths.append(self.stack + [(tag, classes)])
        if tag not in self.VOID:
            self.stack.append((tag, classes))

    def handle_startendtag(self, tag, attrs):
        classes = set(dict(attrs).get("class", "").split())
        self.paths.append(self.stack + [(tag, classes)])

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def matches(selector: str, path: list[tuple[str, set[str]]]) -> bool:
    tokens = selector.split()
    cursor = len(path) - 1
    for token in reversed(tokens):
        tag, *classes = token.split(".")
        found = False
        while cursor >= 0:
            node_tag, node_classes = path[cursor]
            cursor -= 1
            if (not tag or node_tag == tag) and set(classes) <= node_classes:
                found = True
                break
        if not found:
            return False
    return True


def clean_report():
    return {"layout": {"ok": True, "errorCount": 0, "findings": []},
            "runtime": {"findings": []}}


class S83LayoutRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_actual_37247056915_collisions_are_rejected(self):
        old = clean_report()
        old["layout"] = {
            "ok": False,
            "errorCount": 3,
            "findings": [
                {"severity": "error", "code": "content_overlap",
                 "selector": "div.source-note > div:nth-of-type(1)",
                 "containerSelector": "div.claim", "firstSeen": 28.579, "lastSeen": 44.927},
                {"severity": "error", "code": "content_overlap",
                 "selector": "div.source-note > blockquote:nth-of-type(1)",
                 "containerSelector": "div.evidence-state > span:nth-of-type(1)",
                 "firstSeen": 40.31, "lastSeen": 44.927},
                {"severity": "error", "code": "content_overlap",
                 "selector": "div.source-note > blockquote:nth-of-type(1)",
                 "containerSelector": "div.evidence-state > span:nth-of-type(2)",
                 "firstSeen": 40.31, "lastSeen": 44.927},
            ],
        }
        with self.assertRaisesRegex(ValueError, "zero errors"):
            validate(old)

    def test_actual_37249599493_errors_are_rejected(self):
        report = {"layout": {"ok": False, "errorCount": 3, "findings": [
            {"severity": "error", "code": "content_overlap", "selector": "div.source-note > div:nth-of-type(1)", "containerSelector": "article.face.face-back > div:nth-of-type(1) > h2:nth-of-type(1)", "firstSeen": 28.579, "lastSeen": 44.927},
            {"severity": "error", "code": "content_overlap", "selector": "div.source-note > div:nth-of-type(1)", "containerSelector": "article.face.face-back > div:nth-of-type(2) > h2:nth-of-type(1)", "firstSeen": 28.579, "lastSeen": 44.927},
            {"severity": "error", "code": "content_overlap", "selector": "div.evidence-state > span:nth-of-type(2)", "containerSelector": "article.face.face-back > div:nth-of-type(2) > div:nth-of-type(3)", "firstSeen": 40.31, "lastSeen": 44.927}]}, "runtime": {"findings": []}}
        with self.assertRaisesRegex(ValueError, "zero errors"):
            validate(report)

    def test_face_turn_handoff_is_seek_safe_at_edge(self):
        for part in (".face-back{transform:rotateY(180deg);display:none;", ".set('.turnover', { y: 100, rotation: -2, scale: .96, rotationY: 0 }, 28.457)", ".set('.face-front', { display: 'block' }, 28.457)", ".set('.face-back', { display: 'none' }, 28.457)", ".to('.turnover', { rotationY: 180, duration: .78, ease: 'power2.inOut' }, 34.533)", ".set('.face-front', { display: 'none' }, 34.923)", ".set('.face-back', { display: 'grid' }, 34.923)", ".set('.face-back', { display: 'none' }, 44.901)"):
            self.assertIn(part, self.html)
        self.assertNotIn(".fromTo('.turnover'", self.html)

    def test_rear_status_fits_existing_field_clear_of_footer(self):
        self.assertRegex(self.html, r"\.blank-field\s*\{[^}]*top:540px;height:220px")
        self.assertRegex(self.html, r"\.evidence-state\s*\{[^}]*top:560px")
        self.assertRegex(self.html, r"\.ledger-column \.source-tag\s*\{[^}]*bottom:50px")
        height = 2*42*1.08+2*33+2*4
        self.assertGreaterEqual(560,540)
        self.assertLess(560+height,540+220)
        self.assertNotIn("data-layout-allow-overlap",self.html)
        self.assertNotIn("allow-overlap",self.html)

    def test_clean_hosted_layout_report_passes(self):
        validate(clean_report())

    def test_unrelated_new_layout_error_is_also_rejected(self):
        report = clean_report()
        report["layout"] = {"ok": False, "errorCount": 1,
                            "findings": [{"severity": "error", "code": "content_overlap",
                                          "selector": ".new-text", "containerSelector": ".scene"}]}
        with self.assertRaisesRegex(ValueError, "errorCount=1"):
            validate(report)

    def test_missing_layout_diagnostics_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "no layout section"):
            validate({"runtime": {"findings": []}})

    def test_missing_gsap_target_is_rejected(self):
        report = clean_report()
        report["runtime"]["findings"] = [{"code": "console_warning",
                                           "message": "GSAP target .s2 .note .line not found"}]
        with self.assertRaisesRegex(ValueError, "GSAP targets"):
            validate(report)

    def test_every_authored_gsap_tween_target_resolves(self):
        parser = Nodes()
        parser.feed(self.html)
        targets = re.findall(r"\.(?:fromTo|to)\(\s*['\"]([^'\"]+)['\"]", self.html)
        self.assertGreater(len(targets), 10)
        missing = [target for target in targets
                   if not any(matches(part.strip(), path)
                              for path in parser.paths for part in target.split(","))]
        self.assertEqual(missing, [])

    def test_text_zones_are_separated_without_overlap_waivers(self):
        self.assertRegex(self.html, r"\.source-note \.source-tag\s*\{[^}]*position:absolute;[^}]*top:12px")
        self.assertRegex(self.html, r"\.evidence-state\s*\{[^}]*top:560px")
        self.assertNotIn("data-layout-allow-overlap", self.html)
        self.assertNotIn("allow-overlap", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)

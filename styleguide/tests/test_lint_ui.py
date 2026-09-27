import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase


class LintUITest(TestCase):
    def test_templates_have_no_ui_errors(self):
        """No off-palette classes or hardcoded off-palette hex in templates."""
        try:
            call_command("lint_ui")
        except SystemExit as e:
            self.fail(f"lint_ui failed with exit code {e.code}")

    def _run_lint(self, files):
        """Run lint_ui against a temp template dir; returns (exited, output)."""
        from io import StringIO
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, content in files.items():
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            out, err = StringIO(), StringIO()
            exited = False
            try:
                call_command("lint_ui", dir=str(root), stdout=out, stderr=err)
            except SystemExit:
                exited = True
            return exited, out.getvalue() + err.getvalue()

    def test_legacy_include_partial_is_error(self):
        exited, out = self._run_lint({
            "app/page.html": '{% include "components/button.html" %}',
        })
        self.assertTrue(exited)
        self.assertIn("legacy include", out)

    def test_slippers_syntax_is_error(self):
        exited, out = self._run_lint({
            "app/page.html": '{% #button %}{% /button %}',
        })
        self.assertTrue(exited)
        self.assertIn("slippers", out)

    def test_drift_patterns_warn(self):
        _, out = self._run_lint({
            "app/page.html": (
                '<span class="rounded-full bg-chavi-primary-100">x</span>'
                '<details><summary>s</summary>b</details>'
                '<div class="fixed inset-0"></div>'
                '<h1>Title</h1>'
            ),
        })
        self.assertIn("badge component", out)
        self.assertIn("accordion", out)
        self.assertIn("modal or loading_overlay", out)
        self.assertIn("page_header", out)

    def test_allauth_and_admin_exempt_from_drift_rules(self):
        _, out = self._run_lint({
            "allauth/layouts/base.html": '<h1>x</h1><details><summary>s</summary></details>',
            "admin/index.html": '<div class="fixed inset-0"></div><h1>x</h1>',
        })
        self.assertNotIn("badge component", out)
        self.assertNotIn("accordion", out)
        self.assertNotIn("modal or loading_overlay", out)
        self.assertNotIn("page_header", out)

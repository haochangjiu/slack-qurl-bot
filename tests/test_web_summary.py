import os
import sys
import types
import unittest

os.environ.setdefault("ATLASCLOUD_API_KEY", "test-key")

try:
    import openai  # noqa: F401
except ModuleNotFoundError:
    sys.modules["openai"] = types.SimpleNamespace(
        AsyncOpenAI=lambda **kwargs: object(),
    )

from services.web_summary import WebSummaryService, _is_blocked_host, normalize_summary_url


class WebSummaryHelpersTest(unittest.TestCase):
    def test_normalize_summary_url_adds_https_and_strips_fragment(self):
        self.assertEqual(
            normalize_summary_url("example.com/path#section"),
            "https://example.com/path",
        )

    def test_normalize_summary_url_rejects_non_http_scheme(self):
        with self.assertRaises(Exception):
            normalize_summary_url("file:///etc/passwd")

    def test_blocked_hosts_include_local_and_private_ips(self):
        self.assertTrue(_is_blocked_host("localhost"))
        self.assertTrue(_is_blocked_host("127.0.0.1"))
        self.assertTrue(_is_blocked_host("10.0.0.8"))
        self.assertFalse(_is_blocked_host("example.com"))

    def test_extract_page_removes_scripts_and_keeps_visible_text(self):
        service = WebSummaryService()
        html = """
        <html>
          <head>
            <title>Example Title</title>
            <meta name="description" content="Example description" />
            <script>window.evil = true;</script>
          </head>
          <body>
            <main>
              <h1>Heading</h1>
              <p>First paragraph.</p>
              <p>Second paragraph.</p>
            </main>
          </body>
        </html>
        """

        page = service._extract_page("https://example.com", html, truncated=False)

        self.assertEqual(page.title, "Example Title")
        self.assertEqual(page.description, "Example description")
        self.assertIn("Heading", page.text)
        self.assertIn("First paragraph.", page.text)
        self.assertNotIn("window.evil", page.text)


if __name__ == "__main__":
    unittest.main()

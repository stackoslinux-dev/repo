import unittest
from agent_triage import classify

class TriageTests(unittest.TestCase):
    def test_rate_limit(self):
        self.assertEqual(classify("urllib.error.HTTPError: HTTP Error 403: rate limit exceeded")[0]["category"], "github_api_rate_limit")
    def test_signature(self):
        self.assertEqual(classify("gpgv: BAD signature")[0]["category"], "signature_failure")
    def test_no_false_positive(self):
        self.assertEqual(classify("All tests passed"), [])
    def test_token_not_reflected(self):
        self.assertEqual(classify("Authorization: Bearer ghp_123456789012345678901234"), [])

if __name__ == "__main__":
    unittest.main()

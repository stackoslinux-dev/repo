import unittest
from agent_proposal import validate_proposal

class ProposalTests(unittest.TestCase):
    def test_allowlisted(self):
        r = validate_proposal({"path":"ci/c3-native/agent_triage.py","content":"print('test')","reason":"test"})
        self.assertEqual(r["status"], "UNTRUSTED_REVIEW_ONLY")
    def test_production_blocked(self):
        for path in ["ci/verify_c3.py", ".github/workflows/c3-updates.yml", "../../etc/passwd", "ci/c3-native/evil.py"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_proposal({"path":path,"content":"x","reason":"test"})
    def test_secret_blocked(self):
        with self.assertRaises(ValueError):
            validate_proposal({"path":"ci/c3-native/agent_triage.py","content":"ghp_123456789012345678901","reason":"test"})
    def test_oversized_blocked(self):
        with self.assertRaises(ValueError):
            validate_proposal({"path":"ci/c3-native/agent_triage.py","content":"x"*20001,"reason":"test"})

if __name__ == "__main__":
    unittest.main()

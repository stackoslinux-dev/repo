import unittest
from agent_self_audit import audit

class AuditTests(unittest.TestCase):
    def test_empty_runs_not_success(self):
        self.assertEqual(audit({"workflow_runs": []})["status"], "NO_COMPLETED_RUNS")

    def test_latest_success_with_prior_failure(self):
        report = audit({"workflow_runs": [
            {"id": 3, "status": "completed", "conclusion": "success"},
            {"id": 2, "status": "completed", "conclusion": "failure", "head_sha": "abc"},
        ]})
        self.assertEqual(report["status"], "LATEST_COMPLETED_SUCCESS")
        self.assertEqual(report["recent_failures"][0]["id"], 2)
        self.assertFalse(report["writes_performed"])

    def test_latest_failure(self):
        self.assertEqual(audit({"workflow_runs": [
            {"id": 5, "status": "completed", "conclusion": "failure"}
        ]})["status"], "FAILURE_NEEDS_REVIEW")

if __name__ == "__main__":
    unittest.main()

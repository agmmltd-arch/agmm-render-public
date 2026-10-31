import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from hosted_route import hosted_route_result

NOW = datetime(2026, 10, 4, 17, 0, tzinfo=ZoneInfo("Europe/London"))
ROW = {
    "route": "hosted_youtube_studio", "platforms": ["youtube"], "status": "ARMED",
    "date": "2026-10-05", "slot": "15:00", "video_sha256": "a" * 64,
    "hosted_source_run_id": "123456789", "hosted_thumbnail_sha256": "b" * 64,
    "provider_receipt": {
        "schema": "agmm-youtube-cloud-studio-scheduled-v1", "overall": "SCHEDULED_VERIFIED",
        "master_sha256": "a" * 64, "source_run_id": "123456789", "thumbnail_sha256": "b" * 64,
        "scheduled_for": "2026-10-05T15:00:00+01:00", "scheduled_evidence": {"ok": True},
        "video_id": "aBcDeF123_-", "post_url": "https://www.youtube.com/watch?v=aBcDeF123_-"},
}


class HostedRouteTests(unittest.TestCase):
    def test_valid_future_schedule_is_visible_and_never_local_publish(self):
        got = hosted_route_result(ROW, NOW)
        self.assertEqual(got["status"], "scheduled_awaiting_public")
        self.assertTrue(got["ok"])

    def test_missing_receipt_fails_closed(self):
        row = dict(ROW); row.pop("provider_receipt")
        self.assertEqual(hosted_route_result(row, NOW)["status"], "hosted_schedule_receipt_missing")

    def test_false_provider_schedule_fails_closed(self):
        import copy
        row = copy.deepcopy(ROW); row["provider_receipt"]["scheduled_evidence"]["ok"] = False
        self.assertEqual(hosted_route_result(row, NOW)["status"], "hosted_schedule_receipt_invalid")

    def test_master_binding_mismatch_fails_closed(self):
        import copy
        row = copy.deepcopy(ROW); row["provider_receipt"]["master_sha256"] = "c" * 64
        self.assertEqual(hosted_route_result(row, NOW)["status"], "hosted_schedule_binding_mismatch")

    def test_missing_or_invalid_pins_cannot_match_each_other(self):
        import copy
        for row_key, receipt_key in (("video_sha256", "master_sha256"),
                                     ("hosted_thumbnail_sha256", "thumbnail_sha256"),
                                     ("hosted_source_run_id", "source_run_id")):
            row = copy.deepcopy(ROW)
            row.pop(row_key); row["provider_receipt"].pop(receipt_key)
            self.assertEqual(hosted_route_result(row, NOW)["status"], "hosted_schedule_binding_mismatch")

    def test_non_object_provider_evidence_is_refused(self):
        import copy
        row = copy.deepcopy(ROW); row["provider_receipt"]["scheduled_evidence"] = None
        self.assertEqual(hosted_route_result(row, NOW)["status"], "hosted_schedule_receipt_invalid")

    def test_mismatched_and_malformed_identity_is_refused(self):
        import copy
        for url in ("https://www.youtube.com/watch?v=other000000", "https://example.com/watch?v=aBcDeF123_-", ""):
            row = copy.deepcopy(ROW); row["provider_receipt"]["post_url"] = url
            self.assertEqual(hosted_route_result(row, NOW)["status"], "hosted_schedule_identity_missing")

    def test_wrong_offset_and_missing_offset_are_refused(self):
        import copy
        for instant in ("2026-10-05T15:00:00+00:00", "2026-10-05T15:00:00"):
            row = copy.deepcopy(ROW); row["provider_receipt"]["scheduled_for"] = instant
            self.assertEqual(hosted_route_result(row, NOW)["status"], "hosted_schedule_time_mismatch")

    def test_ambiguous_clock_change_slot_is_refused(self):
        import copy
        row = copy.deepcopy(ROW); row.update(date="2026-10-25", slot="01:30")
        row["provider_receipt"]["scheduled_for"] = "2026-10-25T01:30:00+00:00"
        self.assertEqual(hosted_route_result(row, NOW)["status"], "hosted_schedule_time_mismatch")

    def test_due_slot_never_claims_public_without_public_receipt(self):
        after = datetime(2026, 10, 5, 15, 1, tzinfo=ZoneInfo("Europe/London"))
        got = hosted_route_result(ROW, after)
        self.assertEqual(got["status"], "hosted_schedule_due_requires_publication_receipt")
        self.assertFalse(got["ok"])


if __name__ == "__main__":
    unittest.main()

import copy
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from queue_contract import earliest_slot, make_queue_row


MASTER = "a" * 64
META = "b" * 64
THUMB = "c" * 64
APPROVAL = {
    "overall": "PASS", "master_sha256": MASTER, "source_run_id": "123456789",
    "reviewer_id": "independent-reviewer", "maker_id": "maker", "date": "2026-10-05",
    "audiovisual_review": {k: "PASS" for k in (
        "continuous_visual", "continuous_audio", "motion", "pilot_craft", "thumbnail")},
}
RECEIPT = {
    "schema": "agmm-youtube-cloud-studio-scheduled-v1", "overall": "SCHEDULED_VERIFIED",
    "master_sha256": MASTER, "source_run_id": "123456789", "thumbnail_sha256": THUMB,
    "scheduled_for": "2026-10-05T15:00:00+01:00", "scheduled_evidence": {"ok": True},
    "video_id": "aBcDeF123_-", "post_url": "https://www.youtube.com/watch?v=aBcDeF123_-",
}


def row(**overrides):
    args = dict(approval=copy.deepcopy(APPROVAL), provider_receipt=None,
                source_run_id="123456789", artifact_name="approved-master-run-123456789",
                video_name="MASTER.mp4", master_sha256=MASTER, approval_sha256="d" * 64, metadata_sha256=META,
                thumbnail_sha256=THUMB, caption_sha256="e" * 64,
                day="2026-10-05", slot="15:00", post_id="20261005-1500-F04",
                existing_rows=[])
    args.update(overrides)
    return make_queue_row(**args)


class QueueContractTests(unittest.TestCase):
    def test_earliest_available_slot_respects_existing_rows(self):
        rows = [{"platform": "youtube", "date": "2026-10-05", "slot": "11:00"}]
        got = earliest_slot("2026-10-05", ["11:00", "15:00", "19:00"], rows,
                            datetime(2026, 10, 4, 17, 0, tzinfo=ZoneInfo("Europe/London")))
        self.assertEqual(got, "15:00")

    def test_no_provider_receipt_never_arms(self):
        self.assertEqual(row()["status"], "HELD_AWAITING_PROVIDER_SCHEDULE")

    def test_matching_real_schedule_receipt_arms(self):
        self.assertEqual(row(provider_receipt=copy.deepcopy(RECEIPT))["status"], "ARMED")

    def test_receipt_link_must_match_canonical_video_identity(self):
        for url in ("https://www.youtube.com/watch?v=other000000", "https://example.com/watch?v=aBcDeF123_-", ""):
            bad = copy.deepcopy(RECEIPT); bad["post_url"] = url
            with self.assertRaisesRegex(ValueError, "provider identity invalid"):
                row(provider_receipt=bad)

    def test_wrong_master_receipt_refused(self):
        bad = copy.deepcopy(RECEIPT); bad["master_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "receipt master mismatch"):
            row(provider_receipt=bad)

    def test_missing_full_av_gate_refused(self):
        bad = copy.deepcopy(APPROVAL); bad["audiovisual_review"].pop("continuous_audio")
        with self.assertRaisesRegex(ValueError, "continuous_audio"):
            row(approval=bad)

    def test_maker_cannot_approve(self):
        bad = copy.deepcopy(APPROVAL); bad["reviewer_id"] = bad["maker_id"]
        with self.assertRaisesRegex(ValueError, "maker cannot"):
            row(approval=bad)

    def test_duplicate_id_and_slot_refused(self):
        for existing in ([{"post_id": "20261005-1500-F04"}],
                         [{"post_id": "other", "platform": "youtube", "date": "2026-10-05", "slot": "15:00"}],
                         [{"post_id": "other", "master_sha256": MASTER}]):
            with self.subTest(existing=existing), self.assertRaises(ValueError):
                row(existing_rows=existing)

    def test_native_rows_block_occupied_slot_and_reused_master(self):
        native = {"platforms": ["youtube"], "date": "2026-10-05", "slot": "15:00",
                  "video_sha256": "f" * 64, "post_id": "other"}
        with self.assertRaisesRegex(ValueError, "duplicate YouTube slot"):
            row(existing_rows=[native])
        self.assertEqual(earliest_slot("2026-10-05", ["15:00", "19:00"], [native],
                         datetime(2026, 10, 4, 17, 0, tzinfo=ZoneInfo("Europe/London"))), "19:00")
        native.update(slot="11:00", video_sha256=MASTER)
        with self.assertRaisesRegex(ValueError, "master already queued"):
            row(existing_rows=[native])
        native.pop("date")
        with self.assertRaisesRegex(ValueError, "plan date"):
            row(existing_rows=[native])

    def test_wrong_schedule_time_refused(self):
        bad = copy.deepcopy(RECEIPT); bad["scheduled_for"] = "2026-10-05T16:00:00+01:00"
        with self.assertRaisesRegex(ValueError, "differs from queue slot"):
            row(provider_receipt=bad)

    def test_wrong_schedule_date_refused(self):
        bad = copy.deepcopy(RECEIPT); bad["scheduled_for"] = "2026-10-06T15:00:00+01:00"
        with self.assertRaisesRegex(ValueError, "schedule date"):
            row(provider_receipt=bad)

    def test_wrong_offset_cannot_masquerade_as_london_time(self):
        bad = copy.deepcopy(RECEIPT); bad["scheduled_for"] = "2026-10-05T15:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "differs from queue slot"):
            row(provider_receipt=bad)

    def test_missing_timezone_refused(self):
        bad = copy.deepcopy(RECEIPT); bad["scheduled_for"] = "2026-10-05T15:00:00"
        with self.assertRaisesRegex(ValueError, "timezone missing"):
            row(provider_receipt=bad)

    def test_clock_change_slots_refused(self):
        for day in ("2026-03-29", "2026-10-25"):
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, "ambiguous or nonexistent"):
                earliest_slot(day, ["01:30"], [], datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")))

    def test_false_schedule_evidence_refused(self):
        bad = copy.deepcopy(RECEIPT); bad["scheduled_evidence"]["ok"] = False
        with self.assertRaisesRegex(ValueError, "evidence missing"):
            row(provider_receipt=bad)


if __name__ == "__main__":
    unittest.main()

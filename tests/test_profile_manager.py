import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from pirlo.core.services.profile_manager import ProfileManager


class TestProfileManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_workspace = os.environ.get("PIRLO_WORKSPACE")
        os.environ["PIRLO_WORKSPACE"] = self.temp_dir.name

    def tearDown(self):
        if self.original_workspace:
            os.environ["PIRLO_WORKSPACE"] = self.original_workspace
        else:
            os.environ.pop("PIRLO_WORKSPACE", None)
        self.temp_dir.cleanup()

    def test_save_and_load_profile_metadata(self):
        meta = ProfileManager.save_profile_metadata(
            profile_input="work",
            urls=["https://github.com", "https://google.com"],
            ttl_days=7,
        )

        self.assertEqual(meta.name, "work")
        self.assertEqual(meta.ttl_days, 7)
        self.assertIn("https://github.com", meta.authenticated_urls)
        self.assertTrue(ProfileManager.exists("work"))
        self.assertFalse(ProfileManager.is_expired("work"))

        loaded = ProfileManager.load_profile_metadata("work")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, "work")
        self.assertEqual(len(loaded.authenticated_urls), 2)

    def test_is_expired(self):
        # Create metadata and manually set expires_at in the past
        ProfileManager.save_profile_metadata("expired_prof", ttl_days=7)
        meta_path = ProfileManager.get_metadata_path("expired_prof")

        past_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        import json

        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["expires_at"] = past_time
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        self.assertTrue(ProfileManager.is_expired("expired_prof"))

    def test_list_and_delete_profiles(self):
        ProfileManager.save_profile_metadata("prof1", urls=["https://a.com"])
        ProfileManager.save_profile_metadata("prof2", urls=["https://b.com"])

        profiles = ProfileManager.list_profiles()
        names = [p.name for p in profiles]
        self.assertIn("prof1", names)
        self.assertIn("prof2", names)

        deleted = ProfileManager.delete_profile("prof1")
        self.assertTrue(deleted)
        self.assertFalse(ProfileManager.exists("prof1"))


if __name__ == "__main__":
    unittest.main()

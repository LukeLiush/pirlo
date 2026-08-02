import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from pirlo.core.ports.pitch import Parameter
from pirlo.infrastructure.adapters.cli.terminal_pitch import TerminalPitch


class DummyResolutionSession(TerminalPitch):
    """Session subclass for testing parameter resolution."""

    default_config_path = None  # Configured dynamically in tests

    task = Parameter(str, default="default-task", env_name="TEST_TASK")
    count = Parameter(int, default=5, env_name="TEST_COUNT")
    enabled = Parameter(bool, default=False, env_name="TEST_ENABLED")
    items = Parameter(list[str], default=[], env_name="TEST_ITEMS")
    details = Parameter(dict, default={}, env_name="TEST_DETAILS")
    path_val = Parameter(Path, default=None, env_name="TEST_PATH")
    multi_env = Parameter(
        str, default="default-multi", env_name=["TEST_KEY_A", "TEST_KEY_B"]
    )

    async def play(self):
        # No-op for test validation
        pass


class TestParameterResolution(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.temp_dir.name) / "test_config.json"

        # Back up env and argv
        self.original_env = dict(os.environ)
        self.original_argv = list(sys.argv)

        # Set dummy default config path to None initially
        DummyResolutionSession.default_config_path = None

    def tearDown(self):
        # Restore env and argv
        os.environ.clear()
        os.environ.update(self.original_env)
        sys.argv = self.original_argv
        self.temp_dir.cleanup()

    def test_default_values_fallback(self):
        """Verify that default values are used when no other sources are provided."""
        # Setup sys.argv with no arguments for parameters
        sys.argv = ["pirlo dummy_resolution"]

        # Instantiate and parse
        session = DummyResolutionSession()
        # Mock play to run without full lifecycle database side effects
        session.play = lambda: None
        DummyResolutionSession.cli()

        # Retrieve parsed options from the class execution
        # Wait, DummyResolutionSession.cli() instantiates inside cli().
        # Let's inspect sys.modules / local variables by stubbing or intercepting play.
        # An elegant way to assert is to stub play() to save the instance.
        captured_instance = []

        async def mock_play_save(self_instance):
            captured_instance.append(self_instance)

        DummyResolutionSession.play = mock_play_save
        DummyResolutionSession.cli()

        self.assertEqual(len(captured_instance), 1)
        inst = captured_instance[0]

        self.assertEqual(inst.task, "default-task")
        self.assertEqual(inst.count, 5)
        self.assertEqual(inst.enabled, False)
        self.assertEqual(inst.items, [])
        self.assertEqual(inst.details, {})
        self.assertEqual(inst.path_val, None)
        self.assertEqual(inst.multi_env, "default-multi")

    def test_env_variables_resolution(self):
        """Verify that parameters load from environment variables."""
        os.environ["TEST_TASK"] = "env-task"
        os.environ["TEST_COUNT"] = "42"
        os.environ["TEST_ENABLED"] = "true"
        os.environ["TEST_ITEMS"] = "a,b,c"
        os.environ["TEST_DETAILS"] = '{"foo": "bar"}'
        os.environ["TEST_PATH"] = "/var/log"
        os.environ["TEST_KEY_B"] = "value-b"  # testing list env_name fallback

        sys.argv = ["pirlo dummy_resolution"]
        captured_instance = []

        async def mock_play(self_instance):
            captured_instance.append(self_instance)

        DummyResolutionSession.play = mock_play
        DummyResolutionSession.cli()

        inst = captured_instance[0]
        self.assertEqual(inst.task, "env-task")
        self.assertEqual(inst.count, 42)
        self.assertEqual(inst.enabled, True)
        self.assertEqual(inst.items, ["a", "b", "c"])
        self.assertEqual(inst.details, {"foo": "bar"})
        self.assertEqual(inst.path_val, Path("/var/log"))
        # Should pick B because A is not in env
        self.assertEqual(inst.multi_env, "value-b")

    def test_cli_overrides_env_and_default(self):
        """Verify that CLI arguments override env variables and defaults."""
        os.environ["TEST_TASK"] = "env-task"
        os.environ["TEST_COUNT"] = "42"

        # CLI overrides
        sys.argv = [
            "pirlo dummy_resolution",
            "--task",
            "cli-task",
            "--count",
            "100",
            "--enabled",
            "--items",
            "x",
            "y",
        ]

        captured_instance = []

        async def mock_play(self_instance):
            captured_instance.append(self_instance)

        DummyResolutionSession.play = mock_play
        DummyResolutionSession.cli()

        inst = captured_instance[0]
        self.assertEqual(inst.task, "cli-task")
        self.assertEqual(inst.count, 100)
        self.assertEqual(inst.enabled, True)
        self.assertEqual(inst.items, ["x", "y"])

    def test_cli_overrides_config_json(self):
        """Verify that CLI flags override JSON config, while non-specified flags fall back to config JSON."""
        os.environ["TEST_TASK"] = "env-task"
        os.environ["TEST_COUNT"] = "42"

        # Write config
        config_data = {
            "task": "json-task",
            "count": 999,
            "enabled": True,
            "items": ["json1", "json2"],
            "details": {"json_key": "val"},
            "path_val": "/tmp/test",
            "multi_env": "json-multi",
        }
        with open(self.config_file, "w") as f:
            json.dump(config_data, f)

        sys.argv = [
            "pirlo dummy_resolution",
            "--config",
            str(self.config_file),
            "--task",
            "cli-task",
            "--count",
            "100",
        ]

        captured_instance = []

        async def mock_play(self_instance):
            captured_instance.append(self_instance)

        DummyResolutionSession.play = mock_play
        DummyResolutionSession.cli()

        inst = captured_instance[0]
        # CLI flags take top priority over JSON config
        self.assertEqual(inst.task, "cli-task")
        self.assertEqual(inst.count, 100)
        # Non-overridden parameters fall back to JSON config
        self.assertEqual(inst.enabled, True)
        self.assertEqual(inst.items, ["json1", "json2"])
        self.assertEqual(inst.details, {"json_key": "val"})
        self.assertEqual(inst.path_val, Path("/tmp/test"))
        self.assertEqual(inst.multi_env, "json-multi")

    def test_default_config_path_resolution(self):
        """Verify default_config_path works when --config is omitted."""
        # Write to default config file location
        config_data = {"task": "default-json-task", "count": 777}
        with open(self.config_file, "w") as f:
            json.dump(config_data, f)

        # Set class default_config_path
        DummyResolutionSession.default_config_path = self.config_file

        # Run without --config or other args
        sys.argv = ["pirlo dummy_resolution"]

        captured_instance = []

        async def mock_play(self_instance):
            captured_instance.append(self_instance)

        DummyResolutionSession.play = mock_play
        DummyResolutionSession.cli()

        inst = captured_instance[0]
        self.assertEqual(inst.task, "default-json-task")
        self.assertEqual(inst.count, 777)

    def test_autosave_default_config_path(self):
        """Verify that resolved parameters are auto-saved to default_config_path."""
        save_file = Path(self.temp_dir.name) / "autosave_test.json"
        DummyResolutionSession.default_config_path = save_file

        sys.argv = [
            "pirlo dummy_resolution",
            "--task",
            "autosaved-task",
            "--count",
            "500",
        ]

        captured_instance = []

        async def mock_play(self_instance):
            captured_instance.append(self_instance)

        DummyResolutionSession.play = mock_play
        DummyResolutionSession.cli()

        self.assertTrue(save_file.exists())
        with open(save_file, "r") as f:
            data = json.load(f)

        self.assertEqual(data.get("task"), "autosaved-task")
        self.assertEqual(data.get("count"), 500)


if __name__ == "__main__":
    unittest.main()

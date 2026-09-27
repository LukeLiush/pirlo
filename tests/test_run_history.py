import shutil
import tempfile
import unittest
from pathlib import Path

from pirlo.infrastructure.services.run_id_generator import IdentityFactory


class TestRunHistoryAndMVC(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir: Path = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    def test_run_id_generation_is_seeded_and_unique(self) -> None:
        playbook: str = "dummy"
        params: dict[str, object] = {"foo": "bar", "count": 10}

        factory1: IdentityFactory = IdentityFactory(playbook, params)
        factory2: IdentityFactory = IdentityFactory(playbook, params)

        run_name1: str = factory1.generate_run_name()
        run_name2: str = factory2.generate_run_name()
        self.assertEqual(run_name1, run_name2)

        run_id1: str = factory1.generate_run_id()
        run_id2: str = factory2.generate_run_id()
        self.assertNotEqual(run_id1, run_id2)
        self.assertEqual(len(run_id1), 8)
        self.assertEqual(len(run_id2), 8)


if __name__ == "__main__":
    unittest.main()

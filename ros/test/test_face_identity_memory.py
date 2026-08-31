import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "face_identity_memory.py"
SPEC = importlib.util.spec_from_file_location("face_identity_memory", MODULE_PATH)
face_identity_memory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(face_identity_memory)


class FakeFace:
    def __init__(self, face_id, left=0.1, top=0.1, width=0.2, height=0.2):
        self.id = face_id
        self.gender = ""
        self.age_years = 0
        self.age_type = ""
        self.emotion_neutral = 1.0
        self.emotion_angry = 0.0
        self.emotion_happy = 0.0
        self.emotion_surprise = 0.0
        self.rectangle = [left, top, width, height]
        self.angles = [0.0, 0.0, 0.0]


class FaceMemoryStoreTest(unittest.TestCase):
    def test_keeps_only_four_people_and_evicts_oldest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = face_identity_memory.FaceMemoryStore(Path(tmpdir) / "faces.json", max_people=4)

            for face_id in range(1, 5):
                store.observe_faces([FakeFace(face_id)])

            memory = store.load()
            self.assertEqual(len(memory["people"]), 4)
            self.assertEqual(memory["current_person_id"], "person_4")

            store.observe_faces([FakeFace(5)])
            memory = store.load()
            tracking_ids = {person["face_tracking_id"] for person in memory["people"]}
            self.assertEqual(len(memory["people"]), 4)
            self.assertNotIn(1, tracking_ids)
            self.assertIn(5, tracking_ids)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Track short-term QTrobot face slots and persist per-person context."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import rospy
except ImportError:  # Allows unit tests and syntax checks outside ROS.
    rospy = None

try:
    from qt_nuitrack_app.msg import Faces
except ImportError:
    Faces = None


DEFAULT_MEMORY_FILE = Path(__file__).resolve().parents[2] / "runtime" / "face_memory.json"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_write_json(path, payload):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=output_path.name + ".",
        suffix=".tmp",
        dir=str(output_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_name, str(output_path))
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def workspace_path(path):
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path(__file__).resolve().parents[2] / resolved
    return resolved


def _float_list(values, limit=None):
    result = []
    for value in values or []:
        try:
            result.append(round(float(value), 6))
        except (TypeError, ValueError):
            continue
        if limit and len(result) >= limit:
            break
    return result


def _face_area(face):
    rectangle = getattr(face, "rectangle", []) or []
    if len(rectangle) < 4:
        return 0.0
    try:
        return max(0.0, float(rectangle[2])) * max(0.0, float(rectangle[3]))
    except (TypeError, ValueError):
        return 0.0


def face_to_dict(face):
    rectangle = _float_list(getattr(face, "rectangle", []), 4)
    center = None
    if len(rectangle) >= 4:
        center = [
            round(rectangle[0] + rectangle[2] / 2.0, 6),
            round(rectangle[1] + rectangle[3] / 2.0, 6),
        ]
    return {
        "tracking_id": int(getattr(face, "id", 0) or 0),
        "gender": str(getattr(face, "gender", "") or ""),
        "age_years": int(getattr(face, "age_years", 0) or 0),
        "age_type": str(getattr(face, "age_type", "") or ""),
        "rectangle": rectangle,
        "center": center,
        "area": round(_face_area(face), 6),
        "angles": _float_list(getattr(face, "angles", []), 3),
        "emotion": {
            "neutral": round(float(getattr(face, "emotion_neutral", 0.0) or 0.0), 4),
            "angry": round(float(getattr(face, "emotion_angry", 0.0) or 0.0), 4),
            "happy": round(float(getattr(face, "emotion_happy", 0.0) or 0.0), 4),
            "surprise": round(float(getattr(face, "emotion_surprise", 0.0) or 0.0), 4),
        },
    }


class FaceMemoryStore:
    def __init__(self, memory_file, max_people=4):
        self.memory_file = workspace_path(memory_file)
        self.max_people = max(1, int(max_people))

    def _empty_memory(self):
        return {
            "schema_version": 1,
            "updated_at": utc_now_iso(),
            "current_person_id": None,
            "people": [],
        }

    def load(self):
        memory = read_json(self.memory_file)
        if not memory:
            return self._empty_memory()
        memory.setdefault("schema_version", 1)
        memory.setdefault("people", [])
        return memory

    def save(self, memory):
        memory["updated_at"] = utc_now_iso()
        atomic_write_json(self.memory_file, memory)

    def observe_faces(self, faces):
        now = utc_now_iso()
        memory = self.load()
        people = [person for person in memory.get("people", []) if isinstance(person, dict)]
        memory["people"] = people

        sorted_faces = sorted(faces or [], key=_face_area, reverse=True)
        visible_person_ids = []
        events = []
        for face in sorted_faces:
            face_data = face_to_dict(face)
            person, event = self._find_or_create_person(people, face_data["tracking_id"], now)
            if event:
                events.append(event)
            person["face_tracking_id"] = face_data["tracking_id"]
            person["last_seen"] = now
            person["observation_count"] = int(person.get("observation_count", 0) or 0) + 1
            person["face"] = face_data
            if person["person_id"] not in visible_person_ids:
                visible_person_ids.append(person["person_id"])

        memory["current_person_id"] = visible_person_ids[0] if visible_person_ids else None
        memory["visible_person_ids"] = visible_person_ids
        memory["last_events"] = events
        self.save(memory)
        return memory

    def _find_or_create_person(self, people, tracking_id, now):
        for person in people:
            if int(person.get("face_tracking_id", -1) or -1) == int(tracking_id):
                return person, None

        evicted_id = None
        if len(people) >= self.max_people:
            people.sort(key=lambda item: str(item.get("last_seen", item.get("first_seen", ""))))
            evicted = people.pop(0)
            person_id = evicted.get("person_id", self._next_person_id(people))
            evicted_id = person_id
        else:
            person_id = self._next_person_id(people)

        person = {
            "person_id": person_id,
            "face_tracking_id": int(tracking_id),
            "first_seen": now,
            "last_seen": now,
            "observation_count": 0,
        }
        people.append(person)
        event = {
            "type": "new_face_slot",
            "person_id": person_id,
            "tracking_id": int(tracking_id),
        }
        if evicted_id:
            event["evicted_person_id"] = evicted_id
        return person, event

    def _next_person_id(self, people):
        used = set()
        for person in people:
            value = str(person.get("person_id", ""))
            if value.startswith("person_"):
                try:
                    used.add(int(value.split("_", 1)[1]))
                except (TypeError, ValueError, IndexError):
                    continue
        for index in range(1, self.max_people + 1):
            if index not in used:
                return "person_%d" % index
        return "person_1"


class FaceIdentityMemoryNode:
    def __init__(self):
        memory_file = rospy.get_param(
            "~memory_file",
            os.getenv("FACE_MEMORY_FILE", str(DEFAULT_MEMORY_FILE)),
        )
        max_people = int(rospy.get_param("~max_people", os.getenv("FACE_MEMORY_MAX_PEOPLE", "4")))
        face_topic = rospy.get_param("~face_topic", os.getenv("FACE_MEMORY_TOPIC", "/qt_nuitrack_app/faces"))
        self.debug_log_interval = float(
            rospy.get_param("~debug_log_interval", os.getenv("FACE_MEMORY_DEBUG_LOG_INTERVAL", "2.0"))
        )
        self.store = FaceMemoryStore(memory_file, max_people=max_people)
        self.subscriber = None

        if Faces is None:
            rospy.logwarn("qt_nuitrack_app/Faces is unavailable; face memory will stay idle.")
            return

        self.subscriber = rospy.Subscriber(face_topic, Faces, self._faces_callback, queue_size=1)
        rospy.loginfo(
            "[FaceMemory] listening topic=%s max_people=%s file=%s debug_interval=%.1fs",
            face_topic,
            max_people,
            self.store.memory_file,
            self.debug_log_interval,
        )

    def _faces_callback(self, message):
        try:
            memory = self.store.observe_faces(message.faces)
            for event in memory.get("last_events", []):
                rospy.loginfo(
                    "[FaceMemory] event=%s person=%s tracking_id=%s evicted=%s",
                    event.get("type"),
                    event.get("person_id"),
                    event.get("tracking_id"),
                    event.get("evicted_person_id", "(none)"),
                )
            current_person = None
            for person in memory.get("people", []):
                if person.get("person_id") == memory.get("current_person_id"):
                    current_person = person
                    break

            if current_person:
                face = current_person.get("face", {})
                rospy.loginfo_throttle(
                    self.debug_log_interval,
                    (
                        "[FaceMemory] current=%s tracking_id=%s center=%s rect=%s "
                        "gender=%s age=%s visible=%s known=%s file=%s"
                    ),
                    current_person.get("person_id"),
                    current_person.get("face_tracking_id"),
                    face.get("center"),
                    face.get("rectangle"),
                    face.get("gender") or "unknown",
                    face.get("age_years") or "unknown",
                    memory.get("visible_person_ids", []),
                    len(memory.get("people", [])),
                    self.store.memory_file,
                )
            else:
                rospy.loginfo_throttle(
                    self.debug_log_interval,
                    "[FaceMemory] no current face visible; known=%s file=%s",
                    len(memory.get("people", [])),
                    self.store.memory_file,
                )
        except Exception as exc:
            rospy.logwarn_throttle(5.0, "Face memory update failed: %s", exc)


def main():
    if rospy is None:
        raise RuntimeError("rospy is required to run face_identity_memory.py")
    rospy.init_node("face_identity_memory", anonymous=False)
    FaceIdentityMemoryNode()
    rospy.spin()


if __name__ == "__main__":
    main()

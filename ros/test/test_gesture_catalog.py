#!/usr/bin/env python3
import argparse
import time

import rospy

try:
    from qt_gesture_controller.srv import gesture_play
except ImportError as exc:
    raise SystemExit(f"Cannot import qt_gesture_controller.srv.gesture_play: {exc}")


DEFAULT_GESTURES = [
    "swipe_right",
    "clapping",
    "one-arm-up",
    "hi",
    "point_front",
    "neutral",
    "angry",
    "up_right",
    "show_tablet",
    "show_QT",
    "kiss",
    "peekaboo",
    "train",
    "Show-face",
    "bored",
    "challenge",
    "hands-on-hip",
    "hands-on-belly-back",
    "hands-up",
    "hands-on-hip-back",
    "hands-up-back",
    "hands-side",
    "head-right-left",
    "hands-on-belly",
    "nodding-yes",
    "hands-on-head",
    "hands-side-back",
    "hands-on-head-back",
    "breathing_exercise",
    "personal-distance",
    "shy",
    "surprised",
    "disgusted",
    "calm",
    "afraid",
    "sad",
    "happy",
    "hoora",
    "show_right",
    "bye-bye",
    "yawn",
    "hand-front-hold",
    "Phone_call",
    "Beep",
    "Drive",
    "Fly",
    "Beeping",
    "Driving",
    "Dance-3-2",
    "Dance-1-1",
    "Dance-4-2",
    "Dance-2-4",
    "Dance-4-4",
    "Dance-4-5",
    "Dance-1-4",
    "Dance-3-1",
    "Dance-4-1",
    "Dance-2-1",
    "Dance-3-3",
    "Dance-1-3",
    "Dance-2-3",
    "Dance-4-3",
    "Dance-4-6",
    "Dance-2-2",
    "Dance-1-2",
    "touch-head",
    "bye",
    "drink",
    "show_left",
    "sneezing",
    "send_kiss",
    "surprise",
    "monkey",
    "peekaboo-back",
    "touch-head-back",
    "stretching",
    "up_left",
    "swipe_left",
    "modifial",
]

DEFAULT_PREFIX = "QT/"


def load_names(args):
    names = []
    if args.names:
        names.extend(name.strip() for name in args.names.split(",") if name.strip())
    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            for line in handle:
                name = line.strip()
                if name and not name.startswith("#"):
                    names.append(name)
    if not names:
        names = list(DEFAULT_GESTURES)

    prefix = "" if args.no_prefix else args.prefix
    if prefix:
        names = [
            name if name.startswith(prefix) else f"{prefix}{name}"
            for name in names
        ]

    unique = []
    seen = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def response_status(response):
    if hasattr(response, "status"):
        return bool(response.status), f"status={response.status}"
    if hasattr(response, "success"):
        return bool(response.success), f"success={response.success}"
    return True, str(response)


def main():
    parser = argparse.ArgumentParser(description="Test QTrobot gesture names one by one.")
    parser.add_argument("--names", help="Comma-separated gesture names to test.")
    parser.add_argument("--file", help="File containing one gesture name per line.")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--delay", type=float, default=2.5)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Prefix added to gesture names before calling the service.")
    parser.add_argument("--no-prefix", action="store_true", help="Call gesture names exactly as listed.")
    parser.add_argument("--yes", action="store_true", help="Run without confirmation.")
    args = parser.parse_args()

    names = load_names(args)
    print("=" * 56, flush=True)
    print("QTrobot gesture catalog test", flush=True)
    print(f"service=/qt_robot/gesture/play speed={args.speed} delay={args.delay}s", flush=True)
    print(f"count={len(names)}", flush=True)
    print("=" * 56, flush=True)

    if not args.yes:
        answer = input("Robot arms/head may move. Type YES to start: ").strip()
        if answer != "YES":
            print("Canceled.", flush=True)
            return

    rospy.init_node("qt_ai_assistant_gesture_catalog_test", anonymous=True)
    rospy.wait_for_service("/qt_robot/gesture/play", timeout=args.timeout)
    play_gesture = rospy.ServiceProxy("/qt_robot/gesture/play", gesture_play)

    results = []
    for index, name in enumerate(names, start=1):
        print(f"[{index:02d}/{len(names):02d}] gesture={name}", flush=True)
        started = time.monotonic()
        try:
            response = play_gesture(name, args.speed)
            ok, detail = response_status(response)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            marker = "OK" if ok else "FALSE"
            print(f"  -> {marker} {detail} elapsed={elapsed_ms:.1f}ms", flush=True)
            results.append((name, marker, detail))
        except Exception as exc:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            detail = f"{type(exc).__name__}: {exc}"
            print(f"  -> ERROR {detail} elapsed={elapsed_ms:.1f}ms", flush=True)
            results.append((name, "ERROR", detail))
        time.sleep(max(0.0, args.delay))

    print("=" * 56, flush=True)
    print("Gesture test summary", flush=True)
    for name, marker, detail in results:
        print(f"{marker:5s}  {name:22s}  {detail}", flush=True)
    print("=" * 56, flush=True)


if __name__ == "__main__":
    main()

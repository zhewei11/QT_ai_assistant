import zmq
import orjson
import queue
import threading
from config import logger

# ==========================================
# 1. communication bridge
# ==========================================
class ZMQBridge:

    # QT -> AI
    def __init__(self, pull_port=5555, push_port=5556, test_mode=False):
        self.test_mode = test_mode
        if not test_mode:
            self.context = zmq.Context()
            self.receiver = self.context.socket(zmq.PULL)
            self.receiver.bind(f"tcp://*:{pull_port}")

            self.push_endpoint = f"tcp://127.0.0.1:{push_port}"
            self.send_queue = queue.Queue()
            self.sender_ready = threading.Event()
            self.sender_thread = threading.Thread(
                target=self._sender_loop,
                name="zmq_robot_sender",
                daemon=True,
            )
            self.sender_thread.start()
            self.sender_ready.wait(timeout=2)
            logger.info(f"ZMQ Bridge (PULL={pull_port}, PUSH={push_port})")

    @staticmethod
    def _payload_summary(payload):
        action = payload.get("action", "")
        if action == "multimodal":
            speech = payload.get("speech") or payload.get("text", "")
            actions = payload.get("actions", [])
            action_names = [
                item.get("func_name", item.get("function_name", ""))
                for item in actions
                if item.get("func_name", item.get("function_name", ""))
            ]
            trace = payload.get("trace", {}) if isinstance(payload.get("trace"), dict) else {}
            return (
                f"action=multimodal request_id={payload.get('request_id', '-')} "
                f"speech_chars={len(speech)} actions={action_names or '[]'} "
                f"total_ai_ms={trace.get('total_ai_ms', '-')}"
            )
        if action == "function":
            return (
                f"action=function func={payload.get('function_name', payload.get('func_name', ''))} "
                f"args={payload.get('function_args', payload.get('func_args', {}))}"
            )
        return f"action={action or '(unset)'} keys={sorted(payload.keys())}"

    def _sender_loop(self):
        sender = self.context.socket(zmq.PUSH)
        sender.connect(self.push_endpoint)
        self.sender_ready.set()
        try:
            while True:
                payload = self.send_queue.get()
                if payload is None:
                    break
                try:
                    sender.send(orjson.dumps(payload))
                    logger.info("Sent payload to robot body: %s", self._payload_summary(payload))
                except Exception as exc:
                    logger.error(f"Failed to send payload to robot body: {exc}")
        finally:
            sender.close()

    # AI -> QT
    def wait_for_input(self):
        if self.test_mode:
            # Mac test mode
            print("\n" + "="*40)
            text = input("[Mac test mode] Please enter what you want to say to the robot: ")
            return {"source": "mac_terminal", "text": text, "language": "en-US"}
        else:
            msg = self.receiver.recv()
            return orjson.loads(msg)

    def send_action(self, action: str, text: str = "", func_name: str = "", func_args: dict = None):
        payload = {"action": action, "text": text}
        if action == "function":
            payload.update({"function_name": func_name, "function_args": func_args or {}})
        self.send_payload(payload)

    def send_payload(self, payload: dict):
        if self.test_mode:
            logger.info("[Mac test mode] Fake push action to robot body: %s", self._payload_summary(payload))
        else:
            self.send_queue.put(payload)

    def close(self):
        if self.test_mode:
            return
        self.send_queue.put(None)
        self.sender_thread.join(timeout=3)
        self.receiver.close()
        self.context.term()

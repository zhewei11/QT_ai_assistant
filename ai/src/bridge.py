import zmq
import orjson
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
            
            self.sender = self.context.socket(zmq.PUSH)
            self.sender.connect(f"tcp://127.0.0.1:{push_port}")
            logger.info(f"ZMQ Bridge (PULL={pull_port}, PUSH={push_port})")

    # AI -> QT
    def wait_for_input(self):
        if self.test_mode:
            # Mac test mode
            print("\n" + "="*40)
            text = input("[Mac test mode] Please enter what you want to say to the robot: ")
            return {"source": "mac_terminal", "text": text, "language": "zh-CN"}
        else:
            msg = self.receiver.recv()
            return orjson.loads(msg)

    def send_action(self, action: str, text: str = "", func_name: str = "", func_args: dict = None):
        payload = {"action": action, "text": text}
        if action == "function":
            payload.update({"function_name": func_name, "function_args": func_args or {}})
            
        if self.test_mode:
            logger.info(f"[Mac test mode] Fake push action to robot body: {payload}")
        else:
            self.sender.send(orjson.dumps(payload))
            logger.info(f"[Mac test mode] Fake push action to robot body: {payload}")

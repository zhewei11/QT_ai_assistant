import sys
import types
import unittest
from pathlib import Path


AI_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(AI_SRC))

fake_rag_module = types.ModuleType("rag_engine")
fake_rag_module.rag_engine = object()
sys.modules["rag_engine"] = fake_rag_module

from nodes import _is_ecg_measurement_command, router_node  # noqa: E402


class ECGIntentRoutingTest(unittest.TestCase):
    def route(self, text):
        return router_node({
            "input_text": text,
            "language": "zh-TW",
            "ai_latency": {},
        })["route_decision"]

    def test_short_result_commands_read_latest_ecg(self):
        for text in (
            "查看結果",
            "顯示結果",
            "显示结果。",
            "查看数据",
            "显示报告",
            "查看剛才的結果",
            "說明最新量測結果",
            "顯示心電圖量測結果",
            "我剛剛的心電圖結果是多少",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.route(text), "ecg_result")
                self.assertFalse(_is_ecg_measurement_command(text))

    def test_explicit_measurement_commands_start_ecg(self):
        for text in (
            "幫我測量心電圖",
            "請開始進行心電圖量測",
            "幫我重新測一次心跳",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.route(text), "system_control")
                self.assertTrue(_is_ecg_measurement_command(text))


if __name__ == "__main__":
    unittest.main()

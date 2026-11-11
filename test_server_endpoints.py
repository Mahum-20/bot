import unittest
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

class TestHistoricalInspectionEndpoints(unittest.TestCase):
    def test_chart_signals_h4(self):
        """Test that /api/chart_signals returns full October 2026 dataset and HTF levels for H4."""
        response = client.get("/api/chart_signals?symbol=BTCUSDT&timeframe=4h")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        candles = data.get("candles", [])
        self.assertGreaterEqual(len(candles), 184, "Should have at least all 184 October H4 candles plus lookback")
        
        # Check that candles cover October 1 to October 31
        oct_candles = [c for c in candles if 1790812800 <= c["time"] <= 1793491199]
        self.assertEqual(len(oct_candles), 184, "All 184 October 2026 H4 candles must be present")
        
        # Check that HTF structures are present
        boxes = data.get("boxes", [])
        self.assertGreater(len(boxes), 0, "HTF boxes must be generated")
        
        lines = data.get("lines", [])
        self.assertGreater(len(lines), 0, "HTF structure lines must be generated")
        
        labels = data.get("labels", [])
        self.assertGreater(len(labels), 0, "HTF labels must be generated")
        
        print(f"H4 Chart Signals: {len(candles)} candles ({len(oct_candles)} in Oct), {len(boxes)} boxes, {len(lines)} lines, {len(labels)} labels")

    def test_ltf_candles_for_h4_tap(self):
        """Test that /api/ltf_candles returns M5 candles and structure for an H4 candle tapping a zone."""
        # 1792267200 is an H4 candle in October that taps HTF A+ zone
        target_time = 1792267200
        response = client.get(f"/api/ltf_candles?symbol=BTCUSDT&interval=5m&target_time={target_time}&htf=4h")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        candles = data.get("candles", [])
        self.assertGreaterEqual(len(candles), 50, "Should have sufficient M5 candles around target H4 bar")
        
        tap_info = data.get("tap_info")
        self.assertIsNotNone(tap_info, "Zone tap must be detected on this historical candle")
        self.assertIn("winner_pathway", tap_info)
        
        # Check boxes on LTF (tapped zone, level 3/4 or QML/SBR)
        boxes = data.get("boxes", [])
        self.assertGreater(len(boxes), 0, "LTF structure boxes must be generated")
        
        # Check labels on LTF (e.g. W1..W5)
        labels = data.get("labels", [])
        self.assertGreater(len(labels), 0, "LTF labels must be generated")
        
        trade_logic = data.get("trade_logic")
        self.assertIsNotNone(trade_logic, "trade_logic must be present with execution or rejection details")
        
        print(f"LTF M5 for H4 tap {target_time}: {len(candles)} candles, winner: {tap_info.get('winner_pathway')}, boxes: {len(boxes)}, labels: {len(labels)}")

    def test_ltf_candles_for_untapped_h4_candle(self):
        """Test that /api/ltf_candles returns clean M5 view for an H4 candle that does not tap a zone."""
        # Choose a candle that doesn't tap any active zone
        target_time = 1790985600
        response = client.get(f"/api/ltf_candles?symbol=BTCUSDT&interval=5m&target_time={target_time}&htf=4h")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        candles = data.get("candles", [])
        self.assertGreaterEqual(len(candles), 50, "Should have M5 candles even when untapped")
        
        mtf_status = data.get("mtf_status", {})
        self.assertIn("Clean", mtf_status.get("message", ""))
        print(f"LTF M5 for untapped candle {target_time}: clean view confirmed, {len(candles)} candles")

if __name__ == "__main__":
    unittest.main()

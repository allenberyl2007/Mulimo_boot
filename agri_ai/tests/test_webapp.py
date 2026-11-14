"""Tests de l'interface locale de démonstration."""
import errno
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app


class WebAppTests(unittest.TestCase):
    def test_build_recommendation_uses_real_data_without_persisting(self):
        expected = {
            "crop": "maize",
            "alternative": "bean",
            "confidence": 0.46,
            "yield_t_ha": {"low": 2.3, "mid": 5.0, "high": 5.9},
            "reasons": ["Le risque de sécheresse est élevé."],
        }
        with patch.object(app.agri, "recommend", return_value=expected) as recommend:
            result = app.build_recommendation({"region": "mbandaka", "previous_crop": "bean", "slope": "5"})
        self.assertEqual(result["crop"], "maize")
        self.assertEqual(result["crop_name_en"], "Maize")
        self.assertEqual(result["alternative_name_en"], "Beans")
        self.assertEqual(result["reference_location"], "Mbandaka")
        self.assertTrue(result["caveats"])
        self.assertEqual(result["reasons_en"], ["Drought risk is high."])
        self.assertEqual(recommend.call_args.kwargs["mode"], "real")
        self.assertFalse(recommend.call_args.kwargs["persist"])
        self.assertEqual(recommend.call_args.kwargs["soil_site"], "mbandaka")

    def test_invalid_region_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "reference city"):
            app.build_recommendation({"region": "unknown"})

    def test_invalid_slope_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Slope"):
            app.build_recommendation({"region": "mbandaka", "slope": "NaN"})

    def test_explanation_translation(self):
        self.assertEqual(app.translate_reason("Le risque de sécheresse est élevé."), "Drought risk is high.")

    def test_rotation_comparison_uses_separate_model_and_closes_database(self):
        connection = Mock()
        expected = {"strategies": [{"crops": ["maize", "bean"]}]}
        payload = {
            "region": "mbandaka",
            "last_crop": "maize",
            "crop_before_last": "bean",
            "legume_crop": "bean",
            "slope": "5",
            "priorities": {
                "soil_carbon": "3",
                "erosion": "2",
                "nitrogen": "1",
                "water": "4",
                "food": "5",
            },
        }
        with patch.object(app, "connect_db", return_value=connection), patch.object(
            app, "compare_rotations", return_value=expected
        ) as compare:
            result = app.build_rotation_comparison(payload)

        self.assertEqual(result["reference_location"], "Mbandaka")
        self.assertEqual(result["strategies"][0]["crop_names"], ["Maize", "Beans"])
        self.assertEqual(compare.call_args.kwargs["last_crop"], "maize")
        self.assertEqual(compare.call_args.kwargs["crop_before_last"], "bean")
        self.assertEqual(compare.call_args.kwargs["priorities"]["food"], 5.0)
        connection.close.assert_called_once_with()

    def test_rotation_comparison_requires_declared_current_crop(self):
        with patch.object(app, "connect_db") as connect_db:
            with self.assertRaisesRegex(ValueError, "most recently grown crop"):
                app.build_rotation_comparison({"region": "mbandaka", "last_crop": "none"})
        connect_db.assert_not_called()

    def test_rotations_http_endpoint_returns_json(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.RequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        expected = {"strategies": [{"name": "Scenario A"}]}
        try:
            with patch.object(app, "build_rotation_comparison", return_value=expected):
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/rotations",
                    data=json.dumps({"last_crop": "maize"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read()), expected)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_create_server_uses_another_port_when_default_is_busy(self):
        fallback_server = Mock(server_address=("127.0.0.1", 8123))
        with patch.object(
            app,
            "LocalHTTPServer",
            side_effect=[OSError(errno.EADDRINUSE, "Address already in use"), fallback_server],
        ) as server_factory:
            with patch("builtins.print") as print_message:
                server = app.create_server()

        self.assertIs(server, fallback_server)
        self.assertEqual(server_factory.call_args_list[0].args[0], (app.HOST, app.PORT))
        self.assertEqual(server_factory.call_args_list[1].args[0], (app.HOST, 0))
        print_message.assert_called_once()

    def test_create_server_uses_another_real_local_port_when_default_is_busy(self):
        occupied = app.LocalHTTPServer((app.HOST, 0), app.RequestHandler)
        server = None
        try:
            with patch.object(app, "PORT", occupied.server_address[1]):
                with patch("builtins.print"):
                    server = app.create_server()
            self.assertNotEqual(server.server_address[1], occupied.server_address[1])
        finally:
            if server is not None:
                server.server_close()
            occupied.server_close()

    def test_create_server_does_not_hide_other_startup_errors(self):
        with patch.object(
            app,
            "LocalHTTPServer",
            side_effect=OSError(errno.EACCES, "Permission denied"),
        ) as server_factory:
            with self.assertRaises(OSError):
                app.create_server()

        server_factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()

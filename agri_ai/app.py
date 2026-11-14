"""Interface locale de démonstration pour l'aide à la décision agricole."""
import errno
import json
import math
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import main as agri
from core.crops import CROPS
from core.db import connect as connect_db
from core.rotation_model import compare_rotations

HOST = "127.0.0.1"
PORT = 8000
MAX_BODY_BYTES = 8192
HTML_PATH = os.path.join(HERE, "web", "index.html")


class LocalHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False


LOCATIONS = {
    "bukavu": "Bukavu",
    "kananga": "Kananga",
    "kinshasa": "Kinshasa",
    "kisangani": "Kisangani",
    "lubumbashi": "Lubumbashi",
    "mbandaka": "Mbandaka",
}
PREVIOUS_CROPS = {"none": None, "maize": "maize", "cassava": "cassava", "bean": "bean", "groundnut": "groundnut", "rice_upland": "rice_upland"}
CROP_NAMES = {
    "maize": "Maize",
    "cassava": "Cassava",
    "bean": "Beans",
    "groundnut": "Groundnuts",
    "rice_upland": "Upland rice",
}
LEVELS = {"faible": "low", "moyen": "moderate", "élevé": "high"}
REASON_TRANSLATIONS = {
    "Le sol manque d'azote.": "The soil may be low in nitrogen.",
    "Le sol manque d'azote, cette plante en a besoin de peu.": "The soil may be low in nitrogen; this crop has relatively low nitrogen needs.",
    "Le haricot améliore naturellement le sol : il prend l'azote de l'air.": "Beans can add nitrogen to the soil through biological nitrogen fixation.",
    "L'arachide améliore naturellement le sol : elle prend l'azote de l'air.": "Groundnuts can add nitrogen to the soil through biological nitrogen fixation.",
    "Le sol est assez acide, ce qui gêne un peu cette culture (de la chaux aiderait).": "Soil acidity may limit this crop; lime could help, but confirm with a local soil test.",
    "Cette culture protège bien le sol contre l'érosion.": "This crop may help protect the soil from erosion.",
    "Le sol risque de partir avec la pluie (érosion moyenne) : planter en travers de la pente aide.": "Moderate soil erosion is possible; planting across the slope may help.",
    "Attention : forte perte de terre par la pluie sur ce terrain en pente.": "High soil loss from rainfall is possible on this sloping land.",
    "Attention : la récolte attendue est très faible, même pour la meilleure culture. Améliorer le sol (engrais, chaux, compost) aiderait beaucoup.": "The estimated yield is very low even for the top-ranked crop. Soil amendments may help, but consult a local agronomist.",
}
CAVEATS = [
    "Hackathon prototype: the models were trained on simulations, not observed farm yields.",
    "NASA POWER weather is historical. SoilGrids is a nearby city reference point, not a test of your field.",
    "SoilGrids values are depth-weighted estimates for 0–30 cm near each city; phosphorus and potassium come from regional soil archetypes.",
    "Market prices and your available inputs are not included; the model uses default farming practices.",
    "The confidence score describes model uncertainty, not the probability of getting this harvest.",
    "This estimate does not guarantee a harvest and does not replace advice from a local agricultural extension worker.",
]


def translate_reason(reason):
    if reason in REASON_TRANSLATIONS:
        return REASON_TRANSLATIONS[reason]
    for french_level, english_level in LEVELS.items():
        if reason == f"Le risque de sécheresse est {french_level}.":
            return f"Drought risk is {english_level}."
        if reason == f"Le risque de fortes pluies et d'inondation est {french_level}.":
            return f"Heavy-rainfall and flooding risk is {english_level}."
        if reason == f"Besoin en eau : {french_level}.":
            return f"Water requirement is {english_level}."
    return "The model generated an explanation that is not yet available in English."


def build_recommendation(payload):
    if not isinstance(payload, dict):
        raise ValueError("The submitted form is invalid.")

    region = payload.get("region")
    if not isinstance(region, str) or region not in LOCATIONS:
        raise ValueError("Please choose a reference city from the list.")

    previous = payload.get("previous_crop", "none")
    if not isinstance(previous, str) or previous not in PREVIOUS_CROPS:
        raise ValueError("Please choose a previous crop from the list.")

    try:
        slope = float(payload.get("slope", 5))
    except (TypeError, ValueError) as exc:
        raise ValueError("Slope must be a number between 0 and 100.") from exc
    if not math.isfinite(slope) or not 0 <= slope <= 100:
        raise ValueError("Slope must be a number between 0 and 100.")

    management = dict(n_kg=0, p_kg=0, k_kg=0, lime_t=0, weeding=0.6,
                      residue_return=0.3, pest_control=0, seed_quality=0.5)
    result = agri.recommend(
        region=region,
        soil_site=region,
        slope=slope,
        mgmt=management,
        prev=PREVIOUS_CROPS[previous],
        mode="real",
        verbose=False,
        persist=False,
    )
    result["reference_location"] = LOCATIONS[region]
    result["crop_name_en"] = CROP_NAMES[result["crop"]]
    result["alternative_name_en"] = CROP_NAMES[result["alternative"]]
    result["reasons_en"] = [translate_reason(reason) for reason in result["reasons"]]
    result["caveats"] = CAVEATS
    return result


def build_rotation_comparison(payload):
    if not isinstance(payload, dict):
        raise ValueError("The submitted form is invalid.")

    region = payload.get("region")
    if not isinstance(region, str) or region not in LOCATIONS:
        raise ValueError("Please choose a reference city from the list.")

    last_crop = payload.get("last_crop")
    if not isinstance(last_crop, str) or last_crop not in CROPS:
        raise ValueError("Choose the most recently grown crop to compare rotation strategies.")

    crop_before_last = payload.get("crop_before_last", "none")
    if crop_before_last == "none":
        crop_before_last = None
    elif not isinstance(crop_before_last, str) or crop_before_last not in CROPS:
        raise ValueError("Choose a valid earlier crop or leave it unknown.")

    legume_crop = payload.get("legume_crop", "bean")
    if not isinstance(legume_crop, str) or legume_crop not in ("bean", "groundnut"):
        raise ValueError("Choose beans or groundnuts for the legume rotation.")

    try:
        slope = float(payload.get("slope", 5))
    except (TypeError, ValueError) as exc:
        raise ValueError("Slope must be a number between 0 and 100.") from exc
    if not math.isfinite(slope) or not 0 <= slope <= 100:
        raise ValueError("Slope must be a number between 0 and 100.")

    priority_keys = {"soil_carbon", "erosion", "nitrogen", "water", "food"}
    priorities = payload.get("priorities", {key: 1 for key in priority_keys})
    if not isinstance(priorities, dict) or set(priorities) != priority_keys:
        raise ValueError("Choose priorities for soil carbon, erosion, nitrogen, water, and food.")
    try:
        priorities = {key: float(value) for key, value in priorities.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError("Priority weights must be numbers from 0 to 5.") from exc
    if any(not math.isfinite(value) or not 0 <= value <= 5 for value in priorities.values()):
        raise ValueError("Priority weights must be numbers from 0 to 5.")

    con = connect_db()
    try:
        result = compare_rotations(
            con=con,
            region=region,
            slope=slope,
            last_crop=last_crop,
            crop_before_last=crop_before_last,
            legume_crop=legume_crop,
            priorities=priorities,
        )
    finally:
        con.close()

    result["reference_location"] = LOCATIONS[region]
    if crop_before_last:
        result["baseline_assumption"] = (
            f"The reference repeats your reported two-crop pattern "
            f"({CROP_NAMES[crop_before_last]}, {CROP_NAMES[last_crop]}), starting with "
            f"{CROP_NAMES[crop_before_last]}."
        )
    else:
        result["baseline_assumption"] = (
            f"The reference assumes {CROP_NAMES[last_crop]} is repeated because the earlier crop was not provided."
        )
    for strategy in result["strategies"]:
        strategy["crop_names"] = [CROP_NAMES[crop] for crop in strategy["crops"]]
    return result


class RequestHandler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False, default=float), "application/json; charset=utf-8")

    def do_GET(self):
        if urlsplit(self.path).path != "/":
            self._send_json(404, {"error": "Page not found."})
            return
        try:
            with open(HTML_PATH, encoding="utf-8") as page:
                body = page.read()
        except OSError:
            self.log_error("Unable to read the user interface: %s", HTML_PATH)
            self._send_json(500, {"error": "The user interface is temporarily unavailable."})
            return
        self._send(200, body, "text/html; charset=utf-8")

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/recommend", "/api/rotations"):
            self._send_json(404, {"error": "Service not found."})
            return
        if self.headers.get_content_type() != "application/json":
            self._send_json(415, {"error": "The form must be submitted as JSON."})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json(400, {"error": "Invalid request size."})
            return
        if length < 1 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "The submitted form is empty or too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if path == "/api/recommend":
                result = build_recommendation(payload)
            else:
                result = build_rotation_comparison(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "The submitted form is not valid JSON."})
            return
        except (ValueError, KeyError, TypeError) as exc:
            self._send_json(422, {"error": str(exc)})
            return
        except Exception as exc:
            action = "rotation comparison" if path == "/api/rotations" else "recommendation"
            self.log_error("Unexpected error while generating %s: %s", action, exc)
            if path == "/api/rotations":
                message = "The rotation comparison could not be calculated. Check that the local weather and soil data are available, then try again."
            else:
                message = "The recommendation could not be calculated. Please try again or ask a local agricultural extension worker."
            self._send_json(500, {"error": message})
            return
        self._send_json(200, result)


def create_server():
    try:
        return LocalHTTPServer((HOST, PORT), RequestHandler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        server = LocalHTTPServer((HOST, 0), RequestHandler)
        print(
            f"Port {PORT} is already in use; starting this demo separately on port "
            f"{server.server_address[1]}."
        )
        return server


def main():
    server = create_server()
    port = server.server_address[1]
    url = f"http://{HOST}:{port}"
    print(f"Offline demo ready: {url}")
    print("Press Ctrl+C to stop the server.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDemo stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

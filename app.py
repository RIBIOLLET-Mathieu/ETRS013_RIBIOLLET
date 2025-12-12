from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from zeep import Client
from flask import session
from service_projet import get_stations_proche
import json
import requests
from flask import jsonify, request
import openrouteservice as ors
import pprint

import time


ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImViOTg3ZGVjMGY2ODQ1YTliMGM1YTI2Y2ZjYzliZDczIiwiaCI6Im11cm11cjY0In0="  # Remplace par la tienne

app = Flask(__name__)
app.secret_key = "12345"  # clé pour utiliser la session

SOAP_WSDL = "http://127.0.0.1:8000/?wsdl"
client = Client(SOAP_WSDL)


# ------------- | Point 1) | ---------------
@app.route("/")
def index():
    return render_template("index.html")  # aucune donnée → pas de résultat affiché


@app.route("/calcul", methods=["POST"])
def calcul():
    distance = float(request.form["distance"])
    autonomie = float(request.form["autonomie"])
    recharge = float(request.form["recharge"])

    resultat = client.service.calcul_temps_trajet(distance, autonomie, recharge)

    # On stocke temporairement le résultat en session
    # OU dans une variable globale si tu préfères
    # → Ici solution simple avec `flask.session`

    session["resultat"] = round(resultat, 2)

    return redirect(url_for("resultat_page"))


@app.route("/resultat")
def resultat_page():
    resultat = session.pop("resultat", None)
    return render_template("index.html", resultat=resultat)


# ------------------------------------------


# ------------- | Point 2) | ---------------
@app.route("/station")
def station():
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    rayon = request.args.get("rayon")

    if not lat or not lon:
        return Response(
            json.dumps({"error": "Missing lat/lon"}, ensure_ascii=False),
            mimetype="application/json; charset=utf-8",
            status=400,
        )

    data = get_stations_proche(lat, lon, rayon)

    return Response(
        json.dumps(data, ensure_ascii=False), mimetype="application/json; charset=utf-8"
    )


# ------------------------------------------


# ------------- | Point 3) | ---------------
def geocode_city(city):
    url = "https://api.openrouteservice.org/geocode/search"

    headers = {"Authorization": ORS_API_KEY}
    params = {"text": city}

    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    data = r.json()

    coords = data["features"][0]["geometry"]["coordinates"]

    lon = coords[0]
    lat = coords[1]

    return lat, lon  # <- IMPORTANT : tu renvoies dans l’ordre que tu veux utiliser


def get_route(start_coords, end_coords):
    directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"

    body = {
        "coordinates": [
            [start_coords[1], start_coords[0]],
            [end_coords[1], end_coords[0]],
        ]
    }

    headers = {
        "Authorization": f"Bearer {ORS_API_KEY}",
        "Content-Type": "application/json",
    }

    r = requests.post(directions_url, json=body, headers=headers)
    data = r.json()

    if "routes" not in data or len(data["routes"]) == 0:
        return {"error": True, "message": "ORS n’a retourné aucune route."}

    route = data["routes"][0]

    # 🔥 DECODE DE LA POLYLINE (la grosse chaîne que tu as reçue)
    decoded = ors.convert.decode_polyline(route["geometry"])

    # print(f"Infos retournées du backend (calcul trajet) :\nDistance_m: {route['summary']['distance']}\nDuration_s: {route['summary']['duration']}\nGeometry: {decoded}")

    return {
        "distance_m": route["summary"]["distance"],
        "duration_s": route["summary"]["duration"],
        "geometry": decoded,  # → maintenant structure GeoJSON
    }


@app.route("/route")
def api_route():
    start = request.args.get("start")
    end = request.args.get("end")

    if not start or not end:
        return jsonify({"error": True, "message": "start et end obligatoires"})

    try:
        start_coords = geocode_city(start)
        end_coords = geocode_city(end)

        route = get_route(start_coords, end_coords)

        return jsonify(route)

    except Exception as e:
        return jsonify({"error": True, "message": str(e)})


# ------------- | Point 4) | ---------------
CHARGETRIP_URL = "https://api.chargetrip.io/graphql"
CHARGETRIP_CLIENT_ID = "693c273e71c4b62cdd1c4fd8"
CHARGETRIP_APP_ID = "693c273e71c4b62cdd1c4fda"


def debug_print(title, data):
    print("\n==============================")
    print(title)
    print("==============================")
    pprint.pprint(data)
    print("==============================\n")


@app.route("/vehicules")
def api_vehicules():
    page = int(request.args.get("page", 0))
    size = int(request.args.get("size", 20))

    query = f"""
    query {{
      vehicleList(page: {page}, size: {size}) {{
        id
        naming {{
          make
          model
          version
        }}
        battery {{
          usable_kwh
        }}
        range {{
          chargetrip_range {{
            best
            worst
          }}
        }}
        media {{
          image {{
            thumbnail_url
          }}
        }}
      }}
    }}
    """

    headers = {
        "x-client-id": CHARGETRIP_CLIENT_ID,
        "x-app-id": CHARGETRIP_APP_ID,
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(CHARGETRIP_URL, json={"query": query}, headers=headers)
        resp_json = r.json()

        # debug_print("DEBUG", resp_json)

        if "data" not in resp_json or "vehicleList" not in resp_json["data"]:
            return (
                jsonify(
                    {"error": True, "message": "Format inattendu", "raw": resp_json}
                ),
                500,
            )

        return jsonify({"error": False, "vehicules": resp_json["data"]["vehicleList"]})

    except Exception as e:
        return jsonify({"error": True, "message": str(e)}), 500


@app.route("/vehicule/<id>")
def api_vehicule(id):
    """
    Détail d'un véhicule + estimation du temps de recharge
    (car Chargetrip ne fournit pas charging/charge_time dans ce plan)
    """
    query = f"""
    query {{
      vehicle(id: "{id}") {{
        id
        naming {{
          make
          model
          version
        }}
        battery {{
          usable_kwh
        }}
        range {{
          chargetrip_range {{
            best
            worst
          }}
        }}
        media {{
          image {{
            thumbnail_url
          }}
        }}
      }}
    }}
    """

    headers = {
        "x-client-id": CHARGETRIP_CLIENT_ID,
        "x-app-id": CHARGETRIP_APP_ID,
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(CHARGETRIP_URL, json={"query": query}, headers=headers)
        resp = r.json()

        print("\n=== DEBUG VEHICULE ===")
        pprint.pprint(resp)

        veh = resp.get("data", {}).get("vehicle")
        if not veh:
            return (
                jsonify(
                    {"error": True, "message": "Véhicule introuvable", "raw": resp}
                ),
                404,
            )

        # ---- ESTIMATION recharge (le seul possible sans premium) ----
        usable = veh.get("battery", {}).get("usable_kwh") or 50  # kWh
        FAST_POWER = 150  # kW
        recharge_estimee = int((usable / FAST_POWER) * 60)  # minutes

        veh["recharge_estimee"] = recharge_estimee

        return jsonify({"error": False, "vehicule": veh})

    except Exception as e:
        return jsonify({"error": True, "message": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5050)

# ––– IMPORTS –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# Importation de Flask pour toute la partie Web
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    Response,
    session,
)

# Le service SOAP (que l'on intégre directement dans le app.py pour fonctionnement correct sur le Cloud)
from service_projet import wsgi_app as soap_app
from service_projet import get_stations_proche
from zeep import Client

# Monter plusieurs apps WSGI
from werkzeug.middleware.dispatcher import DispatcherMiddleware

# Divers librairies
import json
import requests
import openrouteservice as ors
import pprint
import os
from functools import lru_cache

# Partie sécurité. On envoie pas les clés sur Git et le Cloud
secret_flask = os.getenv("secret_flask")
ORS_API_KEY = os.getenv("ORS_API_KEY")
CHARGETRIP_URL = os.getenv("CHARGETRIP_URL")
CHARGETRIP_CLIENT_ID = os.getenv("CHARGETRIP_CLIENT_ID")
CHARGETRIP_APP_ID = os.getenv("CHARGETRIP_APP_ID")

# Sécurité minimale : fail fast si clé manquante
missing = []
if not secret_flask:
    missing.append("SECRET_FLASK")
if not ORS_API_KEY:
    missing.append("ORS_API_KEY")
if not CHARGETRIP_URL:
    missing.append("CHARGETRIP_URL")
if not CHARGETRIP_CLIENT_ID:
    missing.append("CHARGETRIP_CLIENT_ID")
if not CHARGETRIP_APP_ID:
    missing.append("CHARGETRIP_APP_ID")

if missing:
    raise RuntimeError(f"Variables d'environnement manquantes : {', '.join(missing)}")

# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– Recherche des stations en cache (performance) –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
@lru_cache(maxsize=128)
def get_stations_proche_cached(lat, lon, rayon):
    """
    Cache mémoire des stations proches
    Clé = (lat, lon, rayon)
    """
    return get_stations_proche(lat, lon, rayon)


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– INITIALISATION FLASK ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
app = Flask(__name__)
app.secret_key = secret_flask

# Le service SOAP sera accessible via /soap. L’application Flask principale reste active
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/soap": soap_app})
# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– CLES API EXTERNES –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# URL du WSDL SOAP
SOAP_WSDL = os.environ.get(
    "SOAP_WSDL", "https://USMB-ETRS013-Mathieu-ribiollet.azurewebsites.net/soap?wsdl"
)

_soap_client = None


def get_soap_client():
    global _soap_client
    if _soap_client is None:
        _soap_client = Client(SOAP_WSDL)
    return _soap_client


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– POINT 1 | Calcul trajet (SOAP + REST) –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
@app.route("/")
def index():
    """Page principale. Aucun résultat au chargement initial."""
    return render_template("index.html")


@app.route("/calcul", methods=["POST"])
def calcul():
    """Appel du service SOAP pour calculer le temps de trajet à partir d’un formulaire HTML."""
    distance = float(request.form["distance"])
    autonomie = float(request.form["autonomie"])
    recharge = float(request.form["recharge"])

    client = get_soap_client()
    client.service.calcul_temps_trajet(distance, autonomie, recharge)

    session["resultat"] = round(resultat, 2)

    return redirect(url_for("resultat_page"))


@app.route("/resultat")
def resultat_page():
    """Affiche le résultat stocké temporairement en session."""
    resultat = session.pop("resultat", None)
    return render_template("index.html", resultat=resultat)


@app.route("/api/calcul_trajet", methods=["POST"])
def api_calcul_trajet():
    """API REST simple : calcule uniquement le temps de conduite sans recharge."""
    data = request.json

    try:
        distance = float(data["distance"])
    except Exception as e:
        return jsonify({"error": True, "message": str(e)}), 400

    vitesse_moyenne = 100.0  # km/h
    temps_conduite_h = distance / vitesse_moyenne

    return jsonify({"error": False, "drive_h": round(temps_conduite_h, 4)})


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– POINT 2 | Bornes de recharge proche –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
@app.route("/station")
def station():
    """Retourne les stations de recharge proches d’une position GPS."""
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    rayon = request.args.get("rayon")

    if not lat or not lon:
        return Response(
            json.dumps({"error": "Missing lat/lon"}, ensure_ascii=False),
            mimetype="application/json; charset=utf-8",
            status=400,
        )

    # data contient les données brut retournées par l'API
    data = get_stations_proche_cached(lat, lon, rayon)

    return Response(
        json.dumps(data, ensure_ascii=False), mimetype="application/json; charset=utf-8"
    )


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– POINT 3 | Géocodage et itinéaire –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
def geocode_city(city):
    """Transforme un nom de ville en coordonnées GPS via OpenRouteService."""
    url = "https://api.openrouteservice.org/geocode/search"

    headers = {"Authorization": ORS_API_KEY}
    params = {"text": city}

    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    data = r.json()

    coords = data["features"][0]["geometry"]["coordinates"]

    # ORS retourne [lon, lat]
    lon = coords[0]
    lat = coords[1]

    # On retourne à "l'inverse" car on utilise à l'inverse en Front-End
    return lat, lon


def get_route(start_coords, end_coords):
    """Calcule un itinéraire voiture entre deux points GPS."""
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
    # On reconvertit la chaîne pour pouvoir l'exploiter en Front-End.
    decoded = ors.convert.decode_polyline(route["geometry"])

    # print(f"Infos retournées du backend (calcul trajet) :\nDistance_m: {route['summary']['distance']}\nDuration_s: {route['summary']['duration']}\nGeometry: {decoded}")

    return {
        "distance_m": route["summary"]["distance"],
        "duration_s": route["summary"]["duration"],
        "geometry": decoded,
    }


@app.route("/route")
def api_route():
    """API REST : calcule un itinéraire entre deux villes."""
    start = request.args.get("start")
    end = request.args.get("end")

    if not start or not end:
        return jsonify(
            {"error": True, "message": "Départ et Arrivée a remplir obligatoirement !"}
        )

    try:
        start_coords = geocode_city(start)
        end_coords = geocode_city(end)

        route = get_route(start_coords, end_coords)

        return jsonify(route)

    except Exception as e:
        return jsonify({"error": True, "message": str(e)})


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– POINT 4 | ChargeTrip (Véhicules) ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


def debug_print(title, data):
    """Fonction de debug, non utilisé depuis passage sur le Cloud"""
    print("\n==============================")
    print(title)
    print("==============================")
    pprint.pprint(data)
    print("==============================\n")


@app.route("/vehicules")
def api_vehicules():
    """Liste paginée des véhicules électriques."""
    page = int(request.args.get("page", 0))
    size = int(request.args.get("size", 20))

    # On vient récupérer l'ensemble des informations voulues
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

        # print("\n=== DEBUG VEHICULE ===")
        # pprint.pprint(resp)

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


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– POINT 5 | Itinéaire multi-bornes ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
@app.route("/route_multi", methods=["POST"])
def api_route_multi():
    """Calcule un itinéraire passant par plusieurs bornes de recharges"""
    data = request.json
    coords = data.get("coords")

    body = {"coordinates": [[lon, lat] for lat, lon in coords]}

    headers = {
        "Authorization": f"Bearer {ORS_API_KEY}",
        "Content-Type": "application/json",
    }

    r = requests.post(
        "https://api.openrouteservice.org/v2/directions/driving-car",
        json=body,
        headers=headers,
    )

    route = r.json()["routes"][0]
    decoded = ors.convert.decode_polyline(route["geometry"])

    return jsonify({"distance_m": route["summary"]["distance"], "geometry": decoded})


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

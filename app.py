from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from zeep import Client
from flask import session
from service_projet import get_station_proche
import json
import requests
from flask import jsonify, request

ORS_API_KEY = "TA_CLE_API_ORS"  # Remplace par la tienne

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

    if not lat or not lon:
        return Response(
            json.dumps({"error": "Missing lat/lon"}, ensure_ascii=False),
            mimetype="application/json; charset=utf-8",
            status=400,
        )

    data = get_station_proche(lat, lon)

    return Response(
        json.dumps(data, ensure_ascii=False), mimetype="application/json; charset=utf-8"
    )


# ------------------------------------------


# ------------- | Point 3) | ---------------
def get_route(city_start, city_end):
    """
    Retourne la géométrie du trajet entre deux villes via OpenRouteService.
    """

    # 1. Géocodage
    geocode_url = "https://api.openrouteservice.org/geocode/search"

    coords = []
    for city in (city_start, city_end):
        r = requests.get(geocode_url, params={"api_key": ORS_API_KEY, "text": city})
        r.raise_for_status()

        result = r.json()
        if not result["features"]:
            return {"error": True, "message": f"Ville inconnue : {city}"}

        lon, lat = result["features"][0]["geometry"]["coordinates"]
        coords.append([lon, lat])

    # 2. Calcul du trajet
    directions_url = "https://api.openrouteservice.org/v2/directions/driving-car"

    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}

    body = {"coordinates": coords}

    r = requests.post(directions_url, json=body, headers=headers)
    r.raise_for_status()

    data = r.json()

    geometry = data["features"][0]["geometry"]["coordinates"]

    return {"error": False, "route": geometry}


@app.route("/route")
def api_route():
    start = request.args.get("start")
    end = request.args.get("end")

    if not start or not end:
        return jsonify({"error": True, "message": "start et end obligatoires"})

    return jsonify(get_route(start, end))


if __name__ == "__main__":
    app.run(debug=True, port=5000)

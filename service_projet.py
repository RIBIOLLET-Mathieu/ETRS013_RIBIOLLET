from spyne import Application, rpc, ServiceBase, Float, Integer, ComplexModel
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from wsgiref.simple_server import make_server
import requests
import math


class TrajetResult(ComplexModel):
    total_h = Float
    nb_recharges = Integer
    recharge_min_total = Float


class TrajetService(ServiceBase):

    @rpc(Float, Float, Float, _returns=TrajetResult)
    def calcul_temps_trajet(ctx, distance_km, autonomie_km, temps_recharge_min):

        if autonomie_km <= 0:
            raise ValueError("Autonomie invalide")

        # ⚡ PARAMÈTRE MÉTIER (DOIT matcher le frontend)
        SEUIL_RECHARGE = 0.2  # 20 %

        # 🚗 Autonomie réellement exploitable
        autonomie_utilisable = autonomie_km * (1 - SEUIL_RECHARGE)

        # ⏱️ Temps de conduite
        vitesse_moyenne = 80.0  # km/h
        temps_conduite_h = distance_km / vitesse_moyenne

        # 🔁 Segments réels
        segments = math.ceil(distance_km / autonomie_utilisable)
        nb_recharges = max(0, segments - 1)

        # 🔌 Temps de recharge
        recharge_min_total = nb_recharges * temps_recharge_min
        temps_recharge_h = recharge_min_total / 60.0

        total_h = temps_conduite_h + temps_recharge_h

        return TrajetResult(
            total_h=total_h,
            nb_recharges=nb_recharges,
            recharge_min_total=recharge_min_total,
        )


def get_stations_proche(latitude, longitude, rayon_m, max_rows=200):
    """
    Retourne toutes les bornes IRVE dans un rayon donné,
    en filtrant strictement par distance et en supprimenant les doublons.
    """

    url = "https://odre.opendatasoft.com/api/records/1.0/search/"

    params = {
        "dataset": "bornes-irve",
        "geofilter.distance": f"{latitude},{longitude},{rayon_m}",
        "rows": max_rows,
    }

    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()

        if "records" not in data or not data["records"]:
            return {"error": True, "message": "Aucune borne trouvée dans le rayon."}

        stations = []
        seen_coords = set()

        for record in data["records"]:
            fields = record.get("fields", {})
            geometry = record.get("geometry", {})

            coords = geometry.get("coordinates", [None, None])
            lon, lat = coords[0], coords[1]

            if lat is None or lon is None:
                continue

            # distance renvoyée par ODRE → convertir en float
            dist_raw = fields.get("dist")
            if dist_raw is None:
                continue

            try:
                distance = float(dist_raw)
            except:
                continue  # valeur invalide → on ignore

            # filtrage strict
            if distance > float(rayon_m):
                continue

            # suppression doublons
            if (lat, lon) in seen_coords:
                continue
            seen_coords.add((lat, lon))

            station_info = {
                "station": fields.get("ad_station") or fields.get("n_station"),
                "acces_recharge": fields.get("acces_recharge"),
                "latitude": lat,
                "longitude": lon,
                "distance_m": distance,
            }

            stations.append(station_info)

        return {
            "error": False,
            "count": len(stations),
            "stations": sorted(stations, key=lambda x: x["distance_m"]),
        }

    except Exception as e:
        return {"error": True, "message": str(e)}


# Application SOAP
application = Application(
    [TrajetService],
    tns="spyne.trajet.service",
    in_protocol=Soap11(validator="lxml"),
    out_protocol=Soap11(),
)

wsgi_app = WsgiApplication(application)

### --- Lancement du service
if __name__ == "__main__":
    print("Service SOAP disponible sur http://127.0.0.1:8000")
    server = make_server("127.0.0.1", 8000, wsgi_app)
    server.serve_forever()

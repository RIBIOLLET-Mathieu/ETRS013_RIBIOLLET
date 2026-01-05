# ––– IMPORTS –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
from spyne import Application, rpc, ServiceBase, Float, Integer, ComplexModel
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
import requests
import time

# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– Forme des données SOAP ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
class TrajetResult(ComplexModel):
    """
    Objet SOAP retourné par le service calcul_temps_trajet.

    Il encapsule les informations principales du trajet :
    - durée totale
    - nombre de recharges
    - temps total passé à recharger
    """

    total_h = Float
    nb_recharges = Integer
    recharge_min_total = Float


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– Service SOAP ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
class TrajetService(ServiceBase):
    """
    Service SOAP exposant les méthodes métier
    liées au calcul de trajet en véhicule électrique.
    """

    @rpc(Float, Float, Float, Integer, _returns=TrajetResult)
    def calcul_temps_trajet(
        ctx, distance_km, autonomie_km, temps_recharge_min, nb_recharges
    ):
        """
        Calcule le temps total d'un trajet en tenant compte :
        - de la distance à parcourir
        - de l’autonomie du véhicule
        - du temps moyen d’une recharge
        - du nombre de recharges prévues
        """

        if autonomie_km <= 0:
            raise ValueError("Autonomie invalide")

        # La vitesse est définit en dure ici. Evolution possible : utilisé les données de temps de segments retournées par OpenRouteService
        vitesse_moyenne = 100.0  # km/h
        temps_conduite_h = distance_km / vitesse_moyenne

        recharge_min_total = nb_recharges * temps_recharge_min
        temps_recharge_h = recharge_min_total / 60.0

        total_h = temps_conduite_h + temps_recharge_h

        return TrajetResult(
            total_h=total_h,
            nb_recharges=nb_recharges,
            recharge_min_total=recharge_min_total,
        )


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– Service SOAP ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
def get_stations_proche(latitude, longitude, rayon_m, max_rows=15):
    """Récupère les bornes de recharge à proximité d’un point GPS en interrogeant l’API OpenDataSoft (bornes IRVE)."""
    url = "https://odre.opendatasoft.com/api/records/1.0/search/"
    params = {
        "dataset": "bornes-irve",
        "geofilter.distance": f"{latitude},{longitude},{rayon_m}",
        "rows": max_rows,
    }

    try:
        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        data = r.json()

        if "records" not in data or not data["records"]:
            return {"error": True, "message": "Aucune borne trouvée dans le rayon."}

        stations = []
        # Utilisation d'un set pour éviter les doublons
        seen_coords = set()

        for record in data["records"]:
            fields = record.get("fields", {})
            geometry = record.get("geometry", {})

            coords = geometry.get("coordinates", [None, None])
            lon, lat = coords[0], coords[1]

            if lat is None or lon is None:
                continue

            dist_raw = fields.get("dist")
            if dist_raw is None:
                continue

            try:
                distance = float(dist_raw)
            except:
                continue

            if distance > float(rayon_m):
                continue

            if (lat, lon) in seen_coords:
                continue
            seen_coords.add((lat, lon))

            # NOUVELLES INFOS
            acces = fields.get("acces_recharge")
            puiss_max = fields.get("puiss_max")

            # DEBUG CONSOLE
            # print("----- BORNE IRVE -----")
            # print("Station :", fields.get("ad_station") or fields.get("n_station"))
            # print("Accès   :", acces)
            # print("Puiss max :", puiss_max)
            # print("----------------------")

            station_info = {
                "station": fields.get("ad_station") or fields.get("n_station"),
                "acces_recharge": acces,
                "puiss_max": puiss_max,
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


# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


# ––– Application SOAP ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# Déclaration de l’application SOAP
application = Application(
    [TrajetService],
    tns="spyne.trajet.service",
    in_protocol=Soap11(validator="lxml"),
    out_protocol=Soap11(),
)


# Adaptation WSGI pour intégration dans Flask (fait éco au début du fichier app.py)
wsgi_app = WsgiApplication(application)

# –––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

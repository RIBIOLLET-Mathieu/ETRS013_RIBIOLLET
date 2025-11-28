from spyne import Application, rpc, ServiceBase, Float
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from wsgiref.simple_server import make_server
import requests


class TrajetService(ServiceBase):

    @rpc(Float, Float, Float, _returns=Float)
    def calcul_temps_trajet(ctx, distance_km, autonomie_km, temps_recharge_min):
        """
        distance_km : distance totale du trajet
        autonomie_km : autonomie du véhicule (km)
        temps_recharge_min : temps d'une recharge complète (minutes)
        """
        if autonomie_km <= 0:
            raise ValueError("L'autonomie doit être positive.")

        # Convertir minutes -> heures
        temps_recharge_h = temps_recharge_min / 60.0

        # Nombre de recharges nécessaires
        nb_recharges = max(0, int(distance_km // autonomie_km))

        # Temps de conduite (vitesse moyenne 100 km/h)
        temps_conduite = distance_km / 100.0

        # Temps total de recharge
        temps_total_recharge = nb_recharges * temps_recharge_h

        return temps_conduite + temps_total_recharge


def get_station_proche(latitude, longitude, rayon_m=3000):
    """
    Interroge l'API IRVE d'ODRE et retourne les mêmes champs que la requête officielle.
    """

    url = "https://odre.opendatasoft.com/api/records/1.0/search/"

    params = {
        "dataset": "bornes-irve",
        "geofilter.distance": f"{latitude},{longitude},{rayon_m}",
        "rows": 1,
    }

    try:
        r = requests.get(url, params=params, timeout=5)
        r.encoding = "utf-8"  # garantit un décodage correct côté Python
        r.raise_for_status()
        data = r.json()

        if "records" not in data or not data["records"]:
            return {"error": True, "message": "Aucune borne trouvée à proximité."}

        record = data["records"][0]
        fields = record["fields"]
        geometry = record.get("geometry", {})

        coords = geometry.get("coordinates", [None, None])

        # Champs identiques à la réponse ODRE
        response = {
            "id_station": fields.get("id_station"),
            "id_pdc": fields.get("id_pdc"),
            "station": fields.get("ad_station") or fields.get("n_station"),
            "n_amenageur": fields.get("n_amenageur"),
            "n_enseigne": fields.get("n_enseigne"),
            "n_operateur": fields.get("n_operateur"),
            "accessibilite": fields.get("accessibilite"),
            "acces_recharge": fields.get("acces_recharge"),
            "type_prise": fields.get("type_prise"),
            "nbre_pdc": fields.get("nbre_pdc"),
            "puiss_max": fields.get("puiss_max"),
            "commune": fields.get("commune"),
            "departement": fields.get("departement"),
            "region": fields.get("region"),
            "date_maj": fields.get("date_maj"),
            "source": fields.get("source"),
            "latitude": coords[1],
            "longitude": coords[0],
            "distance_m": fields.get("dist"),
        }

        return response

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

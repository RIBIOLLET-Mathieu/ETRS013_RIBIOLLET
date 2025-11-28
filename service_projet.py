from spyne import Application, rpc, ServiceBase, Float
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from wsgiref.simple_server import make_server


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


# Application SOAP
application = Application(
    [TrajetService],
    tns="spyne.trajet.service",
    in_protocol=Soap11(validator="lxml"),
    out_protocol=Soap11(),
)

wsgi_app = WsgiApplication(application)

### --- Lancement du service
print("Service SOAP disponible sur http://127.0.0.1:8000")
server = make_server("127.0.0.1", 8000, wsgi_app)
server.serve_forever()

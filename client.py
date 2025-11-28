from zeep import Client

client = Client("http://127.0.0.1:8000/?wsdl")

resultat = client.service.calcul_temps_trajet(
    distance_km=350, autonomie_km=150, temps_recharge_h=0.75
)

print(f"Temps total de trajet : {resultat:.2f} heures")

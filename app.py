from flask import Flask, render_template, request, redirect, url_for
from zeep import Client
from flask import session


app = Flask(__name__)
app.secret_key = "12345"  # clé pour utiliser la session

SOAP_WSDL = "http://127.0.0.1:8000/?wsdl"
client = Client(SOAP_WSDL)


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


if __name__ == "__main__":
    app.run(debug=True, port=5000)

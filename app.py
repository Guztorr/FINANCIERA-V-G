from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io
import os

app = Flask(__name__)

# ==========================
# CONFIGURACIÓN POSTGRESQL
# ==========================
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///local.db"  # fallback local
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ==========================
# CONSTANTES
# ==========================
MORA_POR_DIA = 50  # pesos por día de atraso

# ==========================
# MODELOS
# ==========================
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120))
    telefono = db.Column(db.String(50))
    direccion = db.Column(db.String(200))
    garantia = db.Column(db.String(200))
    monto = db.Column(db.Float)
    interes = db.Column(db.Float)
    frecuencia = db.Column(db.String(20))
    periodos = db.Column(db.Integer)
    total = db.Column(db.Float)
    pago = db.Column(db.Float)
    fecha = db.Column(db.String(20))
    liquidado = db.Column(db.Boolean, default=False)

    pagos = db.relationship(
        "Pago",
        backref="cliente",
        cascade="all, delete-orphan"
    )


class Pago(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"))
    numero = db.Column(db.Integer)
    periodo = db.Column(db.String(50))
    fecha = db.Column(db.String(20))
    monto = db.Column(db.Float)
    estado = db.Column(db.String(20))
    mora = db.Column(db.Float, default=0)
    dias_atraso = db.Column(db.Integer, default=0)


# ==========================
# RUTAS
# ==========================
@app.route("/")
def index():
    clientes = Cliente.query.all()
    return render_template("index.html", clientes=clientes)


@app.route("/nuevo", methods=["GET", "POST"])
def nuevo_cliente():
    if request.method == "POST":
        nombre = request.form["nombre"]
        telefono = request.form["telefono"]
        direccion = request.form["direccion"]
        garantia = request.form["garantia"]

        monto = float(request.form["monto"])
        interes = float(request.form["interes"])
        frecuencia = request.form["frecuencia"]
        periodos = int(request.form["periodos"])

        total = round(monto + (monto * interes / 100), 2)
        pago = round(total / periodos, 2)

        hoy = datetime.now()

        cliente = Cliente(
            nombre=nombre,
            telefono=telefono,
            direccion=direccion,
            garantia=garantia,
            monto=monto,
            interes=interes,
            frecuencia=frecuencia,
            periodos=periodos,
            total=total,
            pago=pago,
            fecha=hoy.strftime("%d/%m/%Y")
        )

        db.session.add(cliente)
        db.session.commit()

        for i in range(periodos):
            if frecuencia == "semanal":
                fecha_pago = hoy + timedelta(weeks=i + 1)
                etiqueta = "Semana"
            elif frecuencia == "quincenal":
                fecha_pago = hoy + timedelta(days=15 * (i + 1))
                etiqueta = "Quincena"
            else:
                fecha_pago = hoy + timedelta(days=30 * (i + 1))
                etiqueta = "Mes"

            pago_db = Pago(
                cliente_id=cliente.id,
                numero=i + 1,
                periodo=f"{etiqueta} {i + 1}",
                fecha=fecha_pago.strftime("%d/%m/%Y"),
                monto=pago,
                estado="Pendiente"
            )
            db.session.add(pago_db)

        db.session.commit()
        return redirect(url_for("ver_cliente", cliente_id=cliente.id))

    return render_template("nuevo.html")


@app.route("/cliente/<int:cliente_id>")
def ver_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    hoy = datetime.now()

    total_pagado = 0

    for p in cliente.pagos:
        fecha_pago = datetime.strptime(p.fecha, "%d/%m/%Y")

        if p.estado == "Pendiente" and fecha_pago < hoy:
            p.dias_atraso = (hoy - fecha_pago).days
            p.mora = p.dias_atraso * MORA_POR_DIA
        else:
            p.dias_atraso = 0
            p.mora = 0

        if p.estado == "Pagado":
            total_pagado += p.monto + p.mora

    restante = round(cliente.total - total_pagado, 2)
    if restante < 0:
        restante = 0

    cliente.liquidado = restante == 0
    db.session.commit()

    return render_template(
        "cliente.html",
        cliente=cliente,
        total_pagado=total_pagado,
        restante=restante
    )


@app.route("/abonar/<int:cliente_id>/<int:numero>")
def abonar(cliente_id, numero):
    pago = Pago.query.filter_by(
        cliente_id=cliente_id,
        numero=numero
    ).first_or_404()

    pago.estado = "Pagado"
    db.session.commit()

    return redirect(url_for("ver_cliente", cliente_id=cliente_id))


@app.route("/editar_cliente/<int:cliente_id>", methods=["POST"])
def editar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)

    cliente.nombre = request.form["nombre"]
    cliente.telefono = request.form["telefono"]
    cliente.direccion = request.form["direccion"]
    cliente.garantia = request.form["garantia"]

    db.session.commit()
    return redirect(url_for("ver_cliente", cliente_id=cliente_id))


@app.route("/eliminar_cliente/<int:cliente_id>")
def eliminar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    db.session.delete(cliente)
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/imprimir_pagos/<int:cliente_id>")
def imprimir_pagos(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 40

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "Historial de Pagos")
    y -= 30

    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Cliente: {cliente.nombre}")
    y -= 15
    pdf.drawString(40, y, f"Teléfono: {cliente.telefono}")
    y -= 15
    pdf.drawString(40, y, f"Fecha préstamo: {cliente.fecha}")
    y -= 25

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "Periodo")
    pdf.drawString(140, y, "Fecha")
    pdf.drawString(220, y, "Monto")
    pdf.drawString(290, y, "Mora")
    pdf.drawString(360, y, "Estado")
    y -= 15

    pdf.setFont("Helvetica", 10)
    total_pagado = 0

    for p in cliente.pagos:
        if y < 60:
            pdf.showPage()
            y = height - 40

        pdf.drawString(40, y, p.periodo)
        pdf.drawString(140, y, p.fecha)
        pdf.drawString(220, y, f"${p.monto}")
        pdf.drawString(290, y, f"${p.mora}")
        pdf.drawString(360, y, p.estado)

        if p.estado == "Pagado":
            total_pagado += p.monto + p.mora

        y -= 15

    restante = round(cliente.total - total_pagado, 2)
    if restante < 0:
        restante = 0

    y -= 20
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, f"Total préstamo: ${cliente.total}")
    y -= 15
    pdf.drawString(40, y, f"Total pagado: ${total_pagado}")
    y -= 15
    pdf.drawString(40, y, f"Restante: ${restante}")

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"pagos_{cliente.nombre}.pdf",
        mimetype="application/pdf"
    )


# ==========================
# MAIN
# ==========================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)

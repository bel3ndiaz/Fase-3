"""
Biblioteca Digital de Instrucciones de Trabajo - Impresos Múltiples
Desafío 2
"""
import mysql.connector
from datetime import date

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, abort)

app = Flask(__name__)
app.secret_key = "clave-solo-para-mensajes-flash"

AREAS = [
    "Impresión Offset",
    "Impresión Digital",
    "Preparación de Tintas",
    "Troquelado",
    "Acabados",
    "Encuadernación",
    "Mantenimiento",
    "Control de Calidad",
]



def conectar():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="biblioteca_impresos",
    )


@app.template_filter("fecha")
def formato_fecha(valor):
    """Muestra una fecha como 15/10/2026. MySQL entrega objetos de fecha (DATE)."""
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m/%Y")
    partes = str(valor).split("-")
    if len(partes) == 3:
        return partes[2] + "/" + partes[1] + "/" + partes[0]
    return valor


def clasificar(version, version_vigente):
    """Misma regla que usa /resumen, para mostrar el estado en el listado."""
    if version == version_vigente:
        return "vigente"
    elif version < version_vigente:
        return "desactualizada"
    else:
        return "por_revisar"


def es_version_valida(texto):
    """True si el texto es un número entero entre 1 y 9999."""
    return texto.isdecimal() and 1 <= int(texto) <= 9999


def validar_versiones(version, version_vigente):
    errores = []
    if not es_version_valida(version):
        errores.append("La versión debe ser un número entero entre 1 y 9999.")
    if not es_version_valida(version_vigente):
        errores.append("La versión vigente debe ser un número entero entre 1 y 9999.")
    return errores


def validar_enlace(enlace):
    if enlace != "" and not (enlace.startswith("http://") or enlace.startswith("https://")):
        return ["El enlace de video debe comenzar con http:// o https:// (o dejarse vacío)."]
    return []


@app.errorhandler(mysql.connector.Error)
def error_base_datos(error):
    """Si MySQL está apagado o falla una consulta, se muestra un mensaje claro."""
    return render_template("error.html", detalle=str(error)), 500


@app.route("/")
def inicio():
    return redirect(url_for("listar"))



@app.route("/instrucciones")
def listar():
    texto = request.args.get("q", "").strip()
    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)
    if texto == "":
        cursor.execute("SELECT * FROM instrucciones ORDER BY codigo")
    else:
        patron = "%" + texto + "%"
        cursor.execute(
            "SELECT * FROM instrucciones "
            "WHERE titulo LIKE %s OR codigo LIKE %s OR area LIKE %s ORDER BY codigo",
            (patron, patron, patron))
    filas = cursor.fetchall()
    cursor.close()
    conexion.close()

    instrucciones = []
    for fila in filas:
        estado = clasificar(fila["version"], fila["version_vigente"])
        instrucciones.append({"datos": fila, "estado": estado})
    return render_template("listado.html", instrucciones=instrucciones, q=texto)


@app.route("/instrucciones/<int:id>")
def detalle(id):
    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)
    # JOIN: une cada instrucción con sus versiones usando la llave foránea.
    # LEFT JOIN: si una instrucción no tuviera versiones, igual aparece.
    cursor.execute(
        "SELECT i.id, i.codigo, i.titulo, i.area, i.version, i.version_vigente, "
        "i.enlace_video, i.fecha_actualizacion, "
        "h.version AS version_historial, h.fecha AS fecha_historial "
        "FROM instrucciones i "
        "LEFT JOIN historial_versiones h ON h.instruccion_id = i.id "
        "WHERE i.id = %s ORDER BY h.version DESC", (id,))
    filas = cursor.fetchall()
    cursor.close()
    conexion.close()

    if len(filas) == 0:
        abort(404)

    fila = filas[0]  # los datos de la instrucción se repiten en cada fila del JOIN
    historial = []
    for f in filas:
        if f["version_historial"] is not None:
            historial.append({"version": f["version_historial"],
                              "fecha": f["fecha_historial"]})

    estado = clasificar(fila["version"], fila["version_vigente"])
    return render_template("detalle.html", i=fila, historial=historial, estado=estado)



@app.route("/instrucciones/nuevo", methods=["GET", "POST"])
def nuevo():
    errores = []
    if request.method == "POST":
        codigo = request.form["codigo"].strip().upper()
        titulo = request.form["titulo"].strip()
        area = request.form["area"]
        version = request.form["version"].strip()
        version_vigente = request.form["version_vigente"].strip()
        enlace = request.form["enlace_video"].strip()

        if codigo == "":
            errores.append("El código es obligatorio.")
        elif len(codigo) > 20:
            errores.append("El código no puede tener más de 20 caracteres.")
        if titulo == "":
            errores.append("El título es obligatorio.")
        elif len(titulo) > 100:
            errores.append("El título no puede tener más de 100 caracteres.")
        if area not in AREAS:
            errores.append("Selecciona un área de la lista.")
        errores = errores + validar_versiones(version, version_vigente) + validar_enlace(enlace)

        if not errores:
            hoy = date.today()
            if enlace == "":
                enlace = None  # sin enlace se guarda NULL en la base de datos
            conexion = conectar()
            cursor = conexion.cursor()
            try:
                cursor.execute(
                    "INSERT INTO instrucciones "
                    "(codigo, titulo, area, version, version_vigente, enlace_video, fecha_actualizacion) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (codigo, titulo, area, int(version), int(version_vigente), enlace, hoy))
                nuevo_id = cursor.lastrowid  # id que MySQL le asignó a la instrucción
                cursor.execute(
                    "INSERT INTO historial_versiones (instruccion_id, version, fecha) "
                    "VALUES (%s, %s, %s)", (nuevo_id, int(version), hoy))
                conexion.commit()
            except mysql.connector.IntegrityError:
                errores.append("Ya existe una instrucción con el código " + codigo + ".")
            cursor.close()
            conexion.close()
            if not errores:
                flash("Instrucción " + codigo + " registrada correctamente (versión " + version
                      + ") el " + formato_fecha(hoy) + ".")
                return redirect(url_for("listar"))

    return render_template("nuevo.html", errores=errores, datos=request.form, areas=AREAS)



@app.route("/instrucciones/editar/<int:id>", methods=["GET", "POST"])
def editar(id):
    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT * FROM instrucciones WHERE id = %s", (id,))
    fila = cursor.fetchone()
    if fila is None:
        cursor.close()
        conexion.close()
        abort(404)

    errores = []
    datos = fila  # valores que se muestran en el formulario
    if request.method == "POST":
        version = request.form["version"].strip()
        version_vigente = request.form["version_vigente"].strip()
        enlace = request.form["enlace_video"].strip()
        datos = request.form

        errores = validar_versiones(version, version_vigente) + validar_enlace(enlace)

        if not errores:
            hoy = date.today()
            if enlace == "":
                enlace = None
            cursor.execute(
                "UPDATE instrucciones SET version = %s, version_vigente = %s, "
                "enlace_video = %s, fecha_actualizacion = %s WHERE id = %s",
                (int(version), int(version_vigente), enlace, hoy, id))
            # Si cambió la versión, se agrega una fila nueva al historial
            if int(version) != fila["version"]:
                cursor.execute(
                    "INSERT INTO historial_versiones (instruccion_id, version, fecha) "
                    "VALUES (%s, %s, %s)", (id, int(version), hoy))
            conexion.commit()
            cursor.close()
            conexion.close()
            flash("Instrucción " + fila["codigo"] + " actualizada correctamente (versión " + version
                  + ") el " + formato_fecha(hoy) + ".")
            return redirect(url_for("listar"))

    cursor.close()
    conexion.close()
    return render_template("editar.html", i=fila, datos=datos, errores=errores)



@app.route("/instrucciones/eliminar/<int:id>", methods=["POST"])
def eliminar(id):
    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT codigo FROM instrucciones WHERE id = %s", (id,))
    fila = cursor.fetchone()
    if fila is None:
        cursor.close()
        conexion.close()
        abort(404)

    # Cuántas versiones tiene (solo para informar al usuario)
    cursor.execute(
        "SELECT COUNT(*) AS total FROM historial_versiones WHERE instruccion_id = %s", (id,))
    total_versiones = cursor.fetchone()["total"]

    # Solo se borra la instrucción: ON DELETE CASCADE borra sus versiones
    cursor.execute("DELETE FROM instrucciones WHERE id = %s", (id,))
    conexion.commit()
    cursor.close()
    conexion.close()
    flash("Instrucción " + fila["codigo"] + " eliminada. Versiones eliminadas en cascada: "
          + str(total_versiones) + ".")
    return redirect(url_for("listar"))



@app.route("/resumen")
def resumen():
    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT * FROM instrucciones ORDER BY codigo")
    filas = cursor.fetchall()
    cursor.close()
    conexion.close()

    # Contadores
    total_vigentes = 0
    total_desactualizadas = 0
    total_por_revisar = 0
    # Listas para mostrar cuáles instrucciones cayeron en cada clasificación
    vigentes = []
    desactualizadas = []
    por_revisar = []

    # Repetición: se recorre cada registro de la base de datos
    for fila in filas:
        # Decisión: se compara la versión del documento con la versión vigente
        if fila["version"] == fila["version_vigente"]:
            total_vigentes = total_vigentes + 1
            vigentes.append(fila)
        elif fila["version"] < fila["version_vigente"]:
            total_desactualizadas = total_desactualizadas + 1
            desactualizadas.append(fila)
        else:
            # La versión cargada es mayor que la vigente: dato inconsistente
            total_por_revisar = total_por_revisar + 1
            por_revisar.append(fila)

    return render_template(
        "resumen.html",
        total=len(filas),
        total_vigentes=total_vigentes,
        total_desactualizadas=total_desactualizadas,
        total_por_revisar=total_por_revisar,
        vigentes=vigentes,
        desactualizadas=desactualizadas,
        por_revisar=por_revisar,
    )


if __name__ == "__main__":
    app.run(debug=True)
"""
Biblioteca Digital de Instrucciones de Trabajo - Impresos Múltiples
Fase 3: documentos PDF/Word guardados en MySQL con historial de versiones
"""
import csv
import io
import os
import re
import mysql.connector
from datetime import date

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, abort, Response)

app = Flask(__name__)

# ---------------------------------------------------------------------
# Configuración. Los valores por defecto sirven para XAMPP en local; en otro
# entorno se cambian con variables de entorno, sin tocar el código ni subir
# contraseñas al repositorio (que es público).
#   SECRET_KEY, DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, FLASK_DEBUG (0 = apagado)
# ---------------------------------------------------------------------
app.secret_key = os.environ.get("SECRET_KEY", "clave-solo-para-desarrollo-local")
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "biblioteca_impresos"),
}


EXTENSIONES_PERMITIDAS = ["pdf", "doc", "docx"]
TAMANO_MAXIMO_MB = 5
TAMANO_MAXIMO = TAMANO_MAXIMO_MB * 1024 * 1024  # en bytes
# Límite duro de toda la petición: si alguien envía algo enorme, Flask lo corta
# antes de leerlo (error 413). Los archivos entre 5 y 16 MB llegan y se rechazan
# en la validación con un mensaje en el mismo formulario.
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

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
        **DB_CONFIG,
        # buffered: cada consulta se lee completa al ejecutarla, así se pueden
        # hacer varias consultas seguidas con el mismo cursor sin el error
        # "Unread result found" (por ejemplo: buscar la instrucción y luego
        # calcular MAX(version) antes de insertar el documento).
        buffered=True,
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


# Avance de cada instrucción según lo REALMENTE cargado: documento (tabla
# archivos) y video (enlace). Es la misma clasificación para /resumen, para el
# filtro del listado y para el CSV.
AVANCES = {
    "completa": "Con documento y video",
    "falta_video": "Falta el video",
    "falta_documento": "Falta el documento",
    "sin_nada": "Sin documento ni video",
}


def clasificar_avance(tiene_documento, tiene_video):
    """Decide en qué grupo de avance cae una instrucción (if/elif/else)."""
    if tiene_documento and tiene_video:
        return "completa"
    elif tiene_documento:
        return "falta_video"
    elif tiene_video:
        return "falta_documento"
    else:
        return "sin_nada"


PATRON_CODIGO = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)*$")


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


def limite_paquete_mysql(cursor):
    """Bytes que MySQL acepta en una sola consulta (max_allowed_packet).
    En XAMPP suele ser 1 MB; si el archivo no cabe, MySQL corta la conexión."""
    cursor.execute("SELECT @@max_allowed_packet AS limite")
    fila = cursor.fetchone()
    if isinstance(fila, dict):
        return int(fila["limite"])
    return int(fila[0])


@app.errorhandler(413)
def archivo_demasiado_grande(error):
    """La petición superó MAX_CONTENT_LENGTH: no se guarda nada."""
    flash("El archivo es demasiado grande. El máximo permitido es "
          + str(TAMANO_MAXIMO_MB) + " MB.", "error")
    return redirect(request.referrer or url_for("listar"))


@app.errorhandler(mysql.connector.Error)
def error_base_datos(error):
    """Si MySQL está apagado o falla una consulta, se muestra un mensaje claro."""
    return render_template("error.html", detalle=str(error)), 500


@app.route("/")
def inicio():
    return redirect(url_for("listar"))



# Columnas del listado. El documento vigente es la versión más reciente de la
# tabla archivos. Nunca se pide la columna contenido (LONGBLOB).
COLUMNAS_LISTADO = (
    "SELECT i.id, i.codigo, i.titulo, i.area, i.version, i.version_vigente, "
    "i.enlace_video, i.fecha_actualizacion, "
    "a.version AS version_actual, a.nombre_original AS archivo_vigente, "
    "a.extension, a.tamano_bytes, a.fecha_subida, "
    "(SELECT COUNT(*) FROM archivos x WHERE x.instruccion_id = i.id) AS total_versiones "
    "FROM instrucciones i "
    "LEFT JOIN archivos a ON a.instruccion_id = i.id "
    "AND a.version = (SELECT MAX(m.version) FROM archivos m WHERE m.instruccion_id = i.id) "
)


def filtros_desde_url():
    """Lee los filtros del listado (?q=&area=&avance=). Un valor que no existe en las
    listas se ignora. Los usan el listado y el CSV, así siempre coinciden."""
    texto = request.args.get("q", "").strip()
    area = request.args.get("area", "").strip()
    avance = request.args.get("avance", "").strip()
    if area not in AREAS:
        area = ""
    if avance not in AVANCES:
        avance = ""
    return texto, area, avance


def consultar_instrucciones(texto="", area="", avance=""):
    """Instrucciones (con su documento vigente) que cumplen los filtros dados.
    Cada fila trae la clave 'avance' calculada con clasificar_avance()."""
    condiciones = []
    parametros = []
    if texto != "":
        # \\, % y _ del texto se escapan para que se busquen tal cual
        limpio = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        patron = "%" + limpio + "%"
        condiciones.append("(i.titulo LIKE %s OR i.codigo LIKE %s OR i.area LIKE %s)")
        parametros.extend([patron, patron, patron])
    if area != "":
        condiciones.append("i.area = %s")
        parametros.append(area)
    consulta = COLUMNAS_LISTADO
    if condiciones:
        consulta += "WHERE " + " AND ".join(condiciones) + " "
    consulta += "ORDER BY i.codigo"

    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute(consulta, tuple(parametros))
    filas = cursor.fetchall()
    cursor.close()
    conexion.close()

    resultado = []
    for fila in filas:
        fila["avance"] = clasificar_avance(fila["version_actual"] is not None,
                                           bool(fila["enlace_video"]))
        # El avance se filtra aquí (no en SQL) para usar una sola regla en todo el sistema
        if avance == "" or fila["avance"] == avance:
            resultado.append(fila)
    return resultado


@app.route("/instrucciones")
def listar():
    texto, area, avance = filtros_desde_url()
    filas = consultar_instrucciones(texto, area, avance)
    instrucciones = []
    for fila in filas:
        # "estado" (regla de vigencia del Desafío 2) se conserva para el listado actual
        estado = clasificar(fila["version"], fila["version_vigente"])
        instrucciones.append({"datos": fila, "estado": estado})
    return render_template("listado.html", instrucciones=instrucciones, q=texto,
                           area=area, avance=avance, areas=AREAS, avances=AVANCES)


# Encabezados del CSV, en el mismo orden en que se escriben las columnas
ENCABEZADOS_CSV = [
    "Código", "Título", "Área", "Avance", "Documento vigente", "Tipo",
    "Versión vigente", "Total de versiones", "Tamaño", "Documento subido el",
    "Enlace de video", "Última actualización",
]


def celda_csv(valor):
    """Texto seguro para una celda de CSV. Excel ejecuta como fórmula lo que empieza
    con = + - @, así que se antepone una comilla para que se lea como texto."""
    if valor is None:
        return ""
    texto = str(valor)
    if texto[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + texto
    return texto


def tamano_csv(num_bytes):
    """850 KB o 1.2 MB. Propio del CSV: no depende de los filtros de plantilla."""
    if num_bytes < 1024 * 1024:
        return str(max(1, round(num_bytes / 1024))) + " KB"
    return str(round(num_bytes / (1024 * 1024), 1)) + " MB"


def fecha_hora_csv(valor):
    """15/10/2026 14:05"""
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m/%Y %H:%M")
    return str(valor)


@app.route("/instrucciones/exportar.csv")
def exportar_csv():
    """Descarga el listado como CSV aplicando los MISMOS filtros que el listado."""
    texto, area, avance = filtros_desde_url()
    filas = consultar_instrucciones(texto, area, avance)

    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(ENCABEZADOS_CSV)
    for f in filas:
        tiene_doc = f["version_actual"] is not None
        escritor.writerow([celda_csv(valor) for valor in [
            f["codigo"], f["titulo"], f["area"], AVANCES[f["avance"]],
            f["archivo_vigente"],
            f["extension"].upper() if tiene_doc else None,
            ("v" + str(f["version_actual"])) if tiene_doc else None,
            f["total_versiones"],
            tamano_csv(f["tamano_bytes"]) if tiene_doc else None,
            fecha_hora_csv(f["fecha_subida"]) if tiene_doc else None,
            f["enlace_video"],
            formato_fecha(f["fecha_actualizacion"]),
        ]])

    # utf-8-sig agrega la marca BOM: así Excel muestra bien las tildes y la ñ
    contenido = salida.getvalue().encode("utf-8-sig")
    nombre = "instrucciones_" + date.today().isoformat() + ".csv"
    return Response(contenido, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=" + nombre})


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
        elif not PATRON_CODIGO.match(codigo):
            errores.append("El código solo puede tener letras, números y guiones (ej. IM-OFF-003).")
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

    # Las llaves foráneas son ON DELETE RESTRICT: si la instrucción tiene
    # historial o documentos, MySQL rechaza el DELETE con un IntegrityError.
    try:
        cursor.execute("DELETE FROM instrucciones WHERE id = %s", (id,))
        conexion.commit()
        flash("Instrucción " + fila["codigo"] + " eliminada.")
    except mysql.connector.Error as error:
        # 1451 (o 1217 en versiones viejas): MySQL no deja borrar porque hay filas
        # relacionadas (ON DELETE RESTRICT). Cualquier otro error se deja pasar.
        if error.errno not in (1451, 1217):
            raise
        conexion.rollback()
        flash("No se puede eliminar " + fila["codigo"] + ": tiene " + str(total_versiones)
              + " versión(es) en su historial y la base de datos las protege (ON DELETE RESTRICT).",
              "error")
    cursor.close()
    conexion.close()
    return redirect(url_for("listar"))



@app.context_processor
def utilidades_plantillas():
    """Permite que una plantilla enlace a una ruta solo si ya existe en la aplicación
    (así /resumen no falla mientras otra parte del equipo aún no integra 'subir')."""
    return {"ruta_existe": lambda nombre: nombre in app.view_functions}


@app.route("/resumen")
def resumen():
    filas = consultar_instrucciones()

    # Una lista por cada grupo de avance, para mostrar cuáles instrucciones cayeron en él
    grupos = {clave: [] for clave in AVANCES}
    # Avance por área: se incluyen todas las áreas, aunque todavía no tengan instrucciones
    por_area = {}
    for nombre in AREAS:
        por_area[nombre] = {"area": nombre, "total": 0, "con_documento": 0,
                            "con_video": 0, "completas": 0}

    con_documento = 0
    con_video = 0
    total_versiones = 0

    # Repetición: se recorre cada instrucción una sola vez
    for fila in filas:
        grupos[fila["avance"]].append(fila)

        tiene_documento = fila["version_actual"] is not None
        tiene_video = bool(fila["enlace_video"])
        total_versiones = total_versiones + fila["total_versiones"]
        if tiene_documento:
            con_documento = con_documento + 1
        if tiene_video:
            con_video = con_video + 1

        if fila["area"] not in por_area:  # área que ya no está en la lista oficial
            por_area[fila["area"]] = {"area": fila["area"], "total": 0, "con_documento": 0,
                                      "con_video": 0, "completas": 0}
        datos_area = por_area[fila["area"]]
        datos_area["total"] = datos_area["total"] + 1
        if tiene_documento:
            datos_area["con_documento"] = datos_area["con_documento"] + 1
        if tiene_video:
            datos_area["con_video"] = datos_area["con_video"] + 1
        if fila["avance"] == "completa":
            datos_area["completas"] = datos_area["completas"] + 1

    # Porcentaje de avance = instrucciones completas / instrucciones del área
    areas = []
    for datos_area in por_area.values():
        if datos_area["total"] > 0:
            datos_area["porcentaje"] = round(100 * datos_area["completas"] / datos_area["total"])
        else:
            datos_area["porcentaje"] = 0
        areas.append(datos_area)

    total = len(filas)
    porcentaje_global = round(100 * len(grupos["completa"]) / total) if total > 0 else 0

    return render_template(
        "resumen.html",
        total=total,
        con_documento=con_documento,
        con_video=con_video,
        total_versiones=total_versiones,
        porcentaje_global=porcentaje_global,
        grupos=grupos,
        titulos=AVANCES,
        areas=areas,
    )


if __name__ == "__main__":
    # El modo debug queda encendido por defecto para desarrollar en local.
    # Para apagarlo: FLASK_DEBUG=0
    app.run(debug=os.environ.get("FLASK_DEBUG", "1") == "1")

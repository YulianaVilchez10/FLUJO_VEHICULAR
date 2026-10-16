"""Panel de flujo vehicular: Streamlit + Supabase + Groq.
Instalación: pip install -r requirements.txt
Ejecución: streamlit run app.py
"""
import re
import smtplib
import hmac
import io
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from email.utils import parseaddr
import unicodedata
import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client
from groq import Groq

st.set_page_config(page_title="Flujo Vehicular | Perú", page_icon="🚗", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.stApp{background:#f5f8fc;color:#172b4d}
.block-container{padding-top:2rem;max-width:1450px}
h1,h2,h3{color:#102e55;letter-spacing:-.5px}
[data-testid="stMetric"]{background:white;border:1px solid #e0e8f3;border-radius:16px;padding:18px;box-shadow:0 4px 15px #16335a08}
[data-testid="stSidebar"]{background:#eaf1fa}
div.stButton>button[kind="primary"]{background:#1959a6;border-radius:10px}
[data-testid="stChatMessage"]{background:white;border:1px solid #e3eaf4;border-radius:14px}
</style>""", unsafe_allow_html=True)

NUMERICAS = ["ANIO", "MES", "VEH_TOTAL", "VEH_LIGEROS_TOTAL", "VEH_PESADOS_TOTAL", "VEH_IMD", "VEH_LIGEROS_IMD", "VEH_PESADOS_IMD"]

@st.cache_resource
def cliente_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

@st.cache_data(ttl=300, show_spinner="Consultando registros de Supabase...")
def cargar_datos():
    cliente = cliente_supabase()
    registros = []
    inicio = 0
    while True:
        lote = cliente.table("FLUJO_VEHICULAR").select("*").range(inicio, inicio + 999).execute().data or []
        registros.extend(lote)
        if len(lote) < 1000:
            break
        inicio += 1000
        if inicio > 200000:
            raise RuntimeError("Se alcanzó el límite de seguridad de descarga (200.000 filas).")
    df = pd.DataFrame(registros)
    for campo in NUMERICAS:
        if campo in df.columns:
            df[campo] = pd.to_numeric(df[campo].astype(str).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
    for campo in ["DEPARTAMENTO", "NOMBRE_PEAJE"]:
        if campo in df.columns:
            df[campo] = df[campo].fillna("Sin dato").astype(str).str.strip()
    return df

def fmt(n):
    return f"{n:,.0f}".replace(",", " ")

def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn")

def agrupar(df, campo, cantidad="VEH_TOTAL"):
    return df.groupby(campo, dropna=False, as_index=False)[cantidad].sum().sort_values(cantidad, ascending=False)

def grafico_barras(tabla, x, y="VEH_TOTAL", horizontal=False):
    if horizontal:
        fig = px.bar(tabla, x=y, y=x, orientation="h", color=y, color_continuous_scale="Blues")
        fig.update_layout(yaxis={"categoryorder":"total ascending"})
    else:
        fig = px.bar(tabla, x=x, y=y, color=y, color_continuous_scale="Blues")
    fig.update_layout(template="plotly_white", coloraxis_showscale=False, margin=dict(l=10,r=10,t=15,b=10), height=390)
    return fig


# SEGURIDAD: este módulo está protegido con una contraseña administrativa.
# La clave SERVICE_ROLE solo se usa en el servidor, nunca en el navegador.
def email_valido(valor):
    nombre, direccion = parseaddr(valor.strip())
    return not nombre and direccion == valor.strip() and re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", direccion) is not None


def enviar_correo(destinatario, asunto, cuerpo, csv_bytes=None):
    remitente = st.secrets["GMAIL_USER"]
    clave = st.secrets["GMAIL_APP_PASSWORD"].replace(" ", "")
    msg = EmailMessage()
    msg["From"] = remitente
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.set_content(cuerpo)
    if csv_bytes:
        msg.add_attachment(csv_bytes, maintype="text", subtype="csv", filename="reporte_flujo_vehicular.csv")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25) as smtp:
        smtp.login(remitente, clave)
        smtp.send_message(msg)


def cliente_correos():
    # Necesita SUPABASE_SERVICE_ROLE_KEY, solo en Secrets de Streamlit.
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_ROLE_KEY"])


def generar_informe(df):
    total = int(df["VEH_TOTAL"].sum())
    ligeros = int(df["VEH_LIGEROS_TOTAL"].sum())
    pesados = int(df["VEH_PESADOS_TOTAL"].sum())
    tabla = agrupar(df, "DEPARTAMENTO")
    mayor = tabla.iloc[0]["DEPARTAMENTO"] if not tabla.empty else "Sin datos"
    cuerpo = ("INFORME DE FLUJO VEHICULAR - PERÚ\n\n"
              f"Registros analizados: {fmt(len(df))}\n"
              f"Vehículos totales: {fmt(total)}\n"
              f"Vehículos ligeros: {fmt(ligeros)}\n"
              f"Vehículos pesados: {fmt(pesados)}\n"
              f"Departamento con mayor flujo registrado: {mayor}\n\n"
              "Cuadro comparativo por departamento:\n"
              + tabla.to_string(index=False) +
              "\n\nNota: cifras calculadas a partir de los filtros y registros disponibles al preparar este informe.")
    return cuerpo, tabla.to_csv(index=False).encode("utf-8-sig")

st.sidebar.title("🚗 Flujo Vehicular")
seccion = st.sidebar.radio("Navegación", ["📊 Dashboard", "📋 Registros", "📈 Análisis estadístico", "🤖 Asistente IA", "📧 Agente 2 · Correos"])
st.sidebar.divider()
if st.sidebar.button("🔄 Actualizar datos"):
    cargar_datos.clear()
    st.rerun()

try:
    datos = cargar_datos()
except Exception as exc:
    st.error("No se pudieron cargar o procesar los datos. Revisa el detalle técnico mostrado debajo.")
    st.code(str(exc))
    st.stop()
if datos.empty:
    st.warning("La tabla no devolvió registros. Revisa los permisos SELECT/RLS de tu clave.")
    st.stop()
requeridas = {"DEPARTAMENTO", "NOMBRE_PEAJE", "ANIO", "VEH_TOTAL", "VEH_LIGEROS_TOTAL", "VEH_PESADOS_TOTAL"}
faltantes = requeridas - set(datos.columns)
if faltantes:
    st.error(f"Faltan columnas en FLUJO_VEHICULAR: {', '.join(sorted(faltantes))}")
    st.stop()

st.sidebar.subheader("Filtros generales")
deps = sorted(datos["DEPARTAMENTO"].dropna().unique().tolist())
dep = st.sidebar.selectbox("Departamento", ["Todos"] + deps)
anios = sorted(int(a) for a in datos["ANIO"].dropna().unique())
anio = st.sidebar.selectbox("Año", ["Todos"] + anios)
filtrado = datos.copy()
if dep != "Todos": filtrado = filtrado[filtrado["DEPARTAMENTO"] == dep]
if anio != "Todos": filtrado = filtrado[filtrado["ANIO"] == anio]
peajes = sorted(filtrado["NOMBRE_PEAJE"].dropna().unique().tolist())
peaje = st.sidebar.selectbox("Peaje", ["Todos"] + peajes)
if peaje != "Todos": filtrado = filtrado[filtrado["NOMBRE_PEAJE"] == peaje]
st.sidebar.caption(f"{fmt(len(filtrado))} filas seleccionadas · Datos de Supabase")

st.title("🚗 Sistema Inteligente de Flujo Vehicular")
st.caption("Peajes del Perú · Indicadores, comparaciones y análisis asistido por IA")

if seccion == "📊 Dashboard":
    st.subheader("Panorama general")
    a,b,c,d = st.columns(4)
    a.metric("🚙 Vehículos totales", fmt(filtrado["VEH_TOTAL"].sum()))
    b.metric("🚗 Ligeros", fmt(filtrado["VEH_LIGEROS_TOTAL"].sum()))
    c.metric("🚚 Pesados", fmt(filtrado["VEH_PESADOS_TOTAL"].sum()))
    d.metric("🧾 Registros", fmt(len(filtrado)))
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Departamentos con mayor flujo")
        t = agrupar(filtrado, "DEPARTAMENTO").head(12)
        st.plotly_chart(grafico_barras(t, "DEPARTAMENTO", horizontal=True), use_container_width=True)
    with col2:
        st.subheader("Evolución anual")
        t = filtrado.groupby("ANIO", as_index=False)["VEH_TOTAL"].sum().sort_values("ANIO")
        fig = px.line(t, x="ANIO", y="VEH_TOTAL", markers=True)
        fig.update_layout(template="plotly_white", height=390, margin=dict(l=10,r=10,t=15,b=10))
        st.plotly_chart(fig, use_container_width=True)
    st.info("Los totales reflejan los registros disponibles y los filtros elegidos; si 2026 es parcial, no equivale a un año completo.")

elif seccion == "📋 Registros":
    st.subheader("Consulta de registros")
    buscar = st.text_input("Buscar peaje o departamento", placeholder="Ej. Lima, Corcona...")
    vista = filtrado
    if buscar:
        patron = re.escape(buscar)
        vista = vista[vista["NOMBRE_PEAJE"].str.contains(patron, case=False, na=False) | vista["DEPARTAMENTO"].str.contains(patron, case=False, na=False)]
    st.caption(f"{fmt(len(vista))} registros encontrados")
    st.dataframe(vista, use_container_width=True, height=500, hide_index=True)
    st.download_button("⬇️ Descargar registros filtrados (CSV)", vista.to_csv(index=False).encode("utf-8-sig"), "flujo_vehicular_filtrado.csv", "text/csv")

elif seccion == "📈 Análisis estadístico":
    st.subheader("Comparaciones estadísticas")
    dimension = st.selectbox("Comparar por", ["DEPARTAMENTO", "NOMBRE_PEAJE", "ANIO", "MES"])
    variable = st.selectbox("Indicador", ["VEH_TOTAL", "VEH_LIGEROS_TOTAL", "VEH_PESADOS_TOTAL"])
    tabla = agrupar(filtrado, dimension, variable)
    max_filas = st.slider("Elementos a visualizar", 5, 30, 12)
    tabla = tabla.head(max_filas)
    st.plotly_chart(grafico_barras(tabla, dimension, variable, horizontal=dimension in ["DEPARTAMENTO", "NOMBRE_PEAJE"]), use_container_width=True)
    st.dataframe(tabla.rename(columns={dimension:"Categoría", variable:"Vehículos"}), use_container_width=True, hide_index=True)
    st.download_button("⬇️ Descargar cuadro comparativo", tabla.to_csv(index=False).encode("utf-8-sig"), "comparacion.csv", "text/csv")

elif seccion == "🤖 Asistente IA":
    st.subheader("🤖 Asistente IA con gráficos y cuadros comparativos")
    st.caption("El sistema calcula cifras con los datos de Supabase; Groq explica los resultados. Los filtros laterales también se aplican aquí.")
    if "historial_flujo" not in st.session_state:
        st.session_state.historial_flujo = []
    if st.button("🧹 Limpiar conversación"):
        st.session_state.historial_flujo = []
        st.rerun()
    for entrada in st.session_state.historial_flujo:
        with st.chat_message("user"):
            st.write(entrada["pregunta"])
        with st.chat_message("assistant"):
            st.markdown(entrada["respuesta"])
            if entrada["tabla"] is not None:
                st.plotly_chart(grafico_barras(entrada["tabla"], entrada["dimension"], entrada["metrica"], entrada["horizontal"]), use_container_width=True, key=f"grafico_{entrada['id']}")
                st.dataframe(entrada["tabla"], hide_index=True, use_container_width=True)
    pregunta = st.chat_input("Ej. Compara Lima y Arequipa en 2024; ¿qué peajes tienen mayor tránsito?")
    if pregunta:
        p = sin_tildes(pregunta)
        # La selección de dimensión es determinista: la IA NO genera SQL ni ejecuta código.
        if any(t in p for t in ["peaje", "estacion"]):
            dimension = "NOMBRE_PEAJE"
        elif any(t in p for t in ["mes", "mensual"]):
            dimension = "MES"
        elif any(t in p for t in ["ano", "anual", "evolucion", "tendencia", "202"]):
            dimension = "ANIO"
        else:
            dimension = "DEPARTAMENTO"
        if "pesad" in p and "liger" not in p:
            metrica = "VEH_PESADOS_TOTAL"
        elif "liger" in p and "pesad" not in p:
            metrica = "VEH_LIGEROS_TOTAL"
        else:
            metrica = "VEH_TOTAL"
        consulta = filtrado.copy()
        # Permitir comparar departamentos nombrados incluso con el filtro lateral en 'Todos'.
        # Los filtros explícitos de la barra lateral se respetan siempre.
        if dimension == "DEPARTAMENTO":
            menciones = [d for d in consulta["DEPARTAMENTO"].unique() if sin_tildes(d) in p]
            if menciones:
                consulta = consulta[consulta["DEPARTAMENTO"].isin(menciones)]
        if dimension != "ANIO":
            anos_mencionados = [int(x) for x in re.findall(r"\b20\d{2}\b", p)]
            if anos_mencionados:
                consulta = consulta[consulta["ANIO"].isin(anos_mencionados)]
        tabla = agrupar(consulta, dimension, metrica).head(12)
        total = int(consulta[metrica].sum())
        resumen = tabla.to_csv(index=False)
        instrucciones = (
            "Eres un analista de flujo vehicular peruano. Responde en español claro y breve. "
            "Utiliza EXCLUSIVAMENTE los datos calculados que siguen. No inventes cifras, fechas ni causas. "
            "Explica la comparación, menciona cifras exactas y una conclusión. "
            "Si los datos son insuficientes, dilo. Los gráficos y cuadros los dibuja la aplicación, no tú."
        )
        contexto = f"Pregunta: {pregunta}\nDimensión: {dimension}\nIndicador: {metrica}\nTotal de filas consultadas: {len(consulta)}\nSuma: {total}\nCuadro comparativo:\n{resumen}"
        try:
            groq = Groq(api_key=st.secrets["GROQ_API_KEY"])
            respuesta = groq.chat.completions.create(
                model=st.secrets.get("GROQ_MODEL", "openai/gpt-oss-20b"),
                messages=[{"role":"system","content":instrucciones},{"role":"user","content":contexto}],
                temperature=0.1,
            ).choices[0].message.content or "No se obtuvo respuesta del modelo."
        except Exception as exc:
            respuesta = ("No se pudo consultar Groq. Puedes revisar igualmente el cuadro calculado. "
                         "Comprueba tu clave, modelo y conexión.\n\n" + f"`{type(exc).__name__}: {str(exc)[:260]}`")
        if tabla.empty:
            respuesta = "No se encontraron registros que coincidan con esa consulta y los filtros seleccionados."
        st.session_state.historial_flujo.append({
            "id":len(st.session_state.historial_flujo), "pregunta":pregunta,
            "respuesta":respuesta, "tabla":tabla if not tabla.empty else None,
            "dimension":dimension, "metrica":metrica,
            "horizontal":dimension in ["DEPARTAMENTO", "NOMBRE_PEAJE"]
        })
        st.rerun()
    st.caption("Nota: las preguntas abiertas se interpretan mediante reglas sencillas; para análisis complejos se pueden añadir controles y consultas específicas.")


elif seccion == "📧 Agente 2 · Correos":
    st.subheader("📧 Agente 2 — Envío de informes")
    st.caption("Envía reportes ahora o deja un envío programado. Los informes programados son una instantánea de los datos filtrados al crearlos.")
    if "EMAIL_ADMIN_PASSWORD" not in st.secrets:
        st.error("Configura EMAIL_ADMIN_PASSWORD en Secrets antes de habilitar el agente de correo.")
        st.stop()
    clave_introducida = st.text_input("Contraseña de administración del Agente 2", type="password")
    if not hmac.compare_digest(clave_introducida, str(st.secrets["EMAIL_ADMIN_PASSWORD"])) or not clave_introducida:
        st.info("Ingresa la contraseña administrativa para ver y usar el agente de correos.")
        st.stop()
    st.success("Acceso autorizado al Agente 2")
    destinatario = st.text_input("Correo destinatario", placeholder="persona@gmail.com").strip()
    asunto = st.text_input("Asunto", "Informe de flujo vehicular del Perú")
    cuerpo_sugerido, csv_reporte = generar_informe(filtrado)
    contenido = st.text_area("Vista previa del informe", value=cuerpo_sugerido, height=290)
    adjuntar = st.checkbox("Adjuntar cuadro comparativo CSV", value=True)
    modo = st.radio("Tipo de envío", ["Enviar ahora", "Programar para después", "Envío recurrente"], horizontal=True)
    tz_lima = ZoneInfo("America/Lima")
    ahora_lima = datetime.now(tz_lima)
    fecha = None
    hora = None
    frecuencia = "una_vez"
    if modo != "Enviar ahora":
        col_f, col_h = st.columns(2)
        with col_f:
            fecha = st.date_input("Fecha del primer envío (Perú)", value=ahora_lima.date() + timedelta(days=1), min_value=ahora_lima.date())
        with col_h:
            hora = st.time_input("Hora del envío (Perú)", value=datetime.strptime("09:00", "%H:%M").time())
        if modo == "Envío recurrente":
            frecuencia = st.selectbox("Frecuencia", ["diaria", "semanal", "mensual"])
        st.caption("Los envíos programados se procesan mediante GitHub Actions, aproximadamente cada 5 minutos; no garantizan exactitud al minuto.")
    if st.button("📨 Enviar correo" if modo == "Enviar ahora" else "🗓️ Guardar programación", type="primary"):
        if not email_valido(destinatario):
            st.error("Escribe una sola dirección de correo válida.")
        elif not asunto.strip() or not contenido.strip():
            st.error("El asunto y el contenido no pueden estar vacíos.")
        elif modo == "Enviar ahora":
            try:
                enviar_correo(destinatario, asunto, contenido, csv_reporte if adjuntar else None)
                st.success("Correo enviado. Revisa también la bandeja de spam del destinatario.")
            except Exception as exc:
                st.error(f"No se pudo enviar: {type(exc).__name__}: {exc}")
        else:
            fecha_local = datetime.combine(fecha, hora, tzinfo=tz_lima)
            if fecha_local <= ahora_lima:
                st.error("Selecciona una fecha y hora futuras.")
            elif "SUPABASE_SERVICE_ROLE_KEY" not in st.secrets:
                st.error("Para programar envíos, configura SUPABASE_SERVICE_ROLE_KEY en los Secrets de Streamlit y crea la tabla email_jobs.sql.")
            else:
                try:
                    payload = {
                        "recipient": destinatario,
                        "subject": asunto.strip(),
                        "body": contenido,
                        "csv_content": csv_reporte.decode("utf-8-sig") if adjuntar else None,
                        "scheduled_at": fecha_local.astimezone(timezone.utc).isoformat(),
                        "frequency": frecuencia,
                        "status": "pending",
                    }
                    cliente_correos().table("email_jobs").insert(payload).execute()
                    st.success("Programación guardada. Se enviará cuando el programador externo esté activo.")
                except Exception as exc:
                    st.error(f"No se pudo programar: {type(exc).__name__}: {exc}")
    st.divider()
    st.subheader("📋 Envíos programados")
    if "SUPABASE_SERVICE_ROLE_KEY" not in st.secrets:
        st.info("Agrega SUPABASE_SERVICE_ROLE_KEY para consultar y cancelar programaciones.")
    else:
        try:
            trabajos = cliente_correos().table("email_jobs").select("id,recipient,subject,scheduled_at,frequency,status,sent_count,last_sent_at,last_error").order("scheduled_at", desc=True).limit(50).execute().data or []
            st.dataframe(pd.DataFrame(trabajos), use_container_width=True, hide_index=True)
            pendientes = [j for j in trabajos if j["status"] == "pending"]
            if pendientes:
                opciones = {f'{j["recipient"]} | {j["scheduled_at"]} | {j["id"]}': j["id"] for j in pendientes}
                cancelar = st.selectbox("Cancelar programación pendiente", list(opciones))
                if st.button("Cancelar programación seleccionada"):
                    cliente_correos().table("email_jobs").update({"status": "cancelled"}).eq("id", opciones[cancelar]).eq("status", "pending").execute()
                    st.success("Solicitud de cancelación guardada. Si el envío ya está siendo procesado, podría completarse.")
                    st.rerun()
        except Exception as exc:
            st.warning(f"No se pudo leer el historial: {type(exc).__name__}: {exc}")

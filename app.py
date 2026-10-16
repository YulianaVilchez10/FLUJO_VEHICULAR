
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

    st.subheader("📋 Historial y gestión de programaciones")

    if "SUPABASE_SERVICE_ROLE_KEY" not in st.secrets:

        st.info("Agrega SUPABASE_SERVICE_ROLE_KEY para consultar y cancelar programaciones.")

    else:

        try:

            trabajos = cliente_correos().table("email_jobs").select("id,recipient,subject,scheduled_at,frequency,status,sent_count,last_sent_at,last_error").order("scheduled_at", desc=True).limit(50).execute().data or []

            historial = pd.DataFrame(trabajos)
            if not historial.empty:
                historial = historial.rename(columns={"recipient":"Destinatario","subject":"Asunto","scheduled_at":"Próximo envío (UTC)","frequency":"Frecuencia","status":"Estado","sent_count":"Enviados","last_sent_at":"Último envío (UTC)","last_error":"Último error"})
            st.dataframe(historial, use_container_width=True, hide_index=True)

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

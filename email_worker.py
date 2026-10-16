"""Worker de envíos programados. Ejecutar con GitHub Actions cada 5 minutos."""
import os
import base64
import smtplib
import calendar
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from supabase import create_client


def proxima_fecha(iso, frecuencia):
    fecha = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if frecuencia == 'diaria':
        return fecha + timedelta(days=1)
    if frecuencia == 'semanal':
        return fecha + timedelta(days=7)
    if frecuencia == 'mensual':
        mes = fecha.month + 1
        anio = fecha.year
        if mes == 13:
            mes, anio = 1, anio + 1
        return fecha.replace(year=anio, month=mes, day=min(fecha.day, calendar.monthrange(anio, mes)[1]))
    return None


def main():
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
    ahora = datetime.now(timezone.utc).isoformat()
    jobs = (db.table('email_jobs').select('*').eq('status', 'pending')
            .lte('scheduled_at', ahora).order('scheduled_at').limit(30).execute().data or [])
    for job in jobs:
        # Se comprueba el estado antes de enviar; no ejecutar dos workers simultáneos.
        check = db.table('email_jobs').select('status').eq('id', job['id']).single().execute().data
        if not check or check['status'] != 'pending':
            continue
        db.table('email_jobs').update({'status': 'sending'}).eq('id', job['id']).eq('status', 'pending').execute()
        try:
            msg = EmailMessage()
            msg['From'] = os.environ['GMAIL_USER']
            msg['To'] = job['recipient']
            msg['Subject'] = job['subject']
            msg.set_content(job['body'])
            if job.get('csv_content'):
                adjunto = job['csv_content']
                if adjunto.startswith('PDF_BASE64:'):
                    msg.add_attachment(base64.b64decode(adjunto[len('PDF_BASE64:'):]), maintype='application', subtype='pdf', filename='informe_agente_ia.pdf')
                else:
                    msg.add_attachment(adjunto.encode('utf-8-sig'), maintype='text', subtype='csv', filename='reporte_flujo_vehicular.csv')
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
                smtp.login(os.environ['GMAIL_USER'], os.environ['GMAIL_APP_PASSWORD'].replace(' ', ''))
                smtp.send_message(msg)
            proxima = proxima_fecha(job['scheduled_at'], job['frequency'])
            update = {'status': 'pending' if proxima else 'sent',
                      'sent_count': int(job.get('sent_count') or 0) + 1,
                      'last_sent_at': datetime.now(timezone.utc).isoformat(), 'last_error': None}
            if proxima:
                # Saltar ocurrencias vencidas, sin enviar correos acumulados.
                while proxima <= datetime.now(timezone.utc):
                    proxima = proxima_fecha(proxima.isoformat(), job['frequency'])
                update['scheduled_at'] = proxima.isoformat()
            db.table('email_jobs').update(update).eq('id', job['id']).execute()
            print('Enviado:', job['id'])
        except Exception as exc:
            # No reintento automático para evitar duplicados si Gmail aceptó el correo.
            db.table('email_jobs').update({'status': 'failed', 'last_error': str(exc)[:500]}).eq('id', job['id']).execute()
            print('Error:', job['id'], type(exc).__name__)


if __name__ == '__main__':
    main()

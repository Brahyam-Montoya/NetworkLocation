# NetworkLocation

Aplicacion Flask para cargar un CSV, autenticar usuarios con Microsoft Entra, ejecutar la automatizacion de Netskope y conservar el historial operativo.

## Stack

- `Python 3.13+` para la web Flask
- `Node.js 20+` para la automatizacion Playwright de Netskope

## Ejecutar

1. Completa `.env`
2. Instala dependencias de Python si hacen falta:

```powershell
python -m pip install -r requirements.txt
```

3. Instala dependencias Node si hace falta:

```powershell
npm.cmd install
```

4. Inicia la app:

```powershell
python app.py
```

La app quedara por defecto en `http://localhost:5000`.

## Acceso

- Microsoft Entra usa `APP_BASE_URL` y `AZURE_REDIRECT_URI`; si cambias el host o puerto, ambos deben coincidir con la URI registrada en Entra.
- El acceso local permite escribir alias o correo corporativo.
- `LOCAL_LOGIN_ALIASES` sirve para mapear alias como `brahyam` al correo real que recibira el OTP.

## Variables importantes

- `APP_BASE_URL`
- `SECRET_KEY`
- `AZURE_TENANT_ID`
- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`
- `AZURE_REDIRECT_URI`
- `NETSKOPE_BASE_URL`
- `NETSKOPE_USER`
- `NETSKOPE_PASSWORD`
- `DEFAULT_ADMIN_USERS`
- `DEFAULT_READ_ONLY_USERS`
- `LOCAL_LOGIN_ALIASES`
- `SMTP_HOST`
- `SMTP_FROM`

## Persistencia

- `uploads/` archivos CSV cargados
- `logs/execution_logs.json` historial de ejecuciones
- `logs/user_roles.json` roles persistidos
- `logs/evidence/` screenshots y logs tecnicos del runner Playwright

## Cloudflare

La app queda preparada para mover `APP_BASE_URL` y `AZURE_REDIRECT_URI` a un dominio publico como `https://networklocation.gammalab14.online` cuando se configure el tunnel y el DNS.

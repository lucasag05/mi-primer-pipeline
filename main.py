# ─────────────────────────────────────────────
# IMPORTACIONES
# ─────────────────────────────────────────────

# 'requests' nos permite hacer llamadas HTTP a APIs externas (como CoinGecko)
import requests

# 'psycopg2' es el driver que Python usa para conectarse a PostgreSQL
import psycopg2

# 'sql' sirve para construir queries de forma segura (evita SQL injection)
# 'OperationalError' es la excepción que lanza psycopg2 cuando no puede conectarse a la DB
from psycopg2 import sql, OperationalError

# Para registrar la fecha y hora exacta en que se guardó cada precio
from datetime import datetime, timezone

# 'os' nos permite leer variables del sistema operativo (como las del archivo .env)
import os

# 'load_dotenv' carga las variables del archivo .env al entorno del proceso
from dotenv import load_dotenv


# ─────────────────────────────────────────────
# CONFIGURACIÓN: VARIABLES DE ENTORNO
# ─────────────────────────────────────────────

# Construimos la ruta absoluta al archivo .env que está en la misma carpeta que este script
# Esto evita problemas si el script se ejecuta desde otra carpeta (por ejemplo, con cron)
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')

# Cargamos el archivo .env para que sus variables estén disponibles con os.getenv()
load_dotenv(dotenv_path=dotenv_path)

# Línea de debug: útil para verificar que el .env se cargó correctamente durante el desarrollo
# Podés eliminar esta línea cuando el proyecto esté listo para producción
print(f"DEBUG: Usuario detectado -> {os.getenv('DB_USER')}")


# ─────────────────────────────────────────────
# CONFIGURACIÓN: BASE DE DATOS
# ─────────────────────────────────────────────

# Diccionario con los datos de conexión a PostgreSQL
# Los valores vienen del archivo .env — nunca se hardcodean en el código por seguridad
DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),     # IP o nombre del servidor de base de datos
    "port":     os.getenv("DB_PORT"),     # Puerto (por defecto PostgreSQL usa 5432)
    "dbname":   os.getenv("DB_NAME"),     # Nombre de la base de datos
    "user":     os.getenv("DB_USER"),     # Usuario de PostgreSQL
    "password": os.getenv("DB_PASS"),     # Contraseña del usuario
}


# ─────────────────────────────────────────────
# CONFIGURACIÓN: API
# ─────────────────────────────────────────────

# URL del endpoint de CoinGecko que devuelve el precio de Bitcoin en USD
# ids=bitcoin → qué criptomoneda consultar
# vs_currencies=usd → en qué moneda queremos el precio
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies=usd"
)


# ─────────────────────────────────────────────
# FUNCIÓN 1: Obtener el precio desde la API
# ─────────────────────────────────────────────

def get_bitcoin_price() -> None:
    """Consulta la API de CoinGecko, obtiene el precio de Bitcoin en USD y lo guarda en la DB."""
    try:
        # Hacemos la petición GET a la API con un límite de 10 segundos para no quedarnos esperando
        response = requests.get(COINGECKO_URL, timeout=10)

        # Si el servidor devuelve un error (ej: 404, 500), esta línea lanza una excepción automáticamente
        response.raise_for_status()

        # Convertimos la respuesta de texto JSON a un diccionario de Python
        # Ejemplo de lo que devuelve: {"bitcoin": {"usd": 79500.0}}
        data = response.json()

        # Verificamos que la respuesta tenga la estructura que esperamos
        # Si la API cambia su formato, esta validación nos avisa en lugar de romper silenciosamente
        if "bitcoin" not in data or "usd" not in data["bitcoin"]:
            print("❌ Error: La respuesta de la API no tiene el formato esperado.")
            return

        # Extraemos el precio del diccionario anidado
        price = data["bitcoin"]["usd"]

        # Mostramos el precio en consola con formato de 2 decimales y separador de miles
        print("\n✅ Conexión exitosa con la API")
        print(f"💰 El precio actual de Bitcoin es: ${price:,.2f} USD\n")

        # Llamamos a la función que guarda el precio en la base de datos
        guardar_en_db(price)

    # Error de red: no hay internet o el servidor no responde
    except requests.exceptions.ConnectionError:
        print("❌ Error de red: No se pudo conectar con la API. Verifica tu conexión.")

    # La API tardó más de 10 segundos en responder
    except requests.exceptions.Timeout:
        print("❌ Error: La solicitud tardó demasiado (timeout de 10 segundos).")

    # La API respondió con un código de error HTTP (ej: 429 Too Many Requests, 500 Server Error)
    except requests.exceptions.HTTPError as e:
        print(f"❌ Error HTTP {e.response.status_code}: {e}")

    # Cualquier otro error relacionado con la librería requests
    except requests.exceptions.RequestException as e:
        print(f"❌ Error inesperado con la solicitud: {e}")

    # Error al leer el JSON (ej: la API devolvió HTML en vez de JSON, o falta una clave)
    except (KeyError, ValueError) as e:
        print(f"❌ Error al procesar la respuesta JSON: {e}")


# ─────────────────────────────────────────────
# FUNCIÓN 2: Guardar el precio en PostgreSQL
# ─────────────────────────────────────────────

def guardar_en_db(price: float) -> None:
    """Recibe el precio de Bitcoin y lo inserta en la tabla 'bitcoin_prices' de PostgreSQL."""

    # Inicializamos en None para poder verificar en el bloque 'finally' si se abrieron
    # Si no hacemos esto y falla el connect(), el finally lanzaría otro error al intentar cerrar
    conn = None
    cursor = None

    try:
        # Abrimos la conexión a PostgreSQL usando los datos del diccionario DB_CONFIG
        conn = psycopg2.connect(**DB_CONFIG)

        # El cursor es el objeto que usamos para ejecutar comandos SQL
        cursor = conn.cursor()

        # Creamos la tabla si todavía no existe en la base de datos
        # SERIAL → número autoincremental (1, 2, 3...)
        # NUMERIC(18, 2) → número con hasta 18 dígitos y 2 decimales (ideal para dinero)
        # TIMESTAMPTZ → fecha y hora con zona horaria incluida
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bitcoin_prices (
                id        SERIAL PRIMARY KEY,
                precio    NUMERIC(18, 2) NOT NULL,
                moneda    VARCHAR(10)    NOT NULL DEFAULT 'USD',
                timestamp TIMESTAMPTZ    NOT NULL
            );
        """)

        # Insertamos una nueva fila con el precio, la moneda y la hora actual en UTC
        # Usamos sql.SQL con %s para pasar los valores de forma segura (evita SQL injection)
        # datetime.now(timezone.utc) → hora exacta del momento, en UTC (sin depender del huso del servidor)
        cursor.execute(
            sql.SQL(
                "INSERT INTO bitcoin_prices (precio, moneda, timestamp) VALUES (%s, %s, %s)"
            ),
            (price, "USD", datetime.now(timezone.utc))
        )

        # Confirmamos la transacción: sin esto, el INSERT no se guarda permanentemente
        conn.commit()
        print(f"💾 Precio guardado en la base de datos correctamente.")

    # No se pudo conectar a la DB (credenciales incorrectas, servidor apagado, etc.)
    except OperationalError as e:
        print(f"❌ Error al conectar con la base de datos: {e}")

    # Se conectó, pero falló alguna operación SQL (ej: tipo de dato incorrecto, tabla no existe)
    except psycopg2.DatabaseError as e:
        print(f"❌ Error al ejecutar la consulta SQL: {e}")
        # Revertimos cualquier cambio parcial para no dejar la DB en un estado inconsistente
        if conn:
            conn.rollback()

    finally:
        # Este bloque se ejecuta SIEMPRE, haya error o no
        # Es importante cerrar cursor y conexión para liberar recursos del servidor
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ─────────────────────────────────────────────
# PUNTO DE ENTRADA DEL SCRIPT
# ─────────────────────────────────────────────

# Esta condición hace que get_bitcoin_price() solo se ejecute cuando corremos
# este archivo directamente (ej: python main.py)
# Si otro archivo importa este módulo, la función NO se ejecuta automáticamente
if __name__ == "__main__":
    get_bitcoin_price()
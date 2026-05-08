import os
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# Cargamos las variables del .env
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     os.getenv("DB_PORT"),
    "dbname":   os.getenv("DB_NAME"),
    "user":     os.getenv("DB_USER"),
    "password": os.getenv("DB_PASS"),
}

app = Flask(__name__, static_folder='.')
CORS(app)  # Permite que el HTML abierto como file:// también pueda consultar este servidor


# ── Endpoint: historial completo de precios ──────────────────
@app.route('/api/prices')
def get_prices():
    """Devuelve todos los precios de la tabla bitcoin_prices ordenados por fecha."""
    conn   = None
    cursor = None
    try:
        conn   = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT
                id,
                CAST(precio AS FLOAT) AS precio,
                moneda,
                timestamp AT TIME ZONE 'UTC' AS timestamp
            FROM bitcoin_prices
            ORDER BY timestamp ASC;
        """)

        rows = cursor.fetchall()

        # Convertimos los timestamps a strings ISO 8601 para que JSON los pueda serializar
        result = []
        for row in rows:
            result.append({
                "id":        row["id"],
                "precio":    row["precio"],
                "moneda":    row["moneda"],
                "timestamp": row["timestamp"].isoformat() + "Z",
            })

        return jsonify(result)

    except psycopg2.OperationalError as e:
        return jsonify({"error": f"No se pudo conectar a la base de datos: {e}"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ── Sirve el index.html ───────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    print("\n🚀 Servidor corriendo en http://localhost:5001")
    print("   Abrí esa URL en el navegador para ver el dashboard.\n")
    app.run(host='0.0.0.0', port=5001, debug=False)

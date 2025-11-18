from flask import Flask, request, jsonify
from flask_cors import CORS
import gspread
from google.oauth2.service_account import Credentials
import random
import os
import json

app = Flask(__name__)
CORS(app)

# Configuración de Google Sheets
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

def get_google_sheet():
    """Conecta con Google Sheets usando credenciales"""
    try:
        # Las credenciales deben estar en una variable de entorno como JSON string
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if not creds_json:
            raise ValueError("GOOGLE_CREDENTIALS no configurado")
        
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        # ID del documento de Google Sheets (desde variable de entorno)
        sheet_id = os.environ.get('SHEET_ID')
        if not sheet_id:
            raise ValueError("SHEET_ID no configurado")
        
        sheet = client.open_by_key(sheet_id).sheet1
        return sheet
    except Exception as e:
        print(f"Error conectando con Google Sheets: {str(e)}")
        raise

def parse_question_row(row, row_index):
    """Parsea una fila del sheet a formato de pregunta"""
    if len(row) < 7:  # Necesitamos al menos columnas A-G
        return None
    
    # Columna A: ID (si está vacía, usar índice de fila)
    question_id = row[0] if row[0] else f"pregunta_{row_index}"
    
    # Columna B: Pregunta
    question_text = row[1] if len(row) > 1 else ""
    if not question_text:
        return None
    
    # Columnas C, D, E, F: Opciones
    opciones_originales = [
        {"codigo": "A", "texto": row[2] if len(row) > 2 else ""},
        {"codigo": "B", "texto": row[3] if len(row) > 3 else ""},
        {"codigo": "C", "texto": row[4] if len(row) > 4 else ""},
        {"codigo": "D", "texto": row[5] if len(row) > 5 else ""}
    ]
    
    # Filtrar opciones vacías
    opciones_originales = [op for op in opciones_originales if op["texto"]]
    
    if len(opciones_originales) < 2:  # Al menos 2 opciones
        return None
    
    # Columna G: Respuesta correcta
    respuesta_correcta = row[6] if len(row) > 6 else ""
    
    return {
        "id": question_id,
        "pregunta": question_text,
        "opciones": opciones_originales,
        "respuesta_correcta": respuesta_correcta.strip().upper()
    }

@app.route('/')
def home():
    return jsonify({
        "mensaje": "API de Preguntas v1.0",
        "endpoints": {
            "obtener_preguntas": "POST /api/get-questions",
            "validar_respuestas": "POST /api/validate-answers",
            "diagnostico": "GET /api/test-connection"
        }
    })

@app.route('/api/test-connection', methods=['GET'])
def test_connection():
    """Endpoint de diagnóstico para probar la conexión con Google Sheets"""
    diagnostico = {
        "google_credentials_configurado": False,
        "sheet_id_configurado": False,
        "conexion_exitosa": False,
        "filas_encontradas": 0,
        "error": None
    }
    
    try:
        # Verificar variables de entorno
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        sheet_id = os.environ.get('SHEET_ID')
        
        diagnostico["google_credentials_configurado"] = bool(creds_json)
        diagnostico["sheet_id_configurado"] = bool(sheet_id)
        
        if not creds_json:
            diagnostico["error"] = "GOOGLE_CREDENTIALS no está configurado en las variables de entorno"
            return jsonify(diagnostico), 500
        
        if not sheet_id:
            diagnostico["error"] = "SHEET_ID no está configurado en las variables de entorno"
            return jsonify(diagnostico), 500
        
        # Intentar conectar
        print("Intentando conectar con Google Sheets...")
        sheet = get_google_sheet()
        print("Conexión exitosa!")
        
        # Obtener datos
        all_rows = sheet.get_all_values()
        diagnostico["conexion_exitosa"] = True
        diagnostico["filas_encontradas"] = len(all_rows)
        
        # Mostrar muestra de las primeras 3 filas (sin datos sensibles)
        if len(all_rows) > 0:
            diagnostico["muestra_estructura"] = {
                "fila_1_columnas": len(all_rows[0]),
                "tiene_encabezados": bool(all_rows[0]),
                "filas_con_datos": len([r for r in all_rows if any(r)])
            }
        
        return jsonify(diagnostico), 200
        
    except json.JSONDecodeError as je:
        diagnostico["error"] = f"GOOGLE_CREDENTIALS no es un JSON válido: {str(je)}"
        return jsonify(diagnostico), 500
    except Exception as e:
        diagnostico["error"] = f"{type(e).__name__}: {str(e)}"
        import traceback
        print(traceback.format_exc())
        return jsonify(diagnostico), 500

@app.route('/api/get-questions', methods=['POST'])
def get_questions():
    """Endpoint para obtener preguntas aleatorias"""
    try:
        data = request.get_json()
        cantidad = data.get('cantidad', 5)
        
        if not isinstance(cantidad, int) or cantidad <= 0:
            return jsonify({"error": "La cantidad debe ser un número entero positivo"}), 400
        
        # Obtener datos del sheet
        print("Intentando conectar con Google Sheets...")
        sheet = get_google_sheet()
        print("Conexión exitosa, obteniendo datos...")
        all_rows = sheet.get_all_values()
        print(f"Se obtuvieron {len(all_rows)} filas del documento")
        
        # Parsear preguntas (saltando encabezado si existe)
        preguntas = []
        for idx, row in enumerate(all_rows[1:], start=2):  # Empezar desde fila 2
            question = parse_question_row(row, idx)
            if question:
                preguntas.append(question)
        
        print(f"Se parsearon {len(preguntas)} preguntas válidas")
        
        if not preguntas:
            return jsonify({
                "error": "No se encontraron preguntas válidas en el documento",
                "filas_totales": len(all_rows),
                "ayuda": "Verifica que tu Sheet tenga datos en las columnas B (pregunta), C-F (opciones) y G (respuesta correcta)"
            }), 404
        
        # Seleccionar preguntas aleatorias
        cantidad_disponible = min(cantidad, len(preguntas))
        preguntas_seleccionadas = random.sample(preguntas, cantidad_disponible)
        
        # Mezclar opciones de cada pregunta
        resultado = []
        for pregunta in preguntas_seleccionadas:
            opciones_mezcladas = random.sample(pregunta["opciones"], len(pregunta["opciones"]))
            resultado.append({
                "id": pregunta["id"],
                "pregunta": pregunta["pregunta"],
                "opciones": opciones_mezcladas
            })
        
        return jsonify({"preguntas": resultado}), 200
    
    except ValueError as ve:
        print(f"Error de configuración: {str(ve)}")
        return jsonify({
            "error": "Error de configuración",
            "detalle": str(ve),
            "ayuda": "Verifica que GOOGLE_CREDENTIALS y SHEET_ID estén configurados en las variables de entorno"
        }), 500
    except Exception as e:
        print(f"Error inesperado: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Error al obtener preguntas",
            "detalle": str(e),
            "tipo": type(e).__name__
        }), 500

@app.route('/api/validate-answers', methods=['POST'])
def validate_answers():
    """Endpoint para validar respuestas"""
    try:
        data = request.get_json()
        respuestas_usuario = data.get('respuestas', [])
        
        if not respuestas_usuario:
            return jsonify({"error": "No se enviaron respuestas"}), 400
        
        # Obtener datos del sheet
        print("Intentando conectar con Google Sheets para validar...")
        sheet = get_google_sheet()
        print("Conexión exitosa, obteniendo datos...")
        all_rows = sheet.get_all_values()
        
        # Crear diccionario de preguntas con respuestas correctas
        preguntas_dict = {}
        for idx, row in enumerate(all_rows[1:], start=2):
            question = parse_question_row(row, idx)
            if question:
                preguntas_dict[question["id"]] = question
        
        print(f"Se cargaron {len(preguntas_dict)} preguntas para validación")
        
        # Validar respuestas
        resultados = []
        puntaje_total = 0
        correctas = 0
        incorrectas = 0
        
        for respuesta in respuestas_usuario:
            question_id = respuesta.get('id')
            respuesta_enviada = respuesta.get('respuesta', '').strip().upper()
            
            if question_id not in preguntas_dict:
                resultados.append({
                    "id": question_id,
                    "error": "Pregunta no encontrada",
                    "puntaje": 0
                })
                incorrectas += 1
                continue
            
            respuesta_correcta = preguntas_dict[question_id]["respuesta_correcta"]
            es_correcta = respuesta_enviada == respuesta_correcta
            puntaje = 1 if es_correcta else 0
            
            resultados.append({
                "id": question_id,
                "correcta": es_correcta,
                "respuesta_enviada": respuesta_enviada,
                "respuesta_correcta": respuesta_correcta,
                "puntaje": puntaje
            })
            
            puntaje_total += puntaje
            if es_correcta:
                correctas += 1
            else:
                incorrectas += 1
        
        return jsonify({
            "resultados": resultados,
            "puntaje_total": puntaje_total,
            "total_preguntas": len(respuestas_usuario),
            "correctas": correctas,
            "incorrectas": incorrectas
        }), 200
    
    except ValueError as ve:
        print(f"Error de configuración: {str(ve)}")
        return jsonify({
            "error": "Error de configuración",
            "detalle": str(ve),
            "ayuda": "Verifica que GOOGLE_CREDENTIALS y SHEET_ID estén configurados en las variables de entorno"
        }), 500
    except Exception as e:
        print(f"Error inesperado al validar: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Error al validar respuestas",
            "detalle": str(e),
            "tipo": type(e).__name__
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

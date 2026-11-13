# Tablero · Control de calidad por línea de producción (Hito 2)

Tablero en Streamlit del sistema integrado del Hito 2 (IA Generativa para la gestión industrial).
Equipo: Felipe Alonso, Sofia Fariña, Vicente Lagunas.

## Qué muestra
1. **Indicadores por línea:** tasa de defectos, promedio móvil, meta, límite de control y estado.
2. **Modelos en el tiempo:** series de tiempo (promedio móvil, Holt, GRU, LSTM), imágenes (ResNet18, MobileNetV2 y alternativa simple) y búsqueda en el manual (embeddings frente a TF-IDF).
3. **Recomendaciones del LLM:** registro de cada ejecución del flujo de n8n, con la decisión humana y las citas del manual.

## Datos y avisos
- Las series de defectos y el manual de acciones correctivas son **simulados**.
- Las métricas de imágenes provienen de un modelo entrenado con *Casting product image data* (Kaggle, licencia CC BY-NC-ND 4.0, uso académico). **Este repositorio no contiene imágenes.**
- El registro de recomendaciones se lee desde una pestaña de Google Sheets publicada como CSV.

## Ejecutar en local
```
pip install -r requirements.txt
streamlit run app.py
```
Para ver la pestaña de recomendaciones, define el enlace CSV del registro en `.streamlit/secrets.toml`:
```
registro_csv_url = "https://docs.google.com/spreadsheets/d/e/.../pub?gid=...&single=true&output=csv"
```
(en Streamlit Community Cloud se pega en *Settings → Secrets*). El archivo `secrets.toml` no se sube al repositorio.

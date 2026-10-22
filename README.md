# TrailWise – budget adventure itinerary agent
Run: `pip install -r requirements.txt && uvicorn server:app --port 8000` → open http://localhost:8000

- `data.py` fixture dataset (Rishikesh) · `tools.py` place/route/weather/price tools with source labels
- `planner.py` scheduler, budget engine, validators, repair loop · `llm.py` LLM parsing (schema-validated) + heuristic fallback
- `server.py` FastAPI + session memory · `static/index.html` UI
Demo: Generate → ① price spike → ② closure → ③ nature-focused → "Impossible budget" for honest infeasibility.

# P-HE Simulation Plant

A FastAPI-based simulation system for production planning and inventory management.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
uvicorn app.main:app --reload
```

3. Access the dashboard at: http://localhost:8000

## API Documentation

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Project Structure

- `app/models/` - Database models (Master, Planning, Supply, Simulation)
- `app/services/` - Business logic (Simulation, Inventory, Purchase Orders)
- `app/api/` - API endpoints
- `app/static/` - Frontend dashboard

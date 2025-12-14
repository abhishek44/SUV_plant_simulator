# app/main.py

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import create_db_and_tables
from .seed_data import seed_master_data
from .services.inventory import init_simulation_state
from .services.simulation import start_simulation
from .services.planning import plan_all_open_orders

from .api import simulation as sim_api
from .api import data as data_api
from .api import scenarios as scenarios_api
from .api import kpi as kpi_api
from .api import agent_tools as agent_api


app = FastAPI(title="P-HE / P-ME Simulation Plant")

# Include API routers
app.include_router(scenarios_api.router)
app.include_router(sim_api.router)
app.include_router(data_api.router)
app.include_router(kpi_api.router)
app.include_router(agent_api.router)  # Agent control & MCP tools

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
async def startup_event():
    create_db_and_tables()
    seed_master_data()
    plan_all_open_orders(horizon_days_default=9)
    init_simulation_state()
    start_simulation(background_tasks=None)
    
    # Setup MCP server (optional - if fastapi-mcp is installed)
    try:
        from .mcp_server import setup_mcp
        setup_mcp(app)
    except Exception as e:
        print(f"MCP server not started: {e}")


@app.get("/")
def root():
    return FileResponse("app/static/dashboard.html")


from fastapi import APIRouter, BackgroundTasks
from ..services.simulation import start_simulation, stop_simulation

router = APIRouter()


@router.post("/start_simulation")
def start_sim(background_tasks: BackgroundTasks):
    status = start_simulation(background_tasks)
    return {"status": status}


@router.post("/stop_simulation")
def stop_sim():
    status = stop_simulation()
    return {"status": status}

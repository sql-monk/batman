import uvicorn
from .config import CFG

if __name__ == "__main__":
    uvicorn.run("batman_service.main:app", host=CFG.server.host, port=CFG.server.port, log_level="info")

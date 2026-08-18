from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Code2MCP-esm",
        "transport": os.environ.get("MCP_TRANSPORT", "stdio"),
    }



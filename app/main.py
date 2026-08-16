from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="RAG Legal Assistant")
app.include_router(router)
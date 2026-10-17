from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import auth_router, threads, chat, documents

app = FastAPI(
    title="Agentic RAG Masterclass API",
    description="FastAPI + Supabase + Google Gemini + LangSmith",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(threads.router)
app.include_router(chat.router)
app.include_router(documents.router)


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "llm_model": settings.LLM_MODEL,
        "langsmith_tracing": settings.LANGSMITH_TRACING,
        "supabase_configured": bool(settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY),
    }

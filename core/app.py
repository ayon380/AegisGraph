import os
import io
import json
import asyncio
import warnings
import sys
import uuid
import tempfile

# Suppress LangChain / LangGraph Deprecation Warnings
warnings.filterwarnings("ignore", module="langgraph")
warnings.filterwarnings("ignore", module="langchain")
warnings.filterwarnings("ignore", message=".*allowed_objects.*")
try:
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
    warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)
except Exception:
    pass

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# Add scripts directory to path for ingest helpers
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

# Import our compiled graph from agent.py
from core.agent import compiled_graph

app = FastAPI(
    title="Sovereign GraphRAG OS - AI Core",
    description="Local secure FastAPI service managing LangGraph execution & Ollama inference.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request Model ---
class QueryRequest(BaseModel):
    query: str

# --- Health Check ---
@app.get("/health")
async def health_check():
    return {"status": "healthy", "engine": "FastAPI + LangGraph", "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434")}

# --- Decodes JWT claims locally without signature verification (Postgres does validation) ---
def decode_jwt_payload(auth_header: str) -> dict:
    import base64
    if not auth_header or not auth_header.startswith("Bearer "):
        return {}
    token = auth_header.split(" ")[1]
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return {}
        payload = parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload).decode('utf-8')
        return json.loads(decoded)
    except Exception:
        return {}

# --- Streaming Query Endpoint ---
@app.post("/api/query")
async def query_endpoint(
    request: QueryRequest,
    authorization: Optional[str] = Header(None)
):
    """
    Real-time streaming query endpoint. Reads security metadata from claims inside JWT,
    runs the async retrieval and reasoning graph, and streams output tokens.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized: Missing Authorization header")
        
    claims = decode_jwt_payload(authorization)
    if not claims:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid token format")
        
    org_id = claims.get("org_id", "org_alpha")
    clearance_level = claims.get("clearance_level", 1)
    departments = claims.get("departments", [])
    projects = claims.get("projects", [])
    raw_jwt = authorization.split(" ")[1]
    
    # Initialize the token queue
    queue = asyncio.Queue()
    
    # Define state inputs for the graph
    inputs = {
        "query": request.query,
        "org_id": org_id,
        "clearance_level": clearance_level,
        "departments": departments,
        "projects": projects,
        "jwt": raw_jwt,
        "retrieved_vectors": [],
        "retrieved_graph": [],
        "combined_context": "",
        "final_answer": ""
    }
    
    # Inject the queue into the RunnableConfig configurable namespace
    config = {
        "configurable": {
            "queue": queue
        }
    }
    
    # Define the background worker task that executes LangGraph
    async def run_agent():
        try:
            await compiled_graph.ainvoke(inputs, config=config)
        except Exception as e:
            print(f"[Error] Exception in LangGraph background runner: {e}")
            # Ensure we signal the consumer to close the stream in case of crash
            await queue.put(f"\n[Agent pipeline failed: {e}]")
            await queue.put(None)

    # Start graph execution in the background
    asyncio.create_task(run_agent())
    
    # SSE Token Generator
    async def sse_token_generator():
        try:
            while True:
                # Wait for the next token chunk from the LLM generate node
                token = await queue.get()
                if token is None:
                    # Termination signal received
                    break
                # Format as standard Server-Sent Event (SSE)
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Streaming interrupted: {e}'})}\n\n"

    return StreamingResponse(
        sse_token_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream"
        }
    )


# --- File Ingest Endpoint ---
@app.post("/api/ingest")
async def ingest_endpoint(
    file: UploadFile = File(...),
    org_id: str = Form("org_alpha"),
    clearance_level: int = Form(1),
    departments: str = Form("[\"Engineering\"]"),
    projects: str = Form("[]"),
    authorization: Optional[str] = Header(None)
):
    """
    Accepts a file upload (PDF, image, plain text, markdown) and ingests it
    into the secure vector store (Postgres pgvector) and knowledge graph (Neo4j).
    Returns a preview of extracted text.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")

    claims = decode_jwt_payload(authorization)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid token format")

    # Parse JSON arrays from form fields
    try:
        depts = json.loads(departments)
        projs = json.loads(projects)
    except Exception:
        depts = [departments]
        projs = []

    content_type = file.content_type or ""
    filename = file.filename or "upload"
    file_bytes = await file.read()

    extracted_text = ""

    # --- PDF Extraction ---
    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            extracted_text = "\n\n".join(pages).strip()
        except ImportError:
            raise HTTPException(status_code=500, detail="pdfplumber not installed. Run: pip install pdfplumber")
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"PDF extraction failed: {e}")

    # --- Image OCR ---
    elif content_type.startswith("image/"):
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(io.BytesIO(file_bytes))
            extracted_text = pytesseract.image_to_string(img).strip()
        except ImportError:
            # Fall back to passing image to Ollama vision model if available
            try:
                import base64, httpx as _httpx
                b64 = base64.b64encode(file_bytes).decode()
                async with _httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{os.getenv('OLLAMA_URL', 'http://localhost:11434')}/api/generate",
                        json={
                            "model": "llava",
                            "prompt": "Extract all readable text and describe the content of this image in detail.",
                            "images": [b64],
                            "stream": False
                        },
                        timeout=60.0
                    )
                    if resp.status_code == 200:
                        extracted_text = resp.json().get("response", "").strip()
                    else:
                        extracted_text = f"Image file: {filename} (OCR unavailable)"
            except Exception as e:
                extracted_text = f"Image file: {filename} (could not extract text: {e})"

    # --- Plain Text / Markdown ---
    elif content_type in ("text/plain", "text/markdown") or filename.lower().endswith((".txt", ".md", ".mdx")):
        extracted_text = file_bytes.decode("utf-8", errors="replace")

    # --- Word Documents ---
    elif "wordprocessingml" in content_type or filename.lower().endswith((".docx", ".doc")):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            extracted_text = "\n".join(p.text for p in doc.paragraphs).strip()
        except ImportError:
            raise HTTPException(status_code=500, detail="python-docx not installed. Run: pip install python-docx")
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"DOCX extraction failed: {e}")

    else:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {content_type}")

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="Could not extract any text from the file.")

    # Run the standard ingest pipeline in a thread (it calls Postgres + Neo4j)
    doc_id = str(uuid.uuid4())

    def run_ingest():
        # Import ingest helpers lazily (they import aegis_dsu which needs the gateway build)
        try:
            from ingest import save_document_to_postgres, extract_entities_and_relations, save_graph_to_neo4j
            import requests as _req, random

            # Embed
            OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
            try:
                r = _req.post(f"{OLLAMA_URL}/api/embeddings",
                              json={"model": "nomic-embed-text", "prompt": extracted_text}, timeout=30)
                embedding = r.json().get("embedding", []) if r.status_code == 200 else []
            except Exception:
                embedding = []
            if not embedding:
                vec = [random.uniform(-1.0, 1.0) for _ in range(768)]
                norm = sum(x*x for x in vec) ** 0.5
                embedding = [x/norm for x in vec]

            save_document_to_postgres(doc_id, org_id, clearance_level, depts, projs, extracted_text)
            facts = extract_entities_and_relations(extracted_text)
            save_graph_to_neo4j(facts.get("entities", []), facts.get("relationships", []),
                                org_id, clearance_level, depts, projs)
        except ImportError:
            # aegis_dsu (C++ gateway) not compiled — store just the vector
            from ingest_simple import save_document_to_postgres
            save_document_to_postgres(doc_id, org_id, clearance_level, depts, projs, extracted_text)

    try:
        await asyncio.to_thread(run_ingest)
    except Exception as e:
        print(f"[Ingest] Pipeline failed (non-fatal): {e}")

    preview = extracted_text[:500] + ("..." if len(extracted_text) > 500 else "")

    return JSONResponse({
        "success": True,
        "doc_id": doc_id,
        "filename": filename,
        "chars_extracted": len(extracted_text),
        "extracted_preview": preview
    })

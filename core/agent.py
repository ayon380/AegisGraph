import os
import asyncio
import json
from typing import TypedDict, List, Dict, Any, Optional
import psycopg2
from neo4j import AsyncGraphDatabase
import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END

# --- Database Configurations ---
PG_HOST = os.getenv("PGHOST", "localhost")
PG_PORT = os.getenv("PGPORT", "5432")
PG_USER = os.getenv("PGUSER", "myuser")
PG_PASSWORD = os.getenv("PGPASSWORD", "mypassword")
PG_DATABASE = os.getenv("PGDATABASE", "postgres")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "12345678")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = "nomic-embed-text"
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")

# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    query: str
    org_id: str
    clearance_level: int
    departments: List[str]
    projects: List[str]
    jwt: str

    # Router decision
    needs_search: bool
    search_query: str          # LLM-optimised query for the knowledge base

    # Retrieved data (only populated when LLM requests a search)
    retrieved_vectors: List[Dict[str, Any]]
    retrieved_graph: List[Dict[str, Any]]

    # Assembled tool context for the second LLM call
    # "" = search not requested, "ACCESS_DENIED" = no rows returned, otherwise content
    tool_context: str

    final_answer: str

# ---------------------------------------------------------------------------
# Ollama Helpers
# ---------------------------------------------------------------------------
async def async_get_embedding(text: str) -> List[float]:
    """Retrieves 768-dim embedding from Ollama, falls back to random vector."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBEDDING_MODEL, "prompt": text},
                timeout=60.0
            )
            if response.status_code == 200:
                emb = response.json().get("embedding", [])
                if emb:
                    return emb
    except Exception as e:
        print(f"[Warning] Embedding failed: {e}. Using fallback vector.")

    import random
    vec = [random.uniform(-1.0, 1.0) for _ in range(768)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


async def call_ollama(prompt: str, system: str, temperature: float = 0.1) -> str:
    """Single Ollama chat call, returns raw response string."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": LLM_MODEL,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                    "options": {"temperature": temperature}
                },
                timeout=90.0
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
    except Exception as e:
        print(f"[Warning] Ollama call failed: {e}")
    return ""

# ---------------------------------------------------------------------------
# Node 1: LLM Router
# The FIRST LLM call. Decides: respond directly OR use the search tool.
# ---------------------------------------------------------------------------
async def llm_router_node(state: AgentState) -> Dict[str, Any]:
    """
    Asks the LLM whether the query needs internal knowledge base search or
    can be answered from general knowledge. Sets needs_search and (if direct)
    final_answer. No DB access happens here.
    """
    query = (state.get("query") or "").strip()

    if not query:
        return {
            "needs_search": False,
            "search_query": "",
            "final_answer": "Please provide a non-empty query."
        }

    system_prompt = (
        "You are AegisGraph, a secure AI assistant for a company. "
        "You have access to a corporate knowledge base (internal documents, policies, "
        "salary data, project info, employee records, technical specs).\n\n"
        "Your job: decide how to handle the user message.\n\n"
        "Rules:\n"
        "  - Greetings, chitchat, general knowledge → answer directly.\n"
        "  - Anything needing internal company data → use the search tool.\n\n"
        "Respond with ONLY a raw JSON object (no markdown, no backticks):\n"
        '  Direct answer:  {"action": "direct", "answer": "<your response>"}\n'
        '  Search needed:  {"action": "search", "query": "<optimised search query>"}'
    )

    raw = await call_ollama(query, system_prompt, temperature=0.0)

    # Strip accidental markdown fences
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                raw = part
                break

    try:
        data = json.loads(raw)
        action = data.get("action", "")

        if action == "direct":
            answer = data.get("answer", "").strip()
            if answer:
                return {"needs_search": False, "search_query": "", "final_answer": answer}

        if action == "search":
            search_q = data.get("query", query).strip() or query
            return {"needs_search": True, "search_query": search_q, "final_answer": ""}

    except (json.JSONDecodeError, AttributeError):
        print(f"[Warning] Router JSON parse failed on: {raw!r}")

    # Fallback: attempt a search (safer for a corporate RAG system)
    return {"needs_search": True, "search_query": query, "final_answer": ""}


# ---------------------------------------------------------------------------
# Routing function: after llm_router decide which branch to take
# ---------------------------------------------------------------------------
def route_after_router(state: AgentState) -> str:
    if state.get("needs_search", False):
        return "tool_retrieve"
    return "signal_direct"


# ---------------------------------------------------------------------------
# Node 2a: Signal direct answer to SSE queue (no search path)
# ---------------------------------------------------------------------------
async def signal_direct_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Pushes the router's direct answer into the streaming queue."""
    queue = config.get("configurable", {}).get("queue")
    if queue:
        await queue.put(state.get("final_answer", ""))
        await queue.put(None)
    return {}


# ---------------------------------------------------------------------------
# Node 2b: Tool Retrieve (search path only)
# Runs vector similarity search + graph traversal ONLY when LLM requested it.
# ---------------------------------------------------------------------------
def sync_retrieve_vectors(
    query_embedding: List[float],
    user_context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """pgvector similarity search inside an RLS-secured transaction."""
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT,
        user="app_user", password="app_password",
        dbname=PG_DATABASE
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT set_secure_session(%s);", (user_context["jwt"],))
            cursor.execute("""
                SELECT content, clearance_level, departments, projects,
                       (embedding <=> %s::vector) AS distance
                FROM document_embeddings
                ORDER BY distance ASC
                LIMIT 5;
            """, (str(query_embedding),))
            rows = cursor.fetchall()
            seen = set()
            results = []
            for r in rows:
                content = r[0]
                if content not in seen:
                    seen.add(content)
                    results.append({
                        "content": content,
                        "clearance_level": r[1],
                        "departments": r[2],
                        "projects": r[3],
                        "distance": float(r[4])
                    })
            return results
    finally:
        conn.close()


async def async_traverse_graph(seed: str, state: AgentState) -> List[Dict[str, Any]]:
    """Native async Neo4j graph traversal with full security parameter binding."""
    cypher_query = """
        MATCH (s:Entity)
        WHERE (s.id = $seed OR s.name = $seed)
          AND s.org_id = $org_id
          AND s.clearance_level <= $clearance
          AND ANY(d IN s.departments WHERE d IN $user_depts)
          AND (size(s.projects) = 0 OR ANY(p IN s.projects WHERE p IN $user_projects))

        MATCH (s)-[r]->(t:Entity)
        WHERE r.clearance_level <= $clearance
          AND t.org_id = $org_id
          AND t.clearance_level <= $clearance
          AND ANY(d IN t.departments WHERE d IN $user_depts)
          AND (size(t.projects) = 0 OR ANY(p IN t.projects WHERE p IN $user_projects))

        RETURN s.name AS source, type(r) AS rel, t.name AS target, t.id AS target_id
        LIMIT 10;
    """
    results = []
    try:
        async with AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
            async with driver.session() as session:
                result = await session.run(
                    cypher_query,
                    {
                        "seed": seed,
                        "org_id": state["org_id"],
                        "clearance": state["clearance_level"],
                        "user_depts": state["departments"],
                        "user_projects": state["projects"]
                    }
                )
                async for record in result:
                    results.append({
                        "source": record["source"],
                        "relationship": record["rel"],
                        "target": record["target"],
                        "target_id": record["target_id"]
                    })
    except Exception as e:
        print(f"[Warning] Neo4j traversal failed: {e}")
    return results


async def tool_retrieve_node(state: AgentState) -> Dict[str, Any]:
    """
    Runs vector + graph retrieval ONLY because the LLM explicitly requested it.
    Assembles tool_context for the final generation node:
      - 'ACCESS_DENIED'  → nothing was returned (no rows / clearance too low)
      - '<content>'      → retrieved document chunks and graph relations
    """
    search_query = (state.get("search_query") or state.get("query") or "").strip()

    user_context = {
        "jwt": state["jwt"],
        "org_id": state["org_id"],
        "clearance": state["clearance_level"],
        "departments": state["departments"],
        "projects": state["projects"]
    }

    # --- Vector search ---
    query_emb = await async_get_embedding(search_query)
    try:
        vector_results = await asyncio.to_thread(
            sync_retrieve_vectors, query_emb, user_context
        )
    except Exception as e:
        print(f"[Warning] Vector retrieval failed: {e}")
        vector_results = []

    # --- Graph traversal (best-effort keyword seed) ---
    stopwords = {
        "what", "who", "is", "the", "of", "in", "to", "for", "with",
        "on", "a", "an", "and", "or", "about", "tell", "show", "give",
        "find", "get", "list", "me"
    }
    words = [w.strip("?,.!:;").lower() for w in search_query.split()]
    seed = next((w for w in words if w not in stopwords and len(w) > 3), "")

    graph_results = []
    if seed:
        graph_results = await async_traverse_graph(seed, state)

    # --- Assemble tool_context ---
    if not vector_results and not graph_results:
        # Nothing found — could be access restriction or genuinely absent data
        tool_context = "ACCESS_DENIED"
    else:
        parts = []
        if vector_results:
            doc_lines = []
            for i, doc in enumerate(vector_results):
                doc_lines.append(
                    f"[Document {i + 1}] Clearance: {doc['clearance_level']}, "
                    f"Departments: {doc['departments']}\n{doc['content']}"
                )
            parts.append("=== Retrieved Documents ===\n" + "\n\n".join(doc_lines))

        if graph_results:
            rel_lines = [
                f"({r['source']}) -[{r['relationship']}]-> ({r['target']})"
                for r in graph_results
            ]
            parts.append("=== Knowledge Graph Relations ===\n" + "\n".join(rel_lines))

        tool_context = "\n\n".join(parts)

    return {
        "retrieved_vectors": vector_results,
        "retrieved_graph": graph_results,
        "tool_context": tool_context
    }


# ---------------------------------------------------------------------------
# Node 3: Generate Answer (search path only)
# Second LLM call — uses the assembled tool_context.
# ---------------------------------------------------------------------------
async def generate_answer_node(state: AgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    Final LLM call after retrieval. Uses tool_context to answer the user.
    If ACCESS_DENIED, tells the LLM and lets it respond in its own natural language.
    """
    query = (state.get("query") or "").strip()
    tool_context = state.get("tool_context", "")

    if tool_context == "ACCESS_DENIED":
        system_prompt = (
            "You are AegisGraph, a secure AI assistant. "
            "You attempted to search the internal knowledge base but it returned no results. "
            "This means either the information is not in the knowledge base or the user's "
            "security clearance does not permit access to it. "
            "Be honest, polite, and helpful."
        )
        user_prompt = (
            f"User asked: {query}\n\n"
            "The knowledge base search returned no accessible records. "
            "Respond naturally to the user."
        )
    else:
        system_prompt = (
            "You are AegisGraph, a secure AI assistant. "
            "Answer the user's question using ONLY the context retrieved from the knowledge base. "
            "Be concise and factual. If the context only partially answers the question, say so clearly."
        )
        user_prompt = (
            f"Context from the secure knowledge base:\n\n{tool_context}\n\n"
            f"User question: {query}\n\nAnswer:"
        )

    response_text = await call_ollama(user_prompt, system_prompt, temperature=0.2)

    if not response_text:
        response_text = "I encountered an error generating a response. Please try again."

    queue = config.get("configurable", {}).get("queue")
    if queue:
        await queue.put(response_text)
        await queue.put(None)

    return {"final_answer": response_text}


# ---------------------------------------------------------------------------
# Graph Assembly & Compilation
# ---------------------------------------------------------------------------
workflow = StateGraph(AgentState)

workflow.add_node("llm_router",     llm_router_node)
workflow.add_node("signal_direct",  signal_direct_node)
workflow.add_node("tool_retrieve",  tool_retrieve_node)
workflow.add_node("generate_answer", generate_answer_node)

workflow.set_entry_point("llm_router")

# After router: branch to direct-answer or search tool
workflow.add_conditional_edges(
    "llm_router",
    route_after_router,
    {
        "signal_direct": "signal_direct",
        "tool_retrieve":  "tool_retrieve"
    }
)

workflow.add_edge("signal_direct",  END)
workflow.add_edge("tool_retrieve",  "generate_answer")
workflow.add_edge("generate_answer", END)

compiled_graph = workflow.compile()

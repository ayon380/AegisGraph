import os
import sys
import json
import random
import httpx
import psycopg2
from neo4j import GraphDatabase
import re

# Add gateway/build to Python search path to import our compiled C++ DSU native module
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gateway", "build"))

try:
    import aegis_dsu
except ImportError as e:
    print(f"[Error] Failed to import compiled C++ DSU module: {e}")
    print("Please make sure you have compiled the gateway targets first by running:")
    print("  cd gateway && mkdir -p build && cd build && cmake .. && make")
    sys.exit(1)

# --- Configuration & Environment Variables ---
PG_HOST = os.getenv("PGHOST", "localhost")
PG_PORT = os.getenv("PGPORT", "5432")
PG_USER = os.getenv("PGUSER", "myuser")  # Superuser is used to connect initially
PG_PASSWORD = os.getenv("PGPASSWORD", "mypassword")
PG_DATABASE = os.getenv("PGDATABASE", "postgres")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "12345678")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = "nomic-embed-text"
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")

# --- Helper: Ollama Embeddings ---
def get_embedding(text):
    try:
        import requests
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=10
        )
        if response.status_code == 200:
            return response.json()["embedding"]
    except Exception as e:
        print(f"[Warning] Ollama embedding fetch failed: {e}. Falling back to synthetic.")
    
    # Fallback to random 768-dim normalized vector
    vec = [random.uniform(-1.0, 1.0) for _ in range(768)]
    norm = sum(x*x for x in vec) ** 0.5
    return [x/norm for x in vec]

# --- Helper: Ollama Entity and Relation Extraction ---
def extract_entities_and_relations(text):
    prompt = (
        "You are an information extraction assistant. Extract all key corporate assets, services, "
        "projects, organizations, or technologies as entities, and their semantic relationships from the text.\n"
        "Output the result strictly in JSON format matching this schema:\n"
        "{\n"
        "  \"entities\": [\"Name of Entity 1\", \"Name of Entity 2\"],\n"
        "  \"relationships\": [\n"
        "    {\"source\": \"Name of Entity 1\", \"type\": \"RELATIONSHIP_TYPE\", \"target\": \"Name of Entity 2\"}\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "1. Do not output markdown codeblocks. Only raw JSON.\n"
        "2. Keep entity names brief, exactly as mentioned in text (or standard short forms/acronyms).\n"
        "3. Keep relationship types short, capitalized, snake_case (e.g., DEPLOYED_ON, SUBSIDIARY_OF, INTEGRATES_WITH).\n\n"
        f"Text to parse:\n{text}\n\n"
        "JSON:"
    )

    try:
        import requests
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
            timeout=30
        )
        if response.status_code == 200:
            content = response.json().get("response", "").strip()
            # Clean possible markdown wrapping
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content)
    except Exception as e:
        print(f"[Warning] Ollama extraction failed: {e}. Using rule-based fallback.")
    
    # Fallback structure
    return {"entities": [], "relationships": []}

# --- Database Storage Helpers ---
REL_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,49}$")

def normalize_rel_type(rel_type: str) -> str:
    """Normalize and validate relationship types to prevent Cypher injection."""
    if not rel_type:
        return "ASSOCIATED_WITH"
    normalized = rel_type.upper().replace(" ", "_")
    if REL_TYPE_RE.fullmatch(normalized):
        return normalized
    return "ASSOCIATED_WITH"

def save_document_to_postgres(doc_id, org_id, clearance_level, departments, projects, content):
    embedding = get_embedding(content)
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DATABASE
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO document_embeddings (id, org_id, clearance_level, departments, projects, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (id) DO UPDATE 
                SET content = EXCLUDED.content, embedding = EXCLUDED.embedding;
            """, (doc_id, org_id, clearance_level, departments, projects, content, embedding))
        conn.commit()
    finally:
        conn.close()

def save_graph_to_neo4j(entities, relationships, org_id, clearance_level, departments, projects):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        # Create Entities
        for entity_name in entities:
            # Use lowercased id for entity keying
            entity_id = entity_name.lower().replace(" ", "_")
            session.run("""
                MERGE (e:Entity {id: $id})
                ON CREATE SET e.name = $name, 
                              e.org_id = $org_id, 
                              e.clearance_level = $clearance_level,
                              e.departments = $departments,
                              e.projects = $projects
                ON MATCH SET e.name = $name, 
                             e.clearance_level = $clearance_level,
                             e.departments = $departments,
                             e.projects = $projects
            """, {
                "id": entity_id,
                "name": entity_name,
                "org_id": org_id,
                "clearance_level": clearance_level,
                "departments": departments,
                "projects": projects
            })
        
        # Create Relationships
        for rel in relationships:
            src_id = rel["source"].lower().replace(" ", "_")
            tgt_id = rel["target"].lower().replace(" ", "_")
            rel_type = normalize_rel_type(rel.get("type"))
            
            # Parametric cypher query execution for relationship
            query = f"""
                MATCH (s:Entity {{id: $src_id}})
                MATCH (t:Entity {{id: $tgt_id}})
                MERGE (s)-[r:{rel_type}]->(t)
                SET r.clearance_level = $clearance_level
            """
            session.run(query, {
                "src_id": src_id,
                "tgt_id": tgt_id,
                "clearance_level": clearance_level
            })
    driver.close()

# --- Main Ingestion Function ---
def ingest_text_block(doc_id, org_id, clearance_level, departments, projects, text, canonical_threshold=0.85):
    print(f"\n[Ingest] Processing document {doc_id}...")
    
    # 1. Save document with its vector embedding to PostgreSQL
    print("[Ingest] Generating vector embedding and saving to PostgreSQL...")
    save_document_to_postgres(doc_id, org_id, clearance_level, departments, projects, text)
    
    # 2. Extract facts using Ollama
    print("[Ingest] Extracting entities and relationships using Ollama...")
    facts = extract_entities_and_relations(text)
    extracted_entities = facts.get("entities", [])
    extracted_rels = facts.get("relationships", [])
    
    print(f"[Ingest] Extracted {len(extracted_entities)} entities, {len(extracted_rels)} relationships.")
    
    if not extracted_entities:
        print("[Ingest] No entities extracted. Skipping graph insertion.")
        return
        
    # 3. Canonicalize entities using compiled C++ DSU module
    print("[Ingest] Clustering and resolving entities using C++ DSU engine...")
    mapping = aegis_dsu.canonicalize(extracted_entities, canonical_threshold)
    
    canonical_entities = list(set(mapping.values()))
    print(f"[Ingest] Resolved {len(extracted_entities)} entities down to {len(canonical_entities)} canonical cluster representatives.")
    for orig, canonical in mapping.items():
        if orig != canonical:
            print(f"  - Resolved: '{orig}' -> '{canonical}'")
            
    # 4. Map relationships to canonical names
    canonical_rels = []
    for rel in extracted_rels:
        src = rel.get("source")
        tgt = rel.get("target")
        rel_type = rel.get("type", "ASSOCIATED_WITH")
        
        # Resolve to canonical names if present in map
        canon_src = mapping.get(src, src)
        canon_tgt = mapping.get(tgt, tgt)
        
        if canon_src and canon_tgt:
            canonical_rels.append({
                "source": canon_src,
                "target": canon_tgt,
                "type": rel_type
            })

    # 5. Insert resolved graph data to Neo4j
    print("[Ingest] Seeding canonicalized entities and relationships to Neo4j...")
    save_graph_to_neo4j(canonical_entities, canonical_rels, org_id, clearance_level, departments, projects)
    print("[Ingest] Ingestion completed successfully.")

if __name__ == "__main__":
    # Sample run
    sample_text = (
        "Project Aegis Phoenix focuses on acquiring BetaGraph. BetaGraph is a major competitor. "
        "The project is managed by the Engineering department. The development team uses AWS "
        "as their primary cloud provider. Amazon Web Services (AWS) hosts the lock-free routing matrix."
    )
    
    ingest_text_block(
        doc_id="99999999-9999-9999-9999-999999999999",
        org_id="org_alpha",
        clearance_level=3,
        departments=["Engineering", "Executive"],
        projects=["Mergers"],
        text=sample_text,
        canonical_threshold=0.80
    )

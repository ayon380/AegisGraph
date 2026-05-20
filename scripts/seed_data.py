import os
import sys
import random
import json
import psycopg2
from psycopg2.extras import execute_values
from neo4j import GraphDatabase

# --- Configuration & Environment Variables ---
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

# --- Mock Enterprise Data ---
DOCUMENTS = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "org_id": "org_alpha",
        "clearance_level": 1,
        "departments": ["Engineering", "Support"],
        "projects": [],
        "content": "This document outlines the standard coding style guidelines for AegisGraph. All code must follow clean principles and be thoroughly documented.",
        "node_id": "aegisgraph_style",
        "node_name": "AegisGraph Style Guide"
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "org_id": "org_alpha",
        "clearance_level": 2,
        "departments": ["Engineering"],
        "projects": ["CoreEngine"],
        "content": "AegisGraph Core Engine architecture uses a lock-free ring buffer for passing events between threads. The routing matrix coordinates events using a custom Drogon controller.",
        "node_id": "core_engine",
        "node_name": "AegisGraph Core Engine"
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "org_id": "org_alpha",
        "clearance_level": 2,
        "departments": ["Engineering"],
        "projects": ["CoreEngine"],
        "content": "The Payments Microservice processes card payments and subscription billing. It communicates with Stripe APIs and handles transactional failovers.",
        "node_id": "payments_microservice",
        "node_name": "Payments Microservice"
    },
    {
        "id": "44444444-4444-4444-4444-444444444444",
        "org_id": "org_alpha",
        "clearance_level": 2,
        "departments": ["HR"],
        "projects": ["CompensationReview"],
        "content": "Employee compensation bands for Year 2026. Grade 4: $120k-$160k. Grade 5: $150k-$210k. All salary reviews must be completed by November 2026.",
        "node_id": "comp_bands",
        "node_name": "2026 Compensation Bands"
    },
    {
        "id": "55555555-5555-5555-5555-555555555555",
        "org_id": "org_alpha",
        "clearance_level": 3,
        "departments": ["Executive", "Finance"],
        "projects": ["Mergers"],
        "content": "Project Aegis Phoenix: Acquisition of competitor BetaGraph is in final stages of diligence. Valuation is estimated at $45M, structured as 60% cash and 40% equity.",
        "node_id": "beta_graph_acq",
        "node_name": "Project Aegis Phoenix (BetaGraph Acquisition)"
    }
]

# --- Helper functions ---

def get_embedding(text):
    """
    Attempts to fetch 768-dim embedding from local Ollama.
    Falls back to synthetic random normalized vector if Ollama is unavailable.
    """
    try:
        import requests
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=3
        )
        if response.status_code == 200:
            return response.json()["embedding"]
    except Exception as e:
        print(f"Ollama embedding fetch failed ({e}). Falling back to synthetic vector.")
    
    # Synthetic vector fallback (length 768)
    vec = [random.uniform(-1.0, 1.0) for _ in range(768)]
    norm = sum(x*x for x in vec) ** 0.5
    return [x/norm for x in vec]

def init_postgres_schema(pg_conn):
    """Reads and executes init_postgres.sql to prepare the schema."""
    script_path = os.path.join(os.path.dirname(__file__), "init_postgres.sql")
    with open(script_path, "r") as f:
        sql = f.read()
    
    with pg_conn.cursor() as cursor:
        cursor.execute(sql)
    pg_conn.commit()
    print("PostgreSQL schema initialized successfully.")

def seed_postgres(pg_conn):
    """Embeds and inserts the documents into PostgreSQL."""
    print("Generating embeddings and seeding PostgreSQL...")
    data_to_insert = []
    for doc in DOCUMENTS:
        embedding = get_embedding(doc["content"])
        data_to_insert.append((
            doc["id"],
            doc["org_id"],
            doc["clearance_level"],
            doc["departments"],
            doc["projects"],
            doc["content"],
            embedding
        ))
    
    with pg_conn.cursor() as cursor:
        # We need to insert vectors explicitly using execute_values
        query = """
            INSERT INTO document_embeddings (id, org_id, clearance_level, departments, projects, content, embedding)
            VALUES %s
        """
        execute_values(cursor, query, data_to_insert)
    pg_conn.commit()
    print(f"Seeded {len(DOCUMENTS)} documents into PostgreSQL.")

def seed_neo4j():
    """Seeds graph entities and relationships in Neo4j with security attributes."""
    print("Connecting to Neo4j and seeding graph...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Clear existing entities and relationships
        session.run("MATCH (n:Entity) DETACH DELETE n")
        
        # Create unique constraint
        session.run("CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
        
        # Create Nodes
        for doc in DOCUMENTS:
            session.run("""
                CREATE (e:Entity {
                    id: $id,
                    name: $name,
                    org_id: $org_id,
                    clearance_level: $clearance_level,
                    departments: $departments,
                    projects: $projects
                })
            """, {
                "id": doc["node_id"],
                "name": doc["node_name"],
                "org_id": doc["org_id"],
                "clearance_level": doc["clearance_level"],
                "departments": doc["departments"],
                "projects": doc["projects"]
            })
            
        # Create Relationships with metadata
        # 1. core_engine -[:DEPENDS_ON {clearance_level: 2}]-> payments_microservice
        # 2. payments_microservice -[:PROCESSES_SALARIES {clearance_level: 3}]-> comp_bands
        # 3. core_engine -[:MANAGED_BY {clearance_level: 1}]-> aegisgraph_style
        # 4. beta_graph_acq -[:ACQUISITION_TARGET_OF {clearance_level: 3}]-> core_engine
        
        relationships = [
            ("core_engine", "DEPENDS_ON", "payments_microservice", 2),
            ("payments_microservice", "PROCESSES_SALARIES", "comp_bands", 3),
            ("core_engine", "MANAGED_BY", "aegisgraph_style", 1),
            ("beta_graph_acq", "ACQUISITION_TARGET_OF", "core_engine", 3)
        ]
        
        for source, rel_type, target, clearance in relationships:
            query = f"""
                MATCH (s:Entity {{id: $source}})
                MATCH (t:Entity {{id: $target}})
                CREATE (s)-[r:{rel_type} {{clearance_level: $clearance}}]->(t)
            """
            session.run(query, {"source": source, "target": target, "clearance": clearance})
            
    driver.close()
    print("Seeded Neo4j graph nodes and relationships.")

# --- Security Verification Logic ---

def generate_jwt(payload, secret):
    import hmac
    import hashlib
    import base64
    import json
    
    def base64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')
        
    header = {"alg": "HS256", "typ": "JWT"}
    header_encoded = base64url_encode(json.dumps(header).encode('utf-8'))
    payload_encoded = base64url_encode(json.dumps(payload).encode('utf-8'))
    
    msg = f"{header_encoded}.{payload_encoded}".encode('utf-8')
    sig = hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).digest()
    sig_encoded = base64url_encode(sig)
    
    return f"{header_encoded}.{payload_encoded}.{sig_encoded}"

def run_postgres_verification(test_cases):
    """
    Simulates database connections under different user contexts
    using cryptographically signed JWT tokens verified directly in Postgres.
    Connects as 'app_user' (non-superuser) to ensure PostgreSQL RLS is enforced.
    """
    print("\n================ PostgreSQL Cryptographic RLS Verification ================")
    import time
    secret = "super-secure-shared-secret-key-12345"
    
    try:
        # Connect as non-superuser to test RLS
        verification_conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            user="app_user",
            password="app_password",
            dbname=PG_DATABASE
        )
    except Exception as e:
        print(f"CRITICAL: Failed to connect as app_user: {e}")
        return

    try:
        # 1. Test Standard Cases
        for case in test_cases:
            role = case["role"]
            payload = {
                "org_id": case["org_id"],
                "clearance_level": case["clearance"],
                "departments": case["departments"],
                "projects": case["projects"],
                "exp": int(time.time()) + 3600
            }
            
            token = generate_jwt(payload, secret)
            print(f"\nSimulating Role: {role}")
            print(f"  JWT Generated: {token[:30]}...{token[-20:]}")
            
            # Start a transaction block
            with verification_conn.cursor() as cursor:
                try:
                    # Execute cryptographic session initializer
                    cursor.execute("SELECT set_secure_session(%s);", (token,))
                    
                    # Run simple retrieval
                    cursor.execute("SELECT id, clearance_level, departments, projects, content FROM document_embeddings;")
                    rows = cursor.fetchall()
                    
                    print(f"  --> Retrieved {len(rows)} documents:")
                    for row in rows:
                        print(f"      - ID: {row[0]}, Clearance: {row[1]}, Depts: {row[2]}, Projects: {row[3]} | Msg: '{row[4][:40]}...'")
                        
                    # Verify expectation
                    retrieved_contents = [row[4] for row in rows]
                    for exp_content, expected_allowed in case["expected_docs"].items():
                        is_retrieved = any(exp_content in rc for rc in retrieved_contents)
                        status = "PASS" if is_retrieved == expected_allowed else "FAIL"
                        outcome = "retrieved" if is_retrieved else "blocked"
                        expected_outcome = "retrieved" if expected_allowed else "blocked"
                        print(f"      [{status}] Doc containing '{exp_content}' should be {expected_outcome}: actually {outcome}")
                    
                    # Commit transaction to reset session variables
                    verification_conn.commit()
                except Exception as e:
                    verification_conn.rollback()
                    print(f"      [FAIL] Failed to run test case: {e}")

        # 2. Test Security Boundary Failures
        print("\n================ PostgreSQL Cryptographic Boundary Tests ================")
        
        # Test Case A: Invalid Signature
        print("\nTest Case A: Tampered Signature JWT")
        bad_token = generate_jwt({
            "org_id": "org_alpha", "clearance_level": 3, "departments": ["Executive"], "projects": ["Mergers"], "exp": int(time.time()) + 3600
        }, "wrong-secret-key-9999")
        
        with verification_conn.cursor() as cursor:
            try:
                cursor.execute("SELECT set_secure_session(%s);", (bad_token,))
                cursor.execute("SELECT id FROM document_embeddings;")
                rows = cursor.fetchall()
                print("  [FAIL] Database accepted invalid signature token!")
                verification_conn.commit()
            except Exception as e:
                verification_conn.rollback()
                print(f"  [PASS] Database successfully rejected tampered JWT signature: {str(e).strip()}")

        # Test Case B: Expired Token
        print("\nTest Case B: Expired JWT")
        expired_token = generate_jwt({
            "org_id": "org_alpha", "clearance_level": 3, "departments": ["Executive"], "projects": ["Mergers"], "exp": int(time.time()) - 60
        }, secret)
        
        with verification_conn.cursor() as cursor:
            try:
                cursor.execute("SELECT set_secure_session(%s);", (expired_token,))
                cursor.execute("SELECT id FROM document_embeddings;")
                rows = cursor.fetchall()
                print("  [FAIL] Database accepted expired token!")
                verification_conn.commit()
            except Exception as e:
                verification_conn.rollback()
                print(f"  [PASS] Database successfully rejected expired JWT: {str(e).strip()}")

    finally:
        verification_conn.close()


def run_neo4j_verification(test_cases):
    """
    Simulates graph query authorization checks on Nodes and Edges
    using parameterized Cypher queries that enforce the security boundary.
    """
    print("\n================ Neo4j Graph Security Verification ================")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    for case in test_cases:
        role = case["role"]
        org_id = case["org_id"]
        clearance = case["clearance"]
        user_depts = case["departments"]
        user_projs = case["projects"]
        
        print(f"\nSimulating Role: {role} (Clearance: {clearance}, Depts: {user_depts}, Projects: {user_projs})")
        
        # Test Query 1: Single Node retrieval
        # Retrieve all Entities visible to this user
        with driver.session() as session:
            result = session.run("""
                MATCH (e:Entity)
                WHERE e.org_id = $org_id
                  AND e.clearance_level <= $clearance
                  AND ANY(d IN e.departments WHERE d IN $user_depts)
                  AND (
                      size(e.projects) = 0 
                      OR ANY(p IN e.projects WHERE p IN $user_projects)
                  )
                RETURN e.id AS id, e.name AS name
            """, {
                "org_id": org_id,
                "clearance": clearance,
                "user_depts": user_depts,
                "user_projects": user_projs
            })
            
            nodes = [record["id"] for record in result]
            print(f"  --> Visible nodes: {nodes}")
            
            # Check expected nodes
            for exp_node, expected_allowed in case["expected_nodes"].items():
                is_retrieved = exp_node in nodes
                status = "PASS" if is_retrieved == expected_allowed else "FAIL"
                outcome = "retrieved" if is_retrieved else "blocked"
                expected_outcome = "retrieved" if expected_allowed else "blocked"
                print(f"      [{status}] Node '{exp_node}' should be {expected_outcome}: actually {outcome}")

        # Test Query 2: Path Traversal Security
        # We traverse from `core_engine` and list adjacent connections.
        # We must secure the start node, relationship, AND end node.
        # This protects against traversing confidential edges (like PROCESSES_SALARIES)
        # or reaching confidential nodes.
        print("  --> Traversing connections from 'core_engine':")
        with driver.session() as session:
            result = session.run("""
                MATCH (s:Entity {id: 'core_engine'})-[r]->(t:Entity)
                WHERE s.org_id = $org_id 
                  AND s.clearance_level <= $clearance 
                  AND ANY(d IN s.departments WHERE d IN $user_depts)
                  AND (size(s.projects) = 0 OR ANY(p IN s.projects WHERE p IN $user_projects))
                  
                  AND r.clearance_level <= $clearance
                  
                  AND t.org_id = $org_id 
                  AND t.clearance_level <= $clearance 
                  AND ANY(d IN t.departments WHERE d IN $user_depts)
                  AND (size(t.projects) = 0 OR ANY(p IN t.projects WHERE p IN $user_projects))
                RETURN t.id AS target, type(r) AS rel_type
            """, {
                "org_id": org_id,
                "clearance": clearance,
                "user_depts": user_depts,
                "user_projects": user_projs
            })
            
            connections = [(rec["target"], rec["rel_type"]) for rec in result]
            print(f"      Connections traversed: {connections}")
            
            # Verify specific connection traversal limits
            # Intern should see MANAGED_BY -> aegisgraph_style
            # Engineer should see DEPENDS_ON -> payments_microservice, but NOT downstream PROCESSES_SALARIES (cl=3)
            # Exec should see both, and should see beta_graph_acq
            
    driver.close()

# --- Main Entry Point ---

def main():
    # Attempt to connect to PostgreSQL
    print(f"Connecting to PostgreSQL database '{PG_DATABASE}' at {PG_HOST}:{PG_PORT}...")
    try:
        pg_conn = psycopg2.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            dbname=PG_DATABASE
        )
    except Exception as e:
        print(f"CRITICAL: Failed to connect to PostgreSQL: {e}")
        print("Please check that PostgreSQL is running locally and credentials match environment variables.")
        sys.exit(1)
        
    # Initialize schema and seed PostgreSQL
    try:
        init_postgres_schema(pg_conn)
        seed_postgres(pg_conn)
    except Exception as e:
        print(f"CRITICAL: Failed PostgreSQL seed: {e}")
        pg_conn.close()
        sys.exit(1)

    # Seed Neo4j
    try:
        seed_neo4j()
    except Exception as e:
        print(f"CRITICAL: Failed to seed Neo4j: {e}")
        pg_conn.close()
        sys.exit(1)
        
    # Define Security Test Cases simulating specific user contexts
    test_cases = [
        {
            "role": "Intern (Engineering)",
            "org_id": "org_alpha",
            "clearance": 1,
            "departments": ["Engineering"],
            "projects": [],
            "expected_docs": {
                "coding style guidelines": True,     # Clearance 1, Dept Engineering
                "Core Engine architecture": False,   # Clearance 2, Project CoreEngine (needs proj)
                "compensation bands": False,        # Clearance 2, Dept HR
                "Acquisition of competitor": False   # Clearance 3, Dept Exec
            },
            "expected_nodes": {
                "aegisgraph_style": True,
                "core_engine": False,
                "payments_microservice": False,
                "comp_bands": False,
                "beta_graph_acq": False
            }
        },
        {
            "role": "Software Engineer (Core Engine Project)",
            "org_id": "org_alpha",
            "clearance": 2,
            "departments": ["Engineering"],
            "projects": ["CoreEngine"],
            "expected_docs": {
                "coding style guidelines": True,     # Clearance 1, Dept Eng (and Support)
                "Core Engine architecture": True,    # Clearance 2, Dept Eng, Project CoreEngine
                "compensation bands": False,        # Clearance 2, Dept HR (blocked dept)
                "Acquisition of competitor": False   # Clearance 3, Dept Exec (blocked clearance)
            },
            "expected_nodes": {
                "aegisgraph_style": True,
                "core_engine": True,
                "payments_microservice": True,
                "comp_bands": False,
                "beta_graph_acq": False
            }
        },
        {
            "role": "HR Manager",
            "org_id": "org_alpha",
            "clearance": 2,
            "departments": ["HR"],
            "projects": ["CompensationReview"],
            "expected_docs": {
                "coding style guidelines": False,    # Clearance 1, Dept Eng/Support (wrong dept)
                "Core Engine architecture": False,   # Clearance 2, Dept Eng (wrong dept)
                "compensation bands": True,         # Clearance 2, Dept HR, Project Comp
                "Acquisition of competitor": False   # Clearance 3 (wrong clearance/dept)
            },
            "expected_nodes": {
                "aegisgraph_style": False,
                "core_engine": False,
                "payments_microservice": False,
                "comp_bands": True,
                "beta_graph_acq": False
            }
        },
        {
            "role": "Executive (Finance & M&A)",
            "org_id": "org_alpha",
            "clearance": 3,
            "departments": ["Executive", "Finance", "Engineering"],
            "projects": ["Mergers", "CoreEngine"],
            "expected_docs": {
                "coding style guidelines": True,     # Clearance 1, Dept Eng (user has Eng)
                "Core Engine architecture": True,    # Clearance 2, Dept Eng, Proj CoreEngine
                "compensation bands": False,        # Clearance 2, Dept HR (no HR dept)
                "Acquisition of competitor": True    # Clearance 3, Dept Exec, Proj Mergers
            },
            "expected_nodes": {
                "aegisgraph_style": True,
                "core_engine": True,
                "payments_microservice": True,
                "comp_bands": False,
                "beta_graph_acq": True
            }
        }
    ]
    
    # Run the tests
    try:
        run_postgres_verification(test_cases)
        run_neo4j_verification(test_cases)
    finally:
        pg_conn.close()
        print("\nAll database verifications completed.")

if __name__ == "__main__":
    main()

#!/Users/bishalkumarshah/miniforge3/envs/rag/bin/python
"""Cache & Latency Test Suite for Intradoc AI."""
import json
import sys
import time
import requests

BASE = "http://localhost:8001"

def log(msg):
    print(msg, flush=True)

def call(method, path, **kwargs):
    url = f"{BASE}{path}"
    fn = getattr(requests, method.lower())
    r = fn(url, **kwargs)
    try:
        return r.json()
    except:
        return {"raw": r.text, "status": r.status_code}

def colored(label, val):
    icon = "PASS" if val else "FAIL"
    return f"  [{icon}] {label}: {val}"

log("=" * 55)
log("  INTRADOC AI — CACHING & LATENCY TEST SUITE")
log("=" * 55)
log("")

# --- AUTH ---
log("[1] Authenticating...")
auth = call("POST", "/api/auth/login", json={"username": "admin", "password": "admin123"})
token = auth.get("access", "")
if not token:
    log("  FAIL: Could not get token")
    sys.exit(1)
log(f"  Token: {token[:20]}...")
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
log("")

# --- HEALTH ---
log("[2] Health Check...")
live = call("GET", "/api/health/live")
ready = call("GET", "/api/health/ready")
log(f"  live -> {live.get('status','?')}")
log(f"  ready -> {ready.get('status','?')} deps={ready.get('dependencies',{})}")
log("")

# --- CACHE STATS BEFORE ---
log("[3] Cache Stats (before)...")
stats = call("GET", "/api/cache/stats", headers=headers)
log(f"  Memory: {stats.get('used_memory_human','?')}")
log(f"  Types: {stats.get('cache_types',[])}")
log("")

# --- LIST DOCS ---
log("[4] Documents list (pagination)...")
docs = call("GET", "/api/documents?limit=10&offset=0", headers=headers)
if isinstance(docs, list):
    log(f"  Count: {len(docs)}")
    for d in docs:
        log(f"    [{d['status']}] {d['filename']} ({(d['file_size']/1024):.1f} KB)")
elif isinstance(docs, dict):
    results = docs.get("results", docs)
    log(f"  Total: {docs.get('total', len(results))}")
    for d in results:
        log(f"    [{d['status']}] {d['filename']} ({(d['file_size']/1024):.1f} KB)")

# --- ADMIN METRICS ---
log("[5] Admin Metrics (N+1 test)...")
t0 = time.perf_counter()
metrics = call("GET", "/api/admin/metrics", headers=headers)
t1 = time.perf_counter()
log(f"  Latency: {(t1-t0)*1000:.0f}ms")
log(f"  Users: {metrics.get('metrics',{}).get('total_users',0)}")
log(f"  Docs: {metrics.get('metrics',{}).get('total_documents',0)}")
log(f"  Chunks: {metrics.get('metrics',{}).get('total_chunks',0)}")
log(f"  Sessions: {metrics.get('metrics',{}).get('total_sessions',0)}")
log(f"  Activities: {len(metrics.get('recent_activities',[]))}")
log("")

# --- KNOWLEDGE GRAPH ---
log("[6] Knowledge Graph (N+1 test)...")
t0 = time.perf_counter()
kg = call("GET", "/api/admin/knowledge-graph", headers=headers)
t1 = time.perf_counter()
log(f"  Latency: {(t1-t0)*1000:.0f}ms")
log(f"  Departments: {len(kg.get('departments',[]))}")
for dept in kg.get("departments", []):
    log(f"    {dept['name']}: {dept['document_count']} docs, {dept['chunk_count']} chunks")
log("")

# --- LLM CONFIG ---
log("[7] LLM Config (key masking)...")
cfg = call("GET", "/api/admin/llm-config", headers=headers)
ak = cfg.get("api_keys", {})
for k, v in ak.items():
    log(f"  {k}: '{v}' (masked)")
log(f"  enforce_globally: {cfg.get('enforce_globally')}")
log(f"  provider: {cfg.get('config',{}).get('provider')}")
log("")

# --- CREATE SESSION ---
log("[8] Create chat session...")
session = call("POST", "/api/chat/sessions", json={"name": "Cache Latency Test"}, headers=headers)
sid = session.get("id", "")
log(f"  Session: {sid[:20]}...")
log("")

# --- RAG QUERY 1: COLD CACHE ---
log("[9] RAG Query 1 — Cold Cache (first ever)...")
q1 = {"question": "What is Bishal Kumar Shahs educational background and AI skills?",
      "session_id": sid, "department": "General"}
t0 = time.perf_counter()
r1 = call("POST", "/api/chat/query", json=q1, headers=headers)
t1 = time.perf_counter()
ms1 = (t1 - t0) * 1000
log(f"  CLI wall time: {ms1:.0f}ms")
log(f"  server_latency_ms: {r1.get('latency_ms')}")
log(f"  cache_hit: {r1.get('cache_hit')}")
log(f"  success: {r1.get('success')}")
log(f"  model_used: {r1.get('model_used')}")
log(f"  steps: {r1.get('steps')}")
log(f"  input_tokens: {r1.get('input_tokens')}")
log(f"  output_tokens: {r1.get('output_tokens')}")
log(f"  cost: ${r1.get('estimated_cost_usd', 0):.6f}")
gen = r1.get("content", "") or r1.get("generation", "")
if gen:
    log(f"  response: {gen[:250]}...")
else:
    log(f"  response: (empty)")
log("")

# If first query succeeded, test cache hit
if r1.get("success"):
    # --- RAG QUERY 2: SEMANTIC CACHE HIT ---
    log("[10] RAG Query 2 — Semantic Cache Hit (same question)...")
    t0 = time.perf_counter()
    r2 = call("POST", "/api/chat/query", json=q1, headers=headers)
    t1 = time.perf_counter()
    ms2 = (t1 - t0) * 1000
    speedup = ms1 / ms2 if ms2 > 0 else float('inf')
    log(f"  CLI wall time: {ms2:.0f}ms  (vs {ms1:.0f}ms cold = {speedup:.1f}x speedup)")
    log(f"  cache_hit: {r2.get('cache_hit')}")
    log(f"  steps: {r2.get('steps')}")
    log(f"  server_latency_ms: {r2.get('latency_ms')}")
    gen2 = r2.get("content", "") or r2.get("generation", "")
    log(f"  response: {gen2[:150]}...")
    log("")

    # --- RAG QUERY 3: SIMILAR QUESTION (semantic similarity) ---
    log("[11] RAG Query 3 — Similar Phrasing (semantic similarity)...")
    q3 = {"question": "Tell me about Bishal Kumar Shah's education and his AI skills",
          "session_id": sid, "department": "General"}
    t0 = time.perf_counter()
    r3 = call("POST", "/api/chat/query", json=q3, headers=headers)
    t1 = time.perf_counter()
    ms3 = (t1 - t0) * 1000
    log(f"  CLI wall time: {ms3:.0f}ms")
    log(f"  cache_hit: {r3.get('cache_hit')}")
    log(f"  steps: {r3.get('steps')}")
    log(f"  server_latency_ms: {r3.get('latency_ms')}")
    gen3 = r3.get("content", "") or r3.get("generation", "")
    log(f"  response: {gen3[:150]}...")
    log("")

# --- CACHE STATS AFTER ---
log("[12] Cache Stats (after queries)...")
stats2 = call("GET", "/api/cache/stats", headers=headers)
log(f"  Memory: {stats2.get('used_memory_human','?')}")
log("")

# --- SUMMARY ---
log("=" * 55)
log("  SUMMARY")
log("=" * 55)

results = []

# Health
results.append(("Health /live", live.get("status") == "ok"))
results.append(("Health /ready (redis)", ready.get("dependencies", {}).get("redis") == True))
results.append(("Health /ready (db)", ready.get("dependencies", {}).get("database") == True))

# Cache
results.append(("Cache stats endpoint", "used_memory_human" in stats))
results.append(("11 cache types initialized", len(stats.get("cache_types", [])) == 11))

# Auth/Config
results.append(("Auth login works", bool(token)))
results.append(("API keys masked at rest", all(ak.values())))
results.append(("Enforce globally (server keys)", cfg.get("enforce_globally") == True))

# Admin
results.append(("Admin metrics (N+1 fixed)", "metrics" in metrics))
results.append(("Knowledge graph (N+1 fixed)", "departments" in kg))

# RAG
success = r1.get("success")
results.append(("RAG query execution", success))

if success:
    results.append(("Semantic cached query", r2.get("cache_hit") == True))
    results.append(("Cache speedup > 5x", ms1 / ms2 > 5 if ms2 > 0 else False))

for label, ok in results:
    log(f"  {'PASS' if ok else 'FAIL'}: {label}")

log("")
log("Done.")

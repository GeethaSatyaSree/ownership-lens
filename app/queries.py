"""All Cypher for Ownership Lens.

Queries are module-level constants and are executed with parameters passed
separately to the driver. No query in this file is ever assembled from user
input by string formatting.

Two queries carry most of the argument for using a graph database:

  ULTIMATE_BENEFICIAL_OWNERS - a variable-depth traversal that multiplies
      ownership percentages along each path. In SQL this needs a recursive
      CTE carrying a running product, and the depth is not known in advance.

  RING_OF_2 / RING_OF_3 / RING_OF_4 - find ownership cycles. A recursive CTE
      walks into an infinite loop on a cycle unless you hand-write
      visited-node tracking.

Two openCypher dialect notes, both found by testing against CognoDB:

  * CognoDB's variable-length expansion enforces NODE uniqueness, so a path
    may not revisit a node and can never return to its own start. Cycle
    detection therefore uses fixed-length patterns. See RING_OF_2 below.

  * openCypher fixes the order of WITH subclauses as
    ORDER BY / SKIP / LIMIT / WHERE. A WHERE written before ORDER BY is a
    syntax error. See SHARED_ADDRESS_CLUSTERS below.
"""
from typing import Any

from .db import run_query

# Depth caps everywhere. The free c0 tier is a burstable 0.5 vCPU instance,
# so unbounded variable-length patterns are never sent to it.
DEFAULT_LIMIT = 25

# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

REGISTRY_STATS = """
MATCH (c:Company)  WITH count(c) AS companies
MATCH (p:Person)   WITH companies, count(p) AS people
MATCH ()-[r:OWNS]->() WITH companies, people, count(r) AS ownership_links
MATCH ()-[d:DIRECTOR_OF]->()
RETURN companies, people, ownership_links, count(d) AS directorships
"""

# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

SEARCH_COMPANIES = """
MATCH (c:Company)
WHERE toLower(c.name) CONTAINS toLower($term)
RETURN c.id AS id, c.name AS name, c.jurisdiction AS detail, c.status AS status
ORDER BY c.name
LIMIT $limit
"""

SEARCH_PEOPLE = """
MATCH (p:Person)
WHERE toLower(p.name) CONTAINS toLower($term)
RETURN p.id AS id, p.name AS name, p.nationality AS detail
ORDER BY p.name
LIMIT $limit
"""

# --------------------------------------------------------------------------
# Company profile
# --------------------------------------------------------------------------

COMPANY_PROFILE = """
MATCH (c:Company {id: $company_id})
OPTIONAL MATCH (c)-[:REGISTERED_AT]->(a:Address)
RETURN c.id AS id,
       c.name AS name,
       c.jurisdiction AS jurisdiction,
       c.incorporated AS incorporated,
       c.status AS status,
       c.sector AS sector,
       a.id AS address_id,
       a.line AS address_line,
       a.city AS address_city,
       a.country AS address_country
"""

DIRECT_OWNERS = """
MATCH (owner)-[r:OWNS]->(c:Company {id: $company_id})
RETURN labels(owner)[0] AS owner_type,
       owner.id AS owner_id,
       owner.name AS name,
       r.pct AS pct,
       r.since AS since
ORDER BY r.pct DESC
"""

COMPANY_DIRECTORS = """
MATCH (p:Person)-[r:DIRECTOR_OF]->(c:Company {id: $company_id})
RETURN p.id AS person_id, p.name AS name, r.role AS role, r.since AS since
ORDER BY r.since
"""

# THE MULTI-HOP TRAVERSAL (satisfies section 5.1).
#
# Walks 1..6 OWNS hops backwards from the company to every natural person who
# holds a stake, multiplying the percentages along each path with reduce().
# A person reachable by several routes has their path shares summed.
ULTIMATE_BENEFICIAL_OWNERS = """
MATCH path = (owner:Person)-[:OWNS*1..6]->(target:Company {id: $company_id})
WITH owner,
     reduce(share = 1.0, r IN relationships(path) | share * r.pct / 100.0) * 100 AS path_pct,
     [n IN nodes(path) | n.name] AS chain,
     length(path) AS hops
WITH owner,
     sum(path_pct) AS effective_pct,
     collect({chain: chain, pct: path_pct, hops: hops}) AS paths
ORDER BY effective_pct DESC
LIMIT $limit
RETURN owner.id AS person_id,
       owner.name AS name,
       owner.nationality AS nationality,
       round(effective_pct * 100) / 100.0 AS effective_pct,
       paths
"""

# What this company controls further down the chain.
SUBSIDIARIES = """
MATCH path = (c:Company {id: $company_id})-[:OWNS*1..4]->(sub:Company)
WITH sub,
     sum(reduce(share = 1.0, r IN relationships(path) | share * r.pct / 100.0) * 100) AS effective_pct,
     min(length(path)) AS hops
ORDER BY effective_pct DESC
LIMIT $limit
RETURN sub.id AS id,
       sub.name AS name,
       sub.jurisdiction AS jurisdiction,
       round(effective_pct * 100) / 100.0 AS effective_pct,
       hops
"""

# --------------------------------------------------------------------------
# Person profile
# --------------------------------------------------------------------------

PERSON_PROFILE = """
MATCH (p:Person {id: $person_id})
RETURN p.id AS id, p.name AS name, p.nationality AS nationality, p.born AS born
"""

PERSON_DIRECTORSHIPS = """
MATCH (p:Person {id: $person_id})-[r:DIRECTOR_OF]->(c:Company)
RETURN c.id AS company_id, c.name AS name, c.jurisdiction AS jurisdiction,
       r.role AS role, r.since AS since
ORDER BY r.since
"""

# Everything this person controls, directly or through any chain of companies.
CONTROL_FOOTPRINT = """
MATCH path = (p:Person {id: $person_id})-[:OWNS*1..6]->(c:Company)
WITH c,
     sum(reduce(share = 1.0, r IN relationships(path) | share * r.pct / 100.0) * 100) AS effective_pct,
     min(length(path)) AS hops
ORDER BY effective_pct DESC
LIMIT $limit
RETURN c.id AS id,
       c.name AS name,
       c.jurisdiction AS jurisdiction,
       round(effective_pct * 100) / 100.0 AS effective_pct,
       hops
"""

# --------------------------------------------------------------------------
# Insights - the queries a relational database finds awkward
# --------------------------------------------------------------------------

# THE AWKWARD-IN-SQL QUERY (satisfies section 5.1).
#
# Finds ownership rings: A owns B owns C owns A.
#
# These are fixed-length patterns rather than one variable-length pattern,
# because CognoDB's variable-length expansion enforces NODE uniqueness - a
# path may not revisit a node, so it can never return to its own start.
# (Neo4j enforces RELATIONSHIP uniqueness instead, which is why
# `(c)-[:OWNS*2..6]->(c)` finds cycles there and returns nothing here. Both
# are legal openCypher; the spec leaves the choice to the implementation.)
#
# Binding each position to its own variable sidesteps this. Requiring c0 to
# hold the lowest id keeps only one rotation, so a three-company ring is
# reported once instead of once per member.

RING_OF_2 = """
MATCH (c0:Company)-[r1:OWNS]->(c1:Company)-[r2:OWNS]->(c0)
WHERE c0.id < c1.id
RETURN [c0.name, c1.name, c0.name] AS ring,
       [r1.pct, r2.pct] AS percentages,
       2 AS hops
LIMIT $limit
"""

RING_OF_3 = """
MATCH (c0:Company)-[r1:OWNS]->(c1:Company)-[r2:OWNS]->(c2:Company)-[r3:OWNS]->(c0)
WHERE c0.id < c1.id AND c0.id < c2.id AND c1.id <> c2.id
RETURN [c0.name, c1.name, c2.name, c0.name] AS ring,
       [r1.pct, r2.pct, r3.pct] AS percentages,
       3 AS hops
LIMIT $limit
"""

RING_OF_4 = """
MATCH (c0:Company)-[r1:OWNS]->(c1:Company)-[r2:OWNS]->(c2:Company)
      -[r3:OWNS]->(c3:Company)-[r4:OWNS]->(c0)
WHERE c0.id < c1.id AND c0.id < c2.id AND c0.id < c3.id
  AND c1.id <> c2.id AND c1.id <> c3.id AND c2.id <> c3.id
RETURN [c0.name, c1.name, c2.name, c3.name, c0.name] AS ring,
       [r1.pct, r2.pct, r3.pct, r4.pct] AS percentages,
       4 AS hops
LIMIT $limit
"""

# Rings are detected up to four companies. Each extra length needs its own
# pattern, and ownership rings longer than four are vanishingly rare.
RING_QUERIES = (RING_OF_2, RING_OF_3, RING_OF_4)

# Addresses hosting several companies that also share a director - the
# classic registered-agent shell pattern.
#
# The filter and the sort live in separate WITH clauses on purpose. openCypher
# fixes the order of subclauses as ORDER BY / SKIP / LIMIT / WHERE, so a WHERE
# written before ORDER BY is a syntax error, and moving it after would apply
# LIMIT before the filter. Two WITH clauses express filter-then-sort-then-limit
# portably.
#
# This returns one row per (address, director) pair; the wrapper below groups
# them so each address is presented once.
SHARED_ADDRESS_CLUSTERS = """
MATCH (c:Company)-[:REGISTERED_AT]->(a:Address)
WITH a, count(c) AS company_count
WHERE company_count >= $min_companies
MATCH (d:Person)-[:DIRECTOR_OF]->(c2:Company)-[:REGISTERED_AT]->(a)
WITH a, company_count, d, count(DISTINCT c2) AS companies_directed
WHERE companies_directed >= $min_shared
WITH a, company_count, d, companies_directed
ORDER BY companies_directed DESC, company_count DESC
LIMIT $limit
RETURN a.id AS address_id,
       a.line AS line,
       a.city AS city,
       a.country AS country,
       company_count,
       d.id AS director_id,
       d.name AS director_name,
       companies_directed
"""

COMPANIES_AT_ADDRESS = """
MATCH (c:Company)-[:REGISTERED_AT]->(a:Address {id: $address_id})
RETURN c.id AS id, c.name AS name, c.jurisdiction AS jurisdiction, c.status AS status
ORDER BY c.name
LIMIT $limit
"""

# --------------------------------------------------------------------------
# Python wrappers
# --------------------------------------------------------------------------

def registry_stats() -> dict[str, Any]:
    rows = run_query(REGISTRY_STATS)
    return rows[0] if rows else {
        "companies": 0, "people": 0, "ownership_links": 0, "directorships": 0
    }


def search(term: str, limit: int = DEFAULT_LIMIT) -> dict[str, list[dict]]:
    params = {"term": term, "limit": limit}
    return {
        "companies": run_query(SEARCH_COMPANIES, params),
        "people": run_query(SEARCH_PEOPLE, params),
    }


def company_profile(company_id: str) -> dict[str, Any] | None:
    rows = run_query(COMPANY_PROFILE, {"company_id": company_id})
    return rows[0] if rows else None


def direct_owners(company_id: str) -> list[dict]:
    return run_query(DIRECT_OWNERS, {"company_id": company_id})


def company_directors(company_id: str) -> list[dict]:
    return run_query(COMPANY_DIRECTORS, {"company_id": company_id})


def ultimate_beneficial_owners(company_id: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    return run_query(ULTIMATE_BENEFICIAL_OWNERS,
                     {"company_id": company_id, "limit": limit})


def subsidiaries(company_id: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    return run_query(SUBSIDIARIES, {"company_id": company_id, "limit": limit})


def person_profile(person_id: str) -> dict[str, Any] | None:
    rows = run_query(PERSON_PROFILE, {"person_id": person_id})
    return rows[0] if rows else None


def person_directorships(person_id: str) -> list[dict]:
    return run_query(PERSON_DIRECTORSHIPS, {"person_id": person_id})


def control_footprint(person_id: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    return run_query(CONTROL_FOOTPRINT, {"person_id": person_id, "limit": limit})


def circular_ownership(limit: int = 10) -> list[dict]:
    """Collect ownership rings of length 2, 3 and 4, shortest first.

    One round trip per ring length. The queries are fixed module constants -
    nothing here is assembled from user input.
    """
    rings: list[dict] = []
    for cypher in RING_QUERIES:
        rings.extend(run_query(cypher, {"limit": limit}))
    rings.sort(key=lambda ring: ring["hops"])
    return rings[:limit]


def shared_address_clusters(min_companies: int = 4, min_shared: int = 3,
                            limit: int = 10) -> list[dict]:
    """Group the (address, director) rows so each address appears once.

    The Cypher LIMIT bounds director rows, not addresses, so it is raised and
    the address list is trimmed here instead.
    """
    rows = run_query(SHARED_ADDRESS_CLUSTERS, {
        "min_companies": min_companies,
        "min_shared": min_shared,
        "limit": limit * 5,
    })

    clusters: dict[str, dict[str, Any]] = {}
    for row in rows:
        cluster = clusters.setdefault(row["address_id"], {
            "address_id": row["address_id"],
            "line": row["line"],
            "city": row["city"],
            "country": row["country"],
            "company_count": row["company_count"],
            "directors": [],
        })
        cluster["directors"].append({
            "id": row["director_id"],
            "name": row["director_name"],
            "count": row["companies_directed"],
        })

    return list(clusters.values())[:limit]


def companies_at_address(address_id: str, limit: int = 50) -> list[dict]:
    return run_query(COMPANIES_AT_ADDRESS, {"address_id": address_id, "limit": limit})
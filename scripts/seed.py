"""Load the Ownership Lens registry into CognoDB.

Run from the project root:  python -m scripts.seed

The dataset has two halves:

1. A hand-authored "spine" - named companies and people arranged into
   ownership structures that are interesting on purpose: a five-level chain,
   a three-company ownership cycle, and a cluster of shells sharing one
   address and one nominee director.

2. A deterministically generated background registry, so the spine sits
   inside a realistic dataset rather than floating alone. The generator is
   seeded, so every run produces an identical database.

All companies and people are fictional.
"""
import random
import sys
from typing import Any

from app.db import DatabaseUnavailable, check_connection, close_driver, run_query, run_write

RNG = random.Random(42)

GENERATED_COMPANIES = 300
GENERATED_PEOPLE = 220
GENERATED_ADDRESSES = 120

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

JURISDICTIONS = [
    "India", "Singapore", "British Virgin Islands", "Cyprus",
    "Delaware, USA", "Mauritius", "Netherlands", "United Arab Emirates",
]

SECTORS = [
    "Retail", "Logistics", "Financial services", "Real estate",
    "Technology", "Pharmaceuticals", "Energy", "Media", "Hospitality",
]

# The eight hand-authored addresses. Only these carry narrative meaning; the
# generated companies use a separate pool so that the shell cluster at A-001
# stays a genuine outlier instead of being drowned in background noise.
SPINE_ADDRESSES = [
    {"id": "A-001", "line": "Unit 12-04, Ocean Financial Centre, 10 Collyer Quay",
     "city": "Singapore", "country": "Singapore"},
    {"id": "A-002", "line": "Craigmuir Chambers, Road Town",
     "city": "Tortola", "country": "British Virgin Islands"},
    {"id": "A-003", "line": "Plot 44, HITEC City, Madhapur",
     "city": "Hyderabad", "country": "India"},
    {"id": "A-004", "line": "1209 North Orange Street",
     "city": "Wilmington", "country": "Delaware, USA"},
    {"id": "A-005", "line": "Arch. Makariou III 199, Neocleous House",
     "city": "Limassol", "country": "Cyprus"},
    {"id": "A-006", "line": "Cyber Tower 1, Ebene Cybercity",
     "city": "Ebene", "country": "Mauritius"},
    {"id": "A-007", "line": "Herengracht 566",
     "city": "Amsterdam", "country": "Netherlands"},
    {"id": "A-008", "line": "Level 21, Emirates Towers, Sheikh Zayed Road",
     "city": "Dubai", "country": "United Arab Emirates"},
]

# --------------------------------------------------------------------------
# The hand-authored spine
# --------------------------------------------------------------------------

SPINE_PEOPLE = [
    {"id": "P-001", "name": "Isabelle Moreau",   "nationality": "France",   "born": "1968"},
    {"id": "P-002", "name": "Aleksandr Volkov",  "nationality": "Cyprus",   "born": "1974"},
    {"id": "P-003", "name": "Kavya Raman",       "nationality": "India",    "born": "1981"},
    {"id": "P-004", "name": "Marcus Adeyemi",    "nationality": "Nigeria",  "born": "1970"},
    {"id": "P-005", "name": "Lena Fischer",      "nationality": "Germany",  "born": "1985"},
    {"id": "P-006", "name": "Rohit Nambiar",     "nationality": "India",    "born": "1979"},
    {"id": "P-007", "name": "Priya Deshmukh",    "nationality": "India",    "born": "1988"},
    {"id": "P-008", "name": "Tomas Silva",       "nationality": "Portugal", "born": "1972"},
]

SPINE_COMPANIES = [
    {"id": "C-ORION",  "name": "Orion Retail India Private Limited",
     "jurisdiction": "India", "incorporated": "2016-04-11",
     "status": "Active", "sector": "Retail", "address": "A-003"},
    {"id": "C-MER1",   "name": "Meridian Commerce Holdings Pte Ltd",
     "jurisdiction": "Singapore", "incorporated": "2015-09-02",
     "status": "Active", "sector": "Financial services", "address": "A-001"},
    {"id": "C-MER2",   "name": "Meridian Global Ltd",
     "jurisdiction": "British Virgin Islands", "incorporated": "2014-06-19",
     "status": "Active", "sector": "Financial services", "address": "A-002"},
    {"id": "C-TRI",    "name": "Trident Nominees Ltd",
     "jurisdiction": "Cyprus", "incorporated": "2011-02-28",
     "status": "Active", "sector": "Financial services", "address": "A-005"},
    {"id": "C-VAN",    "name": "Vantage South Partners LLC",
     "jurisdiction": "Delaware, USA", "incorporated": "2017-11-30",
     "status": "Active", "sector": "Financial services", "address": "A-004"},
    {"id": "C-HELIX1", "name": "Helix Capital Ltd",
     "jurisdiction": "Mauritius", "incorporated": "2013-07-15",
     "status": "Active", "sector": "Financial services", "address": "A-006"},
    {"id": "C-HELIX2", "name": "Helix Ventures Pte Ltd",
     "jurisdiction": "Singapore", "incorporated": "2013-08-01",
     "status": "Active", "sector": "Financial services", "address": "A-001"},
    {"id": "C-HELIX3", "name": "Helix Holdings Ltd",
     "jurisdiction": "British Virgin Islands", "incorporated": "2013-08-22",
     "status": "Active", "sector": "Financial services", "address": "A-002"},
]

# Five companies at one address, all with the same nominee director.
SHELL_NAMES = [
    "Blue Harbour Trading Pte Ltd",
    "Northgate Commodities Pte Ltd",
    "Silverline Import Export Pte Ltd",
    "Kestrel Marine Services Pte Ltd",
    "Anchorpoint Ventures Pte Ltd",
]
SPINE_COMPANIES += [
    {"id": f"C-SHELL{i}", "name": name, "jurisdiction": "Singapore",
     "incorporated": f"2019-0{i}-14", "status": "Active",
     "sector": "Logistics", "address": "A-001"}
    for i, name in enumerate(SHELL_NAMES, start=1)
]

# Company -> Company ownership. The Helix trio is a deliberate cycle.
SPINE_COMPANY_OWNS = [
    {"owner": "C-MER1",   "target": "C-ORION",  "pct": 62.0, "since": "2016-04-11"},
    {"owner": "C-VAN",    "target": "C-ORION",  "pct": 20.0, "since": "2018-01-20"},
    {"owner": "C-MER2",   "target": "C-MER1",   "pct": 80.0, "since": "2015-09-02"},
    {"owner": "C-TRI",    "target": "C-MER2",   "pct": 55.0, "since": "2014-06-19"},
    {"owner": "C-HELIX1", "target": "C-VAN",    "pct": 40.0, "since": "2019-03-05"},
    {"owner": "C-HELIX1", "target": "C-HELIX2", "pct": 40.0, "since": "2013-08-01"},
    {"owner": "C-HELIX2", "target": "C-HELIX3", "pct": 35.0, "since": "2013-08-22"},
    {"owner": "C-HELIX3", "target": "C-HELIX1", "pct": 30.0, "since": "2014-01-10"},
]

# Person -> Company ownership.
SPINE_PERSON_OWNS = [
    {"owner": "P-003", "target": "C-ORION",  "pct": 18.0,  "since": "2016-04-11"},
    {"owner": "P-005", "target": "C-MER1",   "pct": 20.0,  "since": "2015-09-02"},
    {"owner": "P-002", "target": "C-MER2",   "pct": 45.0,  "since": "2014-06-19"},
    {"owner": "P-001", "target": "C-TRI",    "pct": 100.0, "since": "2011-02-28"},
    {"owner": "P-004", "target": "C-VAN",    "pct": 60.0,  "since": "2017-11-30"},
    {"owner": "P-008", "target": "C-HELIX1", "pct": 30.0,  "since": "2013-07-15"},
]

SPINE_DIRECTORS = [
    {"person": "P-003", "company": "C-ORION",  "role": "Managing Director", "since": "2016-04-11"},
    {"person": "P-007", "company": "C-ORION",  "role": "Director",          "since": "2020-06-01"},
    {"person": "P-006", "company": "C-MER1",   "role": "Nominee Director",  "since": "2015-09-02"},
    {"person": "P-002", "company": "C-MER2",   "role": "Director",          "since": "2014-06-19"},
    {"person": "P-002", "company": "C-TRI",    "role": "Director",          "since": "2011-02-28"},
    {"person": "P-004", "company": "C-VAN",    "role": "Managing Member",   "since": "2017-11-30"},
    {"person": "P-008", "company": "C-HELIX1", "role": "Director",          "since": "2013-07-15"},
    {"person": "P-008", "company": "C-HELIX2", "role": "Director",          "since": "2013-08-01"},
    {"person": "P-008", "company": "C-HELIX3", "role": "Director",          "since": "2013-08-22"},
] + [
    {"person": "P-006", "company": f"C-SHELL{i}", "role": "Nominee Director", "since": "2019-05-14"}
    for i in range(1, 6)
]

# --------------------------------------------------------------------------
# Generated background registry
# --------------------------------------------------------------------------

FIRST_NAMES = ["Aarav", "Diya", "Noah", "Mei", "Liam", "Sofia", "Omar", "Hannah",
               "Yusuf", "Ana", "Ravi", "Elena", "Chen", "Fatima", "Jonas", "Ines",
               "Arjun", "Nadia", "Pedro", "Zara"]
LAST_NAMES = ["Iyer", "Okonkwo", "Nakamura", "Fernandes", "Novak", "Haddad",
              "Lindqvist", "Rossi", "Mwangi", "Petrov", "Sharma", "Dubois",
              "Katz", "Bakker", "Reyes", "Tan"]
COMPANY_A = ["Amber", "Basalt", "Cinder", "Drift", "Ember", "Fathom", "Granite",
             "Harbour", "Ironwood", "Junction", "Kestrel", "Lantern", "Meadow",
             "Nimbus", "Orchard", "Pillar", "Quarry", "Ridge", "Summit", "Tidal"]
COMPANY_B = ["Capital", "Trading", "Holdings", "Ventures", "Industries",
             "Partners", "Logistics", "Group", "Enterprises", "Associates"]
COMPANY_C = ["Ltd", "Pte Ltd", "LLC", "Private Limited", "B.V.", "Limited"]

STREETS = ["High Street", "Marine Parade", "Church Road", "Park Avenue",
           "Station Road", "Mill Lane", "Cedar Court", "Bay View",
           "Kingsway", "Union Square"]
CITY_COUNTRY = [
    ("Mumbai", "India"), ("Bengaluru", "India"), ("Singapore", "Singapore"),
    ("Rotterdam", "Netherlands"), ("Nicosia", "Cyprus"),
    ("Dubai", "United Arab Emirates"), ("Port Louis", "Mauritius"),
    ("Austin", "Delaware, USA"),
]


def generate_addresses() -> list[dict[str, Any]]:
    """Ordinary addresses for the background registry."""
    rows = []
    for i in range(1, GENERATED_ADDRESSES + 1):
        city, country = RNG.choice(CITY_COUNTRY)
        rows.append({
            "id": f"A-G{i:04d}",
            "line": f"{RNG.randint(1, 400)} {RNG.choice(STREETS)}",
            "city": city,
            "country": country,
        })
    return rows


def generate_people() -> list[dict[str, Any]]:
    return [
        {
            "id": f"P-G{i:04d}",
            "name": f"{RNG.choice(FIRST_NAMES)} {RNG.choice(LAST_NAMES)}",
            "nationality": RNG.choice(JURISDICTIONS),
            "born": str(RNG.randint(1955, 1995)),
        }
        for i in range(1, GENERATED_PEOPLE + 1)
    ]


def generate_companies(addresses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"C-G{i:04d}",
            "name": f"{RNG.choice(COMPANY_A)} {RNG.choice(COMPANY_B)} {RNG.choice(COMPANY_C)}",
            "jurisdiction": RNG.choice(JURISDICTIONS),
            "incorporated": (
                f"{RNG.randint(2005, 2023)}-{RNG.randint(1, 12):02d}-{RNG.randint(1, 28):02d}"
            ),
            "status": RNG.choice(["Active"] * 9 + ["Dissolved"]),
            "sector": RNG.choice(SECTORS),
            "address": RNG.choice(addresses)["id"],
        }
        for i in range(1, GENERATED_COMPANIES + 1)
    ]


def generate_ownership(companies, people):
    """Build a sparse, strictly acyclic ownership background.

    A generated company may only be owned by one earlier in the list, which
    makes cycles impossible. The only cycle in the database is the
    hand-authored Helix trio, so the cycle-detection query has a known,
    explainable answer rather than accidental noise.
    """
    company_owns, person_owns, directors = [], [], []

    for index, company in enumerate(companies):
        remaining = 100.0

        # 0-2 corporate parents, always from earlier in the list.
        if index > 5:
            for _ in range(RNG.randint(0, 2)):
                parent = companies[RNG.randint(0, index - 1)]
                pct = round(RNG.uniform(10, 45), 1)
                if pct >= remaining:
                    break
                company_owns.append({
                    "owner": parent["id"], "target": company["id"],
                    "pct": pct, "since": company["incorporated"],
                })
                remaining -= pct

        # Whatever is left is split between one or two individuals.
        holders = RNG.sample(people, RNG.randint(1, 2))
        share = round(remaining / len(holders), 1)
        if share > 0:
            for holder in holders:
                person_owns.append({
                    "owner": holder["id"], "target": company["id"],
                    "pct": share, "since": company["incorporated"],
                })

        for director in RNG.sample(people, RNG.randint(1, 2)):
            directors.append({
                "person": director["id"], "company": company["id"],
                "role": RNG.choice(["Director", "Managing Director", "Secretary"]),
                "since": company["incorporated"],
            })

    return company_owns, person_owns, directors


# --------------------------------------------------------------------------
# Cypher - every statement is parameterised and batched with UNWIND
# --------------------------------------------------------------------------

CONSTRAINTS = [
    "CREATE CONSTRAINT company_id IF NOT EXISTS FOR (c:Company) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT person_id  IF NOT EXISTS FOR (p:Person)  REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT address_id IF NOT EXISTS FOR (a:Address) REQUIRE a.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX company_name IF NOT EXISTS FOR (c:Company) ON (c.name)",
    "CREATE INDEX person_name  IF NOT EXISTS FOR (p:Person)  ON (p.name)",
]

WIPE = "MATCH (n) DETACH DELETE n"

INSERT_ADDRESSES = """
UNWIND $rows AS row
MERGE (a:Address {id: row.id})
SET a.line = row.line, a.city = row.city, a.country = row.country
"""

INSERT_PEOPLE = """
UNWIND $rows AS row
MERGE (p:Person {id: row.id})
SET p.name = row.name, p.nationality = row.nationality, p.born = row.born
"""

INSERT_COMPANIES = """
UNWIND $rows AS row
MERGE (c:Company {id: row.id})
SET c.name = row.name,
    c.jurisdiction = row.jurisdiction,
    c.incorporated = row.incorporated,
    c.status = row.status,
    c.sector = row.sector
WITH c, row
MATCH (a:Address {id: row.address})
MERGE (c)-[:REGISTERED_AT]->(a)
"""

INSERT_COMPANY_OWNS = """
UNWIND $rows AS row
MATCH (owner:Company {id: row.owner})
MATCH (target:Company {id: row.target})
MERGE (owner)-[r:OWNS]->(target)
SET r.pct = row.pct, r.since = row.since
"""

INSERT_PERSON_OWNS = """
UNWIND $rows AS row
MATCH (owner:Person {id: row.owner})
MATCH (target:Company {id: row.target})
MERGE (owner)-[r:OWNS]->(target)
SET r.pct = row.pct, r.since = row.since
"""

INSERT_DIRECTORS = """
UNWIND $rows AS row
MATCH (p:Person {id: row.person})
MATCH (c:Company {id: row.company})
MERGE (p)-[r:DIRECTOR_OF]->(c)
SET r.role = row.role, r.since = row.since
"""


def batched(rows: list[dict], size: int = 200):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def load(label: str, cypher: str, rows: list[dict]) -> None:
    for chunk in batched(rows):
        run_write(cypher, {"rows": chunk})
    print(f"  loaded {len(rows):>5}  {label}")


def main() -> int:
    print("Seeding Ownership Lens into CognoDB\n")

    # Fail fast with one clear line rather than a wall of driver errors.
    ok, message = check_connection()
    if not ok:
        print(f"Cannot connect: {message}", file=sys.stderr)
        print("\nCheck COGNODB_URI and COGNODB_PASSWORD in your .env file.", file=sys.stderr)
        close_driver()
        return 1

    try:
        print("Applying constraints and indexes...")
        for statement in CONSTRAINTS + INDEXES:
            try:
                run_write(statement)
            except DatabaseUnavailable as exc:
                # openCypher implementations differ on DDL syntax. The app works
                # without these; they are a performance nicety, not a dependency.
                print(f"  skipped: {exc}")

        print("Clearing existing data...")
        run_write(WIPE)

        gen_addresses = generate_addresses()
        gen_people = generate_people()
        gen_companies = generate_companies(gen_addresses)

        addresses = SPINE_ADDRESSES + gen_addresses
        people = SPINE_PEOPLE + gen_people
        companies = SPINE_COMPANIES + gen_companies

        gen_company_owns, gen_person_owns, gen_directors = generate_ownership(
            gen_companies, gen_people
        )

        print("Loading nodes...")
        load("addresses", INSERT_ADDRESSES, addresses)
        load("people", INSERT_PEOPLE, people)
        load("companies", INSERT_COMPANIES, companies)

        print("Loading relationships...")
        load("OWNS (company -> company)", INSERT_COMPANY_OWNS,
             SPINE_COMPANY_OWNS + gen_company_owns)
        load("OWNS (person -> company)", INSERT_PERSON_OWNS,
             SPINE_PERSON_OWNS + gen_person_owns)
        load("DIRECTOR_OF", INSERT_DIRECTORS, SPINE_DIRECTORS + gen_directors)

        summary = run_query("""
            MATCH (n) WITH count(n) AS nodes
            MATCH ()-[r]->() RETURN nodes, count(r) AS relationships
        """)
        print(f"\nDone. {summary[0]['nodes']} nodes, {summary[0]['relationships']} relationships.")
        print("Open the app and search for 'Orion Retail'.")
        return 0

    except DatabaseUnavailable as exc:
        print(f"\nSeed failed: {exc}", file=sys.stderr)
        return 1
    finally:
        close_driver()


if __name__ == "__main__":
    raise SystemExit(main())
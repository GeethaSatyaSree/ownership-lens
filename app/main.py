"""FastAPI application for Ownership Lens.

Routing and rendering only. All Cypher lives in queries.py and all connection
handling in db.py, so this file stays readable end to end.
"""
from pathlib import Path
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import queries
from .config import settings
from .db import DatabaseUnavailable, check_connection, close_driver

logging.basicConfig(level=logging.INFO)

# The threshold most corporate registries use to define a beneficial owner.
DISCLOSURE_THRESHOLD = 25.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    ok, message = check_connection()
    logging.getLogger(__name__).info("Startup database check: %s", message)
    yield
    close_driver()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["app_name"] = settings.app_name
templates.env.globals["threshold"] = DISCLOSURE_THRESHOLD


def render(request: Request, template: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, template, context)


@app.exception_handler(DatabaseUnavailable)
async def database_unavailable_handler(request: Request, exc: DatabaseUnavailable):
    """Render a friendly page instead of a stack trace when CognoDB is down."""
    return templates.TemplateResponse(
        request, "error.html",
        {"message": str(exc)},
        status_code=503,
    )


@app.get("/health")
def health():
    ok, message = check_connection()
    return JSONResponse({"database": "up" if ok else "down", "detail": message},
                        status_code=200 if ok else 503)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render(request, "index.html", stats=queries.registry_stats())


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    term = q.strip()
    results = {"companies": [], "people": []}
    if term:
        results = queries.search(term)
    return render(request, "search.html", term=term, results=results)


@app.get("/company/{company_id}", response_class=HTMLResponse)
def company(request: Request, company_id: str):
    profile = queries.company_profile(company_id)
    if profile is None:
        return render(request, "error.html",
                      message=f"No company found with id {company_id}.")
    ubos = queries.ultimate_beneficial_owners(company_id)
    return render(
        request, "company.html",
        company=profile,
        owners=queries.direct_owners(company_id),
        directors=queries.company_directors(company_id),
        ubos=ubos,
        flagged=[u for u in ubos if u["effective_pct"] >= DISCLOSURE_THRESHOLD],
        subsidiaries=queries.subsidiaries(company_id),
    )


@app.get("/person/{person_id}", response_class=HTMLResponse)
def person(request: Request, person_id: str):
    profile = queries.person_profile(person_id)
    if profile is None:
        return render(request, "error.html",
                      message=f"No person found with id {person_id}.")
    return render(
        request, "person.html",
        person=profile,
        holdings=queries.control_footprint(person_id),
        directorships=queries.person_directorships(person_id),
    )


@app.get("/address/{address_id}", response_class=HTMLResponse)
def address(request: Request, address_id: str):
    companies = queries.companies_at_address(address_id)
    return render(request, "search.html",
                  term=f"companies registered at {address_id}",
                  results={"companies": companies, "people": []})


@app.get("/insights", response_class=HTMLResponse)
def insights(request: Request):
    return render(
        request, "insights.html",
        rings=queries.circular_ownership(),
        clusters=queries.shared_address_clusters(),
    )
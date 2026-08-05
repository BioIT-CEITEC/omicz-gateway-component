from fastapi import APIRouter, Request

router = APIRouter()
from shared_templates import templates


@router.get("/")
def test(request: Request):
    return templates.TemplateResponse(request, "test.html")

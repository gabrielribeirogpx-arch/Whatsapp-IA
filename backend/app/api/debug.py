from fastapi import APIRouter, HTTPException

from scripts.scan_all_flows import scan_all

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/scan-flows")
def scan_flows():
    """
    Endpoint temporário para diagnóstico de flows no banco.
    NÃO USAR EM PRODUÇÃO FINAL.
    """
    import os

    if os.getenv("ENV") == "production":
        raise HTTPException(status_code=403, detail="Debug disabled in production")
    return scan_all()

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import Product, Tenant
from backend.app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from backend.app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
def list_products(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return (
        db.execute(select(Product).where(Product.tenant_id == tenant.id).order_by(Product.created_at.desc(), Product.id.desc()))
        .scalars()
        .all()
    )


@router.post("", response_model=ProductOut)
def create_product(
    payload: ProductCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    product = Product(
        tenant_id=tenant.id,
        name=payload.name.strip(),
        description=(payload.description.strip() if payload.description else None),
        price=(payload.price.strip() if payload.price else None),
        benefits=(payload.benefits.strip() if payload.benefits else None),
        objections=(payload.objections.strip() if payload.objections else None),
        target_customer=(payload.target_customer.strip() if payload.target_customer else None),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    product = db.execute(select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)).scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    product.name = payload.name.strip()
    product.description = payload.description.strip() if payload.description else None
    product.price = payload.price.strip() if payload.price else None
    product.benefits = payload.benefits.strip() if payload.benefits else None
    product.objections = payload.objections.strip() if payload.objections else None
    product.target_customer = payload.target_customer.strip() if payload.target_customer else None

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}")
def delete_product(
    product_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    product = db.execute(select(Product).where(Product.id == product_id, Product.tenant_id == tenant.id)).scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    db.delete(product)
    db.commit()
    return {"deleted": True}

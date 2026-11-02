from sqlalchemy import String, Integer, Float, Date, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(120), default="Uncategorized")
    supplier_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    warehouse_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    inventory_level: Mapped[int] = mapped_column(Integer, default=0)
    lead_time: Mapped[int] = mapped_column(Integer, default=7)
    __table_args__ = (Index("ix_products_user_product", "user_id", "product_id", unique=True),)

class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(80), index=True)
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    quantity_sold: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float, default=0)

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    supplier_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_time: Mapped[int] = mapped_column(Integer, default=7)
    reliability: Mapped[float] = mapped_column(Float, default=0.95)

class Forecast(Base):
    __tablename__ = "forecasts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[str] = mapped_column(String(80), index=True)
    forecast_date: Mapped[datetime.date] = mapped_column(Date)
    predicted_demand: Mapped[float] = mapped_column(Float)
    model_name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

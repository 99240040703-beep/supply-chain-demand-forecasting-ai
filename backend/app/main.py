from datetime import date, timedelta
from io import BytesIO
import json
import pandas as pd
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from .database import Base, engine, get_db
from .models import User, Product, Sale, Supplier, Forecast
from .schemas import RegisterIn, LoginIn, SupplierIn, ChatIn, ForecastIn
from .security import hash_password, verify_password, create_token, current_user
from .config import settings
from .ml import preprocess, train_and_forecast

Base.metadata.create_all(bind=engine)
app=FastAPI(title="Supply Chain Forecasting AI",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(",")],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

@app.get("/health")
def health(db:Session=Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status":"ok","database":"connected"}

@app.post("/api/auth/register")
def register(body:RegisterIn,db:Session=Depends(get_db)):
    email=str(body.email).lower().strip()
    if db.query(User).filter(User.email==email).first(): raise HTTPException(409,"Email already registered")
    if settings.secret_key=="CHANGE_ME": raise HTTPException(503,"Set SECRET_KEY before creating accounts")
    user=User(email=email,password_hash=hash_password(body.password));db.add(user);db.commit();db.refresh(user)
    return {"access_token":create_token(user.id),"token_type":"bearer","user":{"id":user.id,"email":user.email}}

@app.post("/api/auth/login")
def login(body:LoginIn,db:Session=Depends(get_db)):
    user=db.query(User).filter(User.email==str(body.email).lower().strip()).first()
    if not user or not verify_password(body.password,user.password_hash): raise HTTPException(401,"Incorrect email or password")
    return {"access_token":create_token(user.id),"token_type":"bearer","user":{"id":user.id,"email":user.email}}

@app.get("/api/auth/me")
def me(user:User=Depends(current_user)): return {"id":user.id,"email":user.email}

@app.post("/api/datasets/upload")
async def upload_dataset(file:UploadFile=File(...),db:Session=Depends(get_db),user:User=Depends(current_user)):
    name=(file.filename or "").lower()
    if not name.endswith((".csv",".xlsx",".xls")): raise HTTPException(400,"Upload CSV or Excel")
    raw=await file.read()
    if len(raw)>15*1024*1024: raise HTTPException(413,"File exceeds 15 MB")
    try: df=pd.read_csv(BytesIO(raw)) if name.endswith(".csv") else pd.read_excel(BytesIO(raw))
    except Exception as exc: raise HTTPException(400,f"Could not read dataset: {exc}")
    try: clean=preprocess(df)
    except ValueError as exc: raise HTTPException(422,str(exc))
    for pid,group in clean.groupby("Product_ID"):
        row=group.iloc[-1]; product=db.query(Product).filter_by(user_id=user.id,product_id=str(pid)).first()
        values={"name":str(row.Product_Name),"category":str(row.Category),"unit_price":float(row.Unit_Price),"inventory_level":int(row.Inventory_Level),"lead_time":max(1,int(row.Lead_Time)),"supplier_id":str(row.Supplier_ID),"warehouse_id":str(row.Warehouse_ID)}
        if product:
            for key,value in values.items(): setattr(product,key,value)
        else: db.add(Product(user_id=user.id,product_id=str(pid),**values))
    for row in clean.itertuples(index=False):
        db.add(Sale(user_id=user.id,product_id=str(row.Product_ID),date=row.Date.date(),quantity_sold=float(row.Quantity_Sold),unit_price=float(row.Unit_Price)))
    db.commit()
    return {"filename":file.filename,"rows_received":len(df),"rows_imported":len(clean),"products":int(clean.Product_ID.nunique()),"removed_or_invalid_rows":int(len(df)-len(clean))}

@app.get("/api/datasets/sample")
def sample_dataset():
    rows=[]
    for p in range(1,4):
        for i in range(120):
            rows.append({"Date":(date.today()-timedelta(days=119-i)).isoformat(),"Product_ID":f"SKU-{p:03}","Product_Name":f"Product {p}","Category":["Electronics","Home","Office"][p-1],"Quantity_Sold":max(0,20+p*5+(i%7)*2),"Unit_Price":100+p*25,"Inventory_Level":120,"Lead_Time":7+p,"Supplier_ID":f"SUP-{p:02}","Warehouse_ID":"WH-01"})
    out=BytesIO();pd.DataFrame(rows).to_csv(out,index=False);out.seek(0)
    return StreamingResponse(out,media_type="text/csv",headers={"Content-Disposition":"attachment; filename=sample_supply_chain.csv"})

@app.post("/api/forecast/train")
def train(body:ForecastIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    sales=db.query(Sale).filter_by(user_id=user.id).all()
    if not sales: raise HTTPException(400,"Upload sales history before training")
    frame=pd.DataFrame([{"Date":s.date,"Product_ID":s.product_id,"Quantity_Sold":s.quantity_sold} for s in sales])
    if body.product_id: frame=frame[frame.Product_ID==body.product_id]
    predictions,metrics=train_and_forecast(frame,body.days)
    if not predictions: raise HTTPException(422,"At least 40 days of history are required for each product")
    db.query(Forecast).filter_by(user_id=user.id).delete()
    for item in predictions: db.add(Forecast(user_id=user.id,product_id=item["product_id"],forecast_date=date.fromisoformat(item["date"]),predicted_demand=item["predicted_demand"],model_name=item["model"]))
    db.commit()
    return {"predictions":predictions,"metrics":metrics,"selected_model":", ".join(sorted({p["model"] for p in predictions})),"forecast_count":len(predictions)}

@app.get("/api/forecast/history")
def forecast_history(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return [{"product_id":f.product_id,"date":f.forecast_date.isoformat(),"predicted_demand":f.predicted_demand,"model":f.model_name} for f in db.query(Forecast).filter_by(user_id=user.id).order_by(Forecast.forecast_date).all()]

@app.get("/api/forecast/metrics")
def forecast_metrics(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return {"metrics":[],"message":"Train a model to generate validation metrics."}

@app.get("/api/dashboard/summary")
def dashboard_summary(db:Session=Depends(get_db),user:User=Depends(current_user)):
    products=db.query(Product).filter_by(user_id=user.id).all();sales=db.query(Sale).filter_by(user_id=user.id).all();forecasts=db.query(Forecast).filter_by(user_id=user.id).all()
    return {"total_products":len(products),"total_inventory":sum(p.inventory_level for p in products),"total_sales":round(sum(s.quantity_sold*s.unit_price for s in sales),2),"units_sold":round(sum(s.quantity_sold for s in sales),2),"predicted_demand":round(sum(f.predicted_demand for f in forecasts),2),"low_stock_products":sum(p.inventory_level<=p.lead_time*2 for p in products),"pending_purchase_orders":0}

@app.get("/api/dashboard/sales")
def dashboard_sales(db:Session=Depends(get_db),user:User=Depends(current_user)):
    rows=db.query(Sale.date,func.sum(Sale.quantity_sold)).filter_by(user_id=user.id).group_by(Sale.date).order_by(Sale.date).all()
    return [{"date":d.isoformat(),"sales":float(q)} for d,q in rows]

def inventory_calculations(db:Session,user:User):
    result=[]
    for p in db.query(Product).filter_by(user_id=user.id).all():
        sales=db.query(Sale).filter_by(user_id=user.id,product_id=p.product_id).all()
        daily=pd.Series([s.quantity_sold for s in sales],index=[s.date for s in sales]).groupby(level=0).sum() if sales else pd.Series(dtype=float)
        avg=float(daily.mean()) if len(daily) else 0.0;std=float(daily.std()) if len(daily)>1 else 0.0
        safety=1.65*std*(p.lead_time**0.5);rop=avg*p.lead_time+safety;target=avg*30+safety
        result.append({"product_id":p.product_id,"name":p.name,"current_stock":p.inventory_level,"avg_daily_demand":round(avg,2),"safety_stock":round(safety,2),"reorder_point":round(rop,2),"recommended_order_qty":max(0,int(round(target-p.inventory_level))),"status":"REORDER" if p.inventory_level<=rop else ("OVERSTOCK" if p.inventory_level>target*2 else "HEALTHY"),"days_of_inventory":round(p.inventory_level/avg,1) if avg>0 else None})
    return result

@app.get("/api/inventory")
def inventory(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return [{"product_id":p.product_id,"name":p.name,"category":p.category,"inventory_level":p.inventory_level,"lead_time":p.lead_time,"unit_price":p.unit_price} for p in db.query(Product).filter_by(user_id=user.id).all()]
@app.post("/api/inventory/optimize")
def optimize(db:Session=Depends(get_db),user:User=Depends(current_user)): return inventory_calculations(db,user)
@app.get("/api/inventory/recommendations")
def recommendations(db:Session=Depends(get_db),user:User=Depends(current_user)): return inventory_calculations(db,user)

@app.get("/api/suppliers")
def suppliers(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return [{"id":s.id,"supplier_id":s.supplier_id,"name":s.name,"email":s.email,"lead_time":s.lead_time,"reliability":s.reliability} for s in db.query(Supplier).filter_by(user_id=user.id).all()]
@app.post("/api/suppliers")
def add_supplier(body:SupplierIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    supplier=Supplier(user_id=user.id,**body.model_dump());db.add(supplier);db.commit();db.refresh(supplier);return {"id":supplier.id,"supplier_id":supplier.supplier_id,"name":supplier.name}
@app.put("/api/suppliers/{supplier_id}")
def update_supplier(supplier_id:int,body:SupplierIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    supplier=db.query(Supplier).filter_by(id=supplier_id,user_id=user.id).first()
    if not supplier: raise HTTPException(404,"Supplier not found")
    for key,value in body.model_dump().items(): setattr(supplier,key,value)
    db.commit();return {"ok":True}
@app.delete("/api/suppliers/{supplier_id}")
def delete_supplier(supplier_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    supplier=db.query(Supplier).filter_by(id=supplier_id,user_id=user.id).first()
    if not supplier: raise HTTPException(404,"Supplier not found")
    db.delete(supplier);db.commit();return {"ok":True}

@app.post("/api/ai/chat")
def ai_chat(body:ChatIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    summary=dashboard_summary(db,user);inventory=inventory_calculations(db,user)
    if not settings.openai_api_key:
        return {"configured":False,"answer":"Configure OPENAI_API_KEY on the backend to enable natural-language answers.","context":{"summary":summary,"inventory":inventory[:20]}}
    try:
        from openai import OpenAI
        client=OpenAI(api_key=settings.openai_api_key)
        response=client.chat.completions.create(model="gpt-4o-mini",temperature=0.2,messages=[{"role":"system","content":"You are a supply-chain analyst. Use only the supplied application JSON. Never invent figures; say when data is unavailable."},{"role":"user","content":json.dumps({"question":body.question,"summary":summary,"inventory":inventory},default=str)}])
        return {"configured":True,"answer":response.choices[0].message.content}
    except Exception: raise HTTPException(502,"AI provider request failed; verify OPENAI_API_KEY and provider status")

@app.get("/api/reports/inventory")
def inventory_report(db:Session=Depends(get_db),user:User=Depends(current_user)):
    out=BytesIO();pd.DataFrame(inventory_calculations(db,user)).to_csv(out,index=False);out.seek(0)
    return StreamingResponse(out,media_type="text/csv",headers={"Content-Disposition":"attachment; filename=inventory_recommendations.csv"})

# Serve the browser dashboard from the same origin as the API. Keep this mount last
# so that it never shadows /api routes or /health.
from pathlib import Path
from fastapi.staticfiles import StaticFiles
_frontend_dir = Path(__file__).resolve().parent / "static"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")

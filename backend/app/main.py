from datetime import date, timedelta
import logging
from io import BytesIO
import zipfile
import urllib.request
import json
import pandas as pd
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from .database import Base, engine, get_db
from .models import User, Product, Sale, Supplier, Forecast, PurchaseOrder, ForecastMetric, ChatMessage
from .schemas import RegisterIn, LoginIn, SupplierIn, ChatIn, ForecastIn, PurchaseOrderIn, PurchaseOrderStatusIn
from .security import hash_password, verify_password, create_token, current_user
from .config import settings
from .ml import preprocess, train_and_forecast

logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)
app=FastAPI(title="Supply Chain Forecasting AI",version="1.0.0")
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(",")],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

@app.get("/health")
def health(db:Session=Depends(get_db)):
    db.execute(text("SELECT 1"))
    database_type = engine.dialect.name
    return {"status":"ok","database":"connected","database_type":database_type,"durable_storage":database_type=="postgresql"}

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
    for pid in clean.Product_ID.astype(str).unique():
        db.query(Sale).filter_by(user_id=user.id,product_id=pid).delete()
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

@app.post("/api/datasets/uci-online-retail/import")
def import_uci_online_retail(db:Session=Depends(get_db),user:User=Depends(current_user)):
    """Import real UCI Online Retail transactions; stock and supplier fields are explicitly estimated."""
    source_url="https://archive.ics.uci.edu/static/public/352/online+retail.zip"
    try:
        request=urllib.request.Request(source_url,headers={"User-Agent":"SupplyChainAI/1.0 (educational dataset import)"})
        with urllib.request.urlopen(request,timeout=90) as response:
            archive_bytes=response.read()
        with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
            workbook=next((n for n in archive.namelist() if n.lower().endswith(".xlsx")),None)
            if not workbook: raise ValueError("UCI archive did not contain the expected Excel workbook")
            with archive.open(workbook) as xlsx:
                raw=pd.read_excel(xlsx,usecols=["InvoiceNo","StockCode","Description","Quantity","InvoiceDate","UnitPrice"],engine="openpyxl")
    except Exception as exc:
        raise HTTPException(502,"Could not download the UCI public dataset. You can download Online Retail.xlsx from https://archive.ics.uci.edu/dataset/352/online+retail and upload it here. Details: "+str(exc)[:240])
    raw["InvoiceNo"]=raw["InvoiceNo"].astype(str)
    raw["InvoiceDate"]=pd.to_datetime(raw["InvoiceDate"],errors="coerce")
    raw["Quantity"]=pd.to_numeric(raw["Quantity"],errors="coerce")
    raw["UnitPrice"]=pd.to_numeric(raw["UnitPrice"],errors="coerce")
    clean=raw.dropna(subset=["InvoiceDate","StockCode","Description","Quantity","UnitPrice"]).copy()
    clean=clean[~clean["InvoiceNo"].str.upper().str.startswith("C")]
    clean=clean[(clean["Quantity"]>0)&(clean["UnitPrice"]>0)]
    clean["StockCode"]=clean["StockCode"].astype(str).str.strip()
    clean=clean[clean["StockCode"].ne("")]
    top_codes=clean.groupby("StockCode")["Quantity"].sum().nlargest(20).index
    clean=clean[clean["StockCode"].isin(top_codes)].copy()
    clean["Date"]=clean["InvoiceDate"].dt.normalize()
    grouped=clean.groupby(["StockCode","Date"],as_index=False).agg(Quantity_Sold=("Quantity","sum"),Product_Name=("Description",lambda x: str(x.mode().iloc[0]) if not x.mode().empty else str(x.iloc[0])))
    clean["_line_value"]=clean["Quantity"]*clean["UnitPrice"]
    price_stats=clean.groupby("StockCode").agg(_qty=("Quantity","sum"),_value=("_line_value","sum"))
    price=(price_stats["_value"]/price_stats["_qty"]).to_dict()
    last_day=grouped["Date"].max()
    rows=[]
    for pid,g in grouped.groupby("StockCode"):
        avg=float(g.tail(30)["Quantity_Sold"].mean())
        rows.extend({"Date":r.Date,"Product_ID":str(pid),"Product_Name":r.Product_Name,"Category":"Giftware","Quantity_Sold":float(r.Quantity_Sold),"Unit_Price":round(price.get(pid,0),2),"Inventory_Level":max(0,int(round(avg*14))),"Lead_Time":7,"Supplier_ID":"ESTIMATED-SUPPLIER","Warehouse_ID":"UCI-RETAIL"} for r in g.itertuples(index=False))
    imported=preprocess(pd.DataFrame(rows))
    for pid,group in imported.groupby("Product_ID"):
        row=group.iloc[-1]
        product=db.query(Product).filter_by(user_id=user.id,product_id=str(pid)).first()
        values={"name":str(row.Product_Name),"category":"Giftware","unit_price":float(row.Unit_Price),"inventory_level":int(row.Inventory_Level),"lead_time":7,"supplier_id":"ESTIMATED-SUPPLIER","warehouse_id":"UCI-RETAIL"}
        if product:
            for key,value in values.items(): setattr(product,key,value)
        else: db.add(Product(user_id=user.id,product_id=str(pid),**values))
        db.query(Sale).filter_by(user_id=user.id,product_id=str(pid)).delete()
    for row in imported.itertuples(index=False):
        db.add(Sale(user_id=user.id,product_id=str(row.Product_ID),date=row.Date.date(),quantity_sold=float(row.Quantity_Sold),unit_price=float(row.Unit_Price)))
    db.commit()
    return {"source":"UCI Online Retail (Chen, 2015)","license":"CC BY 4.0","source_url":"https://doi.org/10.24432/C5BW33","source_transactions_used":int(len(clean)),"rows_imported":int(len(imported)),"products":int(imported.Product_ID.nunique()),"date_start":imported.Date.min().date().isoformat(),"date_end":imported.Date.max().date().isoformat(),"inventory_note":"Inventory levels and supplier identifiers are demo estimates; the UCI source contains transaction sales, not stock-on-hand or supplier records."}

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
    db.query(ForecastMetric).filter_by(user_id=user.id).delete()
    for metric in metrics: db.add(ForecastMetric(user_id=user.id,product_id=metric["product_id"],model_name=metric["model"],mae=metric["mae"],rmse=metric["rmse"],wape=metric["wape"]))
    db.commit()
    return {"predictions":predictions,"metrics":metrics,"selected_model":", ".join(sorted({p["model"] for p in predictions})),"forecast_count":len(predictions)}

@app.get("/api/forecast/history")
def forecast_history(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return [{"product_id":f.product_id,"date":f.forecast_date.isoformat(),"predicted_demand":f.predicted_demand,"model":f.model_name} for f in db.query(Forecast).filter_by(user_id=user.id).order_by(Forecast.forecast_date).all()]

@app.get("/api/forecast/metrics")
def forecast_metrics(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return [{"product_id":m.product_id,"model":m.model_name,"mae":m.mae,"rmse":m.rmse,"wape":m.wape,"created_at":m.created_at.isoformat()} for m in db.query(ForecastMetric).filter_by(user_id=user.id).order_by(ForecastMetric.product_id).all()]

@app.get("/api/dashboard/summary")
def dashboard_summary(db:Session=Depends(get_db),user:User=Depends(current_user)):
    products=db.query(Product).filter_by(user_id=user.id).all();sales=db.query(Sale).filter_by(user_id=user.id).all();forecasts=db.query(Forecast).filter_by(user_id=user.id).all()
    return {"total_products":len(products),"total_inventory":sum(p.inventory_level for p in products),"total_sales":round(sum(s.quantity_sold*s.unit_price for s in sales),2),"units_sold":round(sum(s.quantity_sold for s in sales),2),"predicted_demand":round(sum(f.predicted_demand for f in forecasts),2),"low_stock_products":sum(p.inventory_level<=p.lead_time*2 for p in products),"pending_purchase_orders":db.query(PurchaseOrder).filter(PurchaseOrder.user_id==user.id,PurchaseOrder.status.in_(["DRAFT","SUBMITTED","APPROVED"])).count()}

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

@app.get("/api/ai/status")
def ai_status(user:User=Depends(current_user)):
    return {"configured":bool(settings.openai_api_key),"provider":"OpenAI","model":settings.openai_model if settings.openai_api_key else None}

@app.get("/api/ai/history")
def ai_history(db:Session=Depends(get_db),user:User=Depends(current_user)):
    rows=db.query(ChatMessage).filter_by(user_id=user.id).order_by(ChatMessage.created_at.desc(),ChatMessage.id.desc()).limit(30).all()
    return [{"role":m.role,"content":m.content,"created_at":m.created_at.isoformat()} for m in reversed(rows)]

@app.post("/api/ai/chat")
def ai_chat(body:ChatIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not settings.openai_api_key:
        return {"configured":False,"answer":"The AI provider is not connected yet. Add OPENAI_API_KEY in Render → supply-chain-demand-api → Environment, then redeploy."}
    try:
        from openai import OpenAI
        summary=dashboard_summary(db,user)
        inventory=inventory_calculations(db,user)
        supplier_rows=[{"supplier_id":s.supplier_id,"name":s.name,"lead_time":s.lead_time,"reliability":s.reliability} for s in db.query(Supplier).filter_by(user_id=user.id).limit(30).all()]
        forecast_rows=[{"product_id":f.product_id,"date":f.forecast_date.isoformat(),"predicted_demand":f.predicted_demand,"model":f.model_name} for f in db.query(Forecast).filter_by(user_id=user.id).order_by(Forecast.forecast_date).limit(60).all()]
        prior=db.query(ChatMessage).filter_by(user_id=user.id).order_by(ChatMessage.created_at.desc(),ChatMessage.id.desc()).limit(8).all()
        messages=[{"role":"system","content":"You are SupplyChain AI, an expert demand planning and inventory analyst. Answer clearly and practically. Use only the user's supplied dashboard context and conversation. Never invent numbers, stock levels, suppliers, forecasts, or API actions. If data is missing, say what should be uploaded or configured. Distinguish actual historical sales from predicted demand and estimated inventory."}]
        messages.extend([{"role":m.role,"content":m.content} for m in reversed(prior) if m.role in ("user","assistant")])
        context={"dashboard":summary,"inventory_recommendations":inventory[:30],"suppliers":supplier_rows,"forecasts":forecast_rows}
        messages.append({"role":"user","content":"Application context (JSON): "+json.dumps(context,default=str)+"\n\nQuestion: "+body.question})
        client=OpenAI(api_key=settings.openai_api_key,timeout=settings.openai_timeout_seconds,max_retries=1)
        response=client.chat.completions.create(model=settings.openai_model,temperature=0.2,messages=messages)
        answer=(response.choices[0].message.content or "I couldn't produce an answer. Please try again.").strip()
        db.add(ChatMessage(user_id=user.id,role="user",content=body.question[:8000]))
        db.add(ChatMessage(user_id=user.id,role="assistant",content=answer[:8000]))
        db.commit()
        return {"configured":True,"provider":"OpenAI","model":settings.openai_model,"answer":answer}
    except Exception as exc:
        db.rollback()
        # Log safe diagnostics only; never log credentials, headers, or prompt contents.
        logger.error("AI provider failure type=%s status=%s code=%s",
                     type(exc).__name__, getattr(exc, "status_code", None),
                     getattr(exc, "code", None))
        status = getattr(exc, "status_code", None)
        if status == 401:
            detail = "OpenAI rejected the API key. Check that the key is active and belongs to the correct project."
        elif status == 429:
            detail = "OpenAI quota or rate limit reached. Check API billing and usage limits."
        elif status == 404:
            detail = "The configured OpenAI model was not found or is unavailable to this project."
        elif status in (500, 502, 503, 504):
            detail = "OpenAI is temporarily unavailable. Please retry shortly."
        else:
            detail = "The AI service could not complete the request. Check Render logs for the safe diagnostic entry."
        raise HTTPException(502, detail)


@app.get("/api/purchase-orders")
def list_purchase_orders(db:Session=Depends(get_db),user:User=Depends(current_user)):
    from .models import PurchaseOrder
    rows=db.query(PurchaseOrder).filter_by(user_id=user.id).order_by(PurchaseOrder.created_at.desc()).all()
    return [{"id":p.id,"product_id":p.product_id,"supplier_id":p.supplier_id,"quantity":p.quantity,"unit_cost":p.unit_cost,"total_cost":round(p.quantity*p.unit_cost,2),"status":p.status,"created_at":p.created_at.isoformat()} for p in rows]

@app.post("/api/purchase-orders")
def create_purchase_order(body:PurchaseOrderIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    from .models import PurchaseOrder
    product=db.query(Product).filter_by(user_id=user.id,product_id=body.product_id).first()
    if not product: raise HTTPException(404,"Product not found")
    if body.supplier_id and not db.query(Supplier).filter_by(user_id=user.id,supplier_id=body.supplier_id).first():
        raise HTTPException(404,"Supplier not found")
    order=PurchaseOrder(user_id=user.id,product_id=body.product_id,supplier_id=body.supplier_id,quantity=body.quantity,unit_cost=product.unit_price,status="DRAFT")
    db.add(order);db.commit();db.refresh(order)
    return {"id":order.id,"status":order.status,"total_cost":round(order.quantity*order.unit_cost,2)}

@app.patch("/api/purchase-orders/{order_id}/status")
def update_purchase_order_status(order_id:int,body:PurchaseOrderStatusIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    from .models import PurchaseOrder
    order=db.query(PurchaseOrder).filter_by(id=order_id,user_id=user.id).first()
    if not order: raise HTTPException(404,"Purchase order not found")
    allowed={"DRAFT":{"SUBMITTED","CANCELLED"},"SUBMITTED":{"APPROVED","CANCELLED"},"APPROVED":{"RECEIVED","CANCELLED"},"RECEIVED":set(),"CANCELLED":set()}
    if body.status not in allowed.get(order.status,set()): raise HTTPException(409,f"Cannot change status from {order.status} to {body.status}")
    if body.status=="RECEIVED":
        product=db.query(Product).filter_by(user_id=user.id,product_id=order.product_id).first()
        if product: product.inventory_level += order.quantity
    order.status=body.status;db.commit()
    return {"id":order.id,"status":order.status}

@app.get("/api/alerts")
def alerts(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return [dict(item, severity="critical" if item["status"]=="REORDER" else "warning") for item in inventory_calculations(db,user) if item["status"]!="HEALTHY"]

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

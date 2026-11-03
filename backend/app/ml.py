import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error

REQUIRED = {"Date", "Product_ID", "Quantity_Sold"}

def preprocess(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    def _header_key(value):
        return "".join(ch for ch in str(value).strip().lower() if ch.isalnum())
    aliases = {
        "date": "Date",
        "productid": "Product_ID", "sku": "Product_ID", "itemid": "Product_ID",
        "quantitysold": "Quantity_Sold", "qtysold": "Quantity_Sold",
        "unitsold": "Quantity_Sold", "salesquantity": "Quantity_Sold",
    }
    rename = {}
    for column in frame.columns:
        cleaned = str(column).strip()
        rename[column] = aliases.get(_header_key(cleaned), cleaned)
    frame = frame.rename(columns=rename)
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(sorted(missing)) + ". Accepted headers are Date, Product_ID (or SKU), and Quantity_Sold (or Qty_Sold / Units_Sold).")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame["Quantity_Sold"] = pd.to_numeric(frame["Quantity_Sold"], errors="coerce")
    frame["Product_ID"] = frame["Product_ID"].astype("string").str.strip()
    frame = frame.dropna(subset=["Date", "Product_ID", "Quantity_Sold"])
    frame = frame[(frame["Product_ID"] != "") & (frame["Quantity_Sold"] >= 0)].drop_duplicates()
    defaults = {"Product_Name":"Unknown product","Category":"Uncategorized","Unit_Price":0,"Inventory_Level":0,"Lead_Time":7,"Promotion":0,"Supplier_ID":"","Warehouse_ID":""}
    for col, default in defaults.items():
        if col not in frame: frame[col] = default
        frame[col] = frame[col].fillna(default)
    for col in ("Unit_Price","Inventory_Level","Lead_Time","Promotion"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(defaults[col])
    return frame.sort_values("Date")

def _features(history: pd.Series, target_date: pd.Timestamp) -> dict:
    vals = {"dow":target_date.dayofweek,"month":target_date.month,"day":target_date.day,"quarter":target_date.quarter,"trend":len(history)}
    for lag in (1,7,14,30):
        vals[f"lag_{lag}"] = float(history.iloc[-lag]) if len(history)>=lag else float(history.mean())
    vals["roll7"] = float(history.tail(7).mean())
    vals["roll30"] = float(history.tail(30).mean())
    return vals

def train_and_forecast(frame: pd.DataFrame, days: int = 30):
    frame = preprocess(frame)
    records, metrics = [], []
    for pid, group in frame.groupby("Product_ID"):
        daily = group.groupby("Date")["Quantity_Sold"].sum().asfreq("D", fill_value=0)
        if len(daily) < 40: continue
        features = pd.DataFrame([_features(daily.iloc[:i], daily.index[i]) for i in range(30,len(daily))], index=daily.index[30:])
        target = daily.loc[features.index]
        split = max(1, int(len(features)*0.8))
        x_train,x_test=features.iloc[:split],features.iloc[split:]
        y_train,y_test=target.iloc[:split],target.iloc[split:]
        if len(x_test)==0: continue
        best=None; best_mae=float("inf"); best_name=""
        for name,model in [("LinearRegression",LinearRegression()),("RandomForest",RandomForestRegressor(n_estimators=120,max_depth=8,random_state=42,n_jobs=-1))]:
            model.fit(x_train,y_train)
            pred=np.maximum(0,model.predict(x_test))
            mae=float(mean_absolute_error(y_test,pred))
            rmse=float(np.sqrt(mean_squared_error(y_test,pred)))
            wape=float(np.abs(y_test.values-pred).sum()/max(float(np.abs(y_test.values).sum()),1))
            metrics.append({"product_id":str(pid),"model":name,"mae":round(mae,3),"rmse":round(rmse,3),"wape":round(wape,4)})
            if mae<best_mae: best,best_mae,best_name=model,mae,name
        history=daily.copy()
        for _ in range(days):
            next_date=history.index[-1]+pd.Timedelta(days=1)
            value=max(0.0,float(best.predict(pd.DataFrame([_features(history,next_date)]))[0]))
            history.loc[next_date]=value
            records.append({"product_id":str(pid),"date":next_date.date().isoformat(),"predicted_demand":round(value,2),"model":best_name})
    return records,metrics

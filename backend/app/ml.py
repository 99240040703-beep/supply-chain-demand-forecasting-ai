import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error

REQUIRED = {"Date", "Product_ID", "Quantity_Sold"}

# Normalize common names from retail, ERP, POS, and UCI-style sales exports.
HEADER_ALIASES = {
    "date": "Date", "invoicedate": "Date", "invoicedatetime": "Date",
    "orderdate": "Date", "transactiondate": "Date", "salesdate": "Date",
    "productid": "Product_ID", "productcode": "Product_ID",
    "sku": "Product_ID", "itemid": "Product_ID", "itemcode": "Product_ID",
    "stockcode": "Product_ID", "materialid": "Product_ID",
    "quantitysold": "Quantity_Sold", "qtysold": "Quantity_Sold",
    "unitsold": "Quantity_Sold", "salesquantity": "Quantity_Sold",
    "quantity": "Quantity_Sold", "qty": "Quantity_Sold",
    "units": "Quantity_Sold", "soldquantity": "Quantity_Sold",
    "unitprice": "Unit_Price", "price": "Unit_Price",
    "sellingprice": "Unit_Price", "productname": "Product_Name",
    "description": "Product_Name", "itemname": "Product_Name",
    "category": "Category", "productcategory": "Category",
    "inventorylevel": "Inventory_Level", "stock": "Inventory_Level",
    "stockquantity": "Inventory_Level", "onhand": "Inventory_Level",
    "leadtime": "Lead_Time", "supplierid": "Supplier_ID",
    "warehouseid": "Warehouse_ID", "promotion": "Promotion",
}

def _header_key(value) -> str:
    # Handles spaces, punctuation, underscores, hyphens, and UTF-8 BOM.
    return "".join(ch for ch in str(value).replace("\ufeff", "").strip().lower() if ch.isalnum())

def preprocess(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("The uploaded dataset is empty. Add at least one sales row and try again.")

    frame = frame.copy()
    # Ignore blank spreadsheet columns such as Unnamed: 0, but retain all useful columns.
    frame = frame.loc[:, [not str(c).strip().lower().startswith("unnamed:") for c in frame.columns]]
    rename = {column: HEADER_ALIASES.get(_header_key(column), str(column).replace("\ufeff", "").strip())
              for column in frame.columns}
    frame = frame.rename(columns=rename)

    # If a file contains both an alias and its canonical column, combine values
    # rather than producing duplicate DataFrame column names.
    if frame.columns.duplicated().any():
        merged = {}
        for name in dict.fromkeys(frame.columns):
            columns = frame.loc[:, frame.columns == name]
            merged[name] = columns.bfill(axis=1).iloc[:, 0] if columns.shape[1] > 1 else columns.iloc[:, 0]
        frame = pd.DataFrame(merged, index=frame.index)

    missing = REQUIRED - set(frame.columns)
    if missing:
        accepted = (
            "Date (InvoiceDate, OrderDate, TransactionDate), "
            "Product_ID (SKU, ItemID, StockCode, ProductCode), and "
            "Quantity_Sold (Quantity, Qty, Units, Qty_Sold, Units_Sold)."
        )
        raise ValueError("Missing required columns: " + ", ".join(sorted(missing)) +
                         ". Accepted column names include " + accepted)

    received = len(frame)
    date_values = frame["Date"]
    # Excel serial dates occasionally arrive in CSV exports as numbers.
    if pd.api.types.is_numeric_dtype(date_values):
        numeric_dates = pd.to_numeric(date_values, errors="coerce")
        parsed_dates = pd.to_datetime(numeric_dates, unit="D", origin="1899-12-30", errors="coerce")
    else:
        parsed_dates = pd.to_datetime(date_values.astype("string").str.strip(), errors="coerce", dayfirst=False)
        # Retry only values not parsed by the default month-first interpretation.
        failed = parsed_dates.isna()
        if failed.any():
            parsed_dates.loc[failed] = pd.to_datetime(
                date_values.loc[failed].astype("string").str.strip(), errors="coerce", dayfirst=True
            )

    quantities = pd.to_numeric(
        frame["Quantity_Sold"].astype("string").str.replace(",", "", regex=False).str.strip(),
        errors="coerce"
    )
    product_ids = frame["Product_ID"].astype("string").str.strip()
    valid = parsed_dates.notna() & quantities.notna() & product_ids.notna() & product_ids.ne("")
    # Negative quantities usually represent returns/credit notes; exclude them
    # from demand forecasting but report them as removed rows in upload analysis.
    valid &= quantities >= 0
    frame = frame.loc[valid].copy()
    frame["Date"] = parsed_dates.loc[valid]
    frame["Quantity_Sold"] = quantities.loc[valid].astype(float)
    frame["Product_ID"] = product_ids.loc[valid].astype(str)

    defaults = {
        "Product_Name": "Unknown product", "Category": "Uncategorized",
        "Unit_Price": 0, "Inventory_Level": 0, "Lead_Time": 7,
        "Promotion": 0, "Supplier_ID": "", "Warehouse_ID": ""
    }
    for col, default in defaults.items():
        if col not in frame:
            frame[col] = default
        frame[col] = frame[col].fillna(default)
    for col in ("Unit_Price", "Inventory_Level", "Lead_Time", "Promotion"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(defaults[col])
    frame = frame.drop_duplicates().sort_values("Date")
    if frame.empty:
        raise ValueError(
            f"No valid sales rows remain after validation (0 of {received} rows). "
            "Check that dates are readable, product IDs are not blank, and quantities are numeric and non-negative."
        )
    return frame

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

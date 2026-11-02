from datetime import date, timedelta
import pandas as pd
import pytest
from app.ml import preprocess, train_and_forecast

def test_preprocess_removes_invalid_and_duplicate_rows():
    df=pd.DataFrame([
        {"Date":"2026-01-01","Product_ID":"A","Quantity_Sold":3},
        {"Date":"2026-01-01","Product_ID":"A","Quantity_Sold":3},
        {"Date":"bad-date","Product_ID":"A","Quantity_Sold":5},
    ])
    result=preprocess(df)
    assert len(result)==1
    assert result.iloc[0].Quantity_Sold==3

def test_required_columns_are_validated():
    with pytest.raises(ValueError):
        preprocess(pd.DataFrame({"Date":["2026-01-01"]}))

def test_chronological_forecast_uses_history():
    rows=[]
    for product in ("SKU-A","SKU-B"):
        for i in range(90):
            rows.append({"Date":date(2026,1,1)+timedelta(days=i),"Product_ID":product,"Quantity_Sold":10+i%7})
    predictions,metrics=train_and_forecast(pd.DataFrame(rows),7)
    assert len(predictions)==14
    assert metrics
    assert all(p["predicted_demand"]>=0 for p in predictions)

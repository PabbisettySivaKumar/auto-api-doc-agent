from fastapi import FastAPI
app = FastAPI()

@app.get("/items")
def list_items():
    return []

@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    return {}

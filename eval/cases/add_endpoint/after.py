from fastapi import FastAPI
app = FastAPI()

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {}

@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    """Delete a user."""
    return {}

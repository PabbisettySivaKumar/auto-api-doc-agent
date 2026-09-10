from fastapi import FastAPI
app = FastAPI()

@app.post("/users")
def create_user(name: str, email: str):
    """Create a user."""
    return {}

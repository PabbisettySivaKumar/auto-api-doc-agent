from fastapi import FastAPI
app = FastAPI()

@app.post("/users")
def create_user(name: str, email: str, role: str):
    """Create a user with a role."""
    return {}

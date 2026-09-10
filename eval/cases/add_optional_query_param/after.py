from fastapi import FastAPI
app = FastAPI()

@app.get("/users/{user_id}")
def get_user(user_id: int, verbose: bool = False):
    """Fetch a user, optionally verbose."""
    return {}

"""Web server entrypoint for the v1.3.0 interface."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("web.app:app", host="0.0.0.0", port=8001, reload=True)

"""Web server entrypoint for the AI Test Case Generator Web UI."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("web.app:app", host="0.0.0.0", port=8001, reload=True)

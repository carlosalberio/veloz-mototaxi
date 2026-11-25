from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parent


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        reload_dirs=[str(PROJECT_ROOT)],
        app_dir=str(PROJECT_ROOT),
    )

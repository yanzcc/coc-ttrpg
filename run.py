"""启动服务器"""

import uvicorn
from dotenv import load_dotenv

from src.config import get_settings

load_dotenv(override=True)

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run(
        "src.api.app:create_app",
        host=s.effective_server_host(),
        port=s.effective_server_port(),
        reload=s.server.uvicorn_reload,
        factory=True,
    )

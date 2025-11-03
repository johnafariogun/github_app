from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import os
import logging
import sys

from models.a2a import JSONRPCRequest, JSONRPCResponse
from agents.github_issues_agent import GitHubIssuesAgent

load_dotenv()

# Configure root logger to stdout so logs appear in any deployment logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Initialize GitHub issues agent
github_agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown"""
    global github_agent

    # Initialize GitHub issues agent
    logger.info("Initializing GitHubIssuesAgent")
    github_agent = GitHubIssuesAgent()
    
    yield
    
    # Cleanup github_agent if it exposes cleanup
    if github_agent and hasattr(github_agent, "cleanup"):
        logger.info("Cleaning up GitHubIssuesAgent")
        await github_agent.cleanup()


app = FastAPI(
    title="GitHub Issues Agent A2A",
    description="An agent to fetch GitHub repository issues via A2A JSON-RPC",
    version="1.0.0",
    lifespan=lifespan
)


# (Comparison endpoint removed — project now focuses on GitHub issues)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "agent": "github_issues"}


@app.post("/a2a/issues")
async def issues_endpoint(request: Request):
    """Endpoint to fetch GitHub issues via the GitHubIssuesAgent A2A flow"""
    try:
        body = await request.json()

        if body.get("jsonrpc") != "2.0" or "id" not in body:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request: jsonrpc must be '2.0' and id is required"
                    }
                }
            )

        rpc_request = JSONRPCRequest(**body)

        messages = []
        context_id = None
        task_id = None
        config = None

        if rpc_request.method == "message/send":
            messages = [rpc_request.params.message]
            config = rpc_request.params.configuration
        elif rpc_request.method == "execute":
            messages = rpc_request.params.messages
            context_id = rpc_request.params.contextId
            task_id = rpc_request.params.taskId

        result = await github_agent.process_messages(
            messages=messages,
            context_id=context_id,
            task_id=task_id,
            config=config
        )

        response = JSONRPCResponse(
            id=rpc_request.id,
            result=result
        )

        return response.model_dump()

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "jsonrpc": "2.0",
                "id": body.get("id") if "body" in locals() else None,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": {"details": str(e)}
                }
            }
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5001))
    uvicorn.run(app, host="0.0.0.0", port=port)
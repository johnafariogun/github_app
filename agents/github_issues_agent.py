from uuid import uuid4
from typing import List, Optional
import re

from models.a2a import (
    A2AMessage, TaskResult, TaskStatus, Artifact,
    MessagePart, MessageConfiguration
)
from utils.utils import fetch_issues
import os


class GitHubIssuesAgent:
    def __init__(self):
        # No external client required for simple GitHub REST fetches
        self.conversations = {}

    async def process_messages(
        self,
        messages: List[A2AMessage],
        context_id: Optional[str] = None,
        task_id: Optional[str] = None,
        config: Optional[MessageConfiguration] = None
    ) -> TaskResult:
        """Process incoming A2A messages and return GitHub issues for the repo mentioned."""
        context_id = context_id or str(uuid4())
        task_id = task_id or str(uuid4())

        history = self.conversations.get(context_id, [])

        user_message = messages[-1] if messages else None
        if not user_message:
            raise ValueError("No message provided")

        # Extract text content from message parts
        text = ""
        for part in user_message.parts:
            if part.kind == "text" and part.text:
                text = part.text.strip()
                break
            elif part.kind == "data" and part.data:
                # If data contains a string or dict with repo info
                if isinstance(part.data, str):
                    text = part.data
                    break
                if isinstance(part.data, dict):
                    # try to extract owner/repo
                    owner = part.data.get("owner")
                    repo = part.data.get("repo")
                    if owner and repo:
                        text = f"{owner}/{repo}"
                        break

        if not text:
            error_msg = "Please provide a repository in the form 'owner/repo' or a sentence mentioning the repository."
            response_message = A2AMessage(
                role="agent",
                parts=[MessagePart(kind="text", text=error_msg)],
                taskId=task_id
            )

            return TaskResult(
                id=task_id,
                contextId=context_id,
                status=TaskStatus(
                    state="completed",
                    message=response_message
                ),
                artifacts=[],
                history=messages + [response_message]
            )

        # Try to parse owner/repo
        m = re.search(r"([\w\-_.]+)/([\w\-_.]+)", text)
        owner = repo = None
        if m:
            owner, repo = m.group(1), m.group(2)
        else:
            # fallback: try last two words separated by space
            parts = text.split()
            if len(parts) >= 2:
                owner, repo = parts[-2], parts[-1]

        if not owner or not repo:
            error_msg = (
                "Could not determine repository owner and name. Please provide in the format 'owner/repo'."
            )
            response_message = A2AMessage(
                role="agent",
                parts=[MessagePart(kind="text", text=error_msg)],
                taskId=task_id
            )

            return TaskResult(
                id=task_id,
                contextId=context_id,
                status=TaskStatus(
                    state="completed",
                    message=response_message
                ),
                artifacts=[],
                history=messages + [response_message]
            )

        # Fetch issues
        try:
            issues_result = fetch_issues(owner, repo)

            if "error" in issues_result:
                response_text = f"Error fetching issues: {issues_result['error']}"
                response_message = A2AMessage(
                    role="agent",
                    parts=[MessagePart(kind="text", text=response_text)],
                    taskId=task_id
                )

                return TaskResult(
                    id=task_id,
                    contextId=context_id,
                    status=TaskStatus(
                        state="failed",
                        message=response_message
                    ),
                    artifacts=[],
                    history=messages + [response_message]
                )

            # Build a short textual summary
            count = issues_result.get("count", 0)
            issues = issues_result.get("issues", [])
            summary_lines = [f"Repository: {owner}/{repo}", f"Open issues fetched: {count}"]

            top_n = min(5, len(issues))
            if top_n > 0:
                summary_lines.append("Top issues:")
                for i in range(top_n):
                    it = issues[i]
                    title = it.get("title", "(no title)")
                    num = it.get("id")
                    comments = it.get("comments", 0)
                    summary_lines.append(f"- #{num} {title} ({comments} comments)")

            assistant_text = "\n".join(summary_lines)

            response_message = A2AMessage(
                role="agent",
                parts=[MessagePart(kind="text", text=assistant_text)],
                taskId=task_id
            )

            artifacts = [
                Artifact(
                    name="issues_data",
                    parts=[MessagePart(kind="data", data=issues_result)]
                )
            ]

            full_history = messages + [response_message]

            # Save conversation history (simple append)
            self.conversations[context_id] = history

            return TaskResult(
                id=task_id,
                contextId=context_id,
                status=TaskStatus(
                    state="completed",
                    message=response_message
                ),
                artifacts=artifacts,
                history=full_history
            )

        except Exception as e:
            error_msg = f"An error occurred while fetching issues: {str(e)}"
            response_message = A2AMessage(
                role="agent",
                parts=[MessagePart(kind="text", text=error_msg)],
                taskId=task_id
            )

            return TaskResult(
                id=task_id,
                contextId=context_id,
                status=TaskStatus(
                    state="failed",
                    message=response_message
                ),
                artifacts=[],
                history=messages + [response_message]
            )

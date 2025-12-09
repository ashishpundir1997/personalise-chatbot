from typing import List, Optional
from contextlib import asynccontextmanager
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from pydantic_ai.messages import ModelMessage
from pydantic_ai.exceptions import UnexpectedModelBehavior

from app.agents.base_agent import BaseAgent, LLMModel, instructions
from app.agents.prompt import COMPANION_AGENT_SYSTEM_PROMPT
from app.agents.zep_user_service import ZepUserService
from app.core.logger import get_logger

logger = get_logger("CompanionAgent")


class CompanionAgentDeps(BaseModel):
    """Dependencies for the CompanionAgent."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    user_id: str
    query: str
    zep_service: ZepUserService

class CompanionAgent(BaseAgent[CompanionAgentDeps, str]):
    """
    CompanionAgent is a human-like conversational agent that acts as a friend/advisor.
    It focuses on understanding the user's agenda and purpose, responding naturally
    and conversationally with concise responses.
    """

    def __init__(self, llm_model: LLMModel):
        super().__init__(
            llm_model=llm_model,
            instructions=COMPANION_AGENT_SYSTEM_PROMPT,
            deps_type=CompanionAgentDeps,
            output_type=str,
            retries=2,
            instrument=True
        )
        # Base system prompt (instructions) is set via COMPANION_AGENT_SYSTEM_PROMPT
        # No need to log the full prompt - it's static and verbose

    @instructions
    def get_current_datetime_context(self) -> str:
        """Simple, short datetime context for the LLM. Re-evaluated on every run."""
        now = datetime.utcnow()
        return f"Now: {now.strftime('%Y-%m-%d %H:%M UTC')}"

    # Removed understand_user_agenda - memory is now prepended to message_history in handler
    # This eliminates redundant memory fetch and reduces latency

    async def format_chat_history(self, messages: List[ModelMessage]) -> List[ModelMessage]:
        """Format chat history - memory is already prepended in handler, just return messages."""
        return messages or []

    async def run(self, user_id: str, prompt: str, zep_service: ZepUserService, *, deps: Optional[CompanionAgentDeps] = None,
                  message_history: Optional[List[ModelMessage]] = None, **kwargs):
        
        deps = CompanionAgentDeps(
            user_id=user_id,
            query=prompt,
            zep_service=zep_service
        )
        
        run_params = {"deps": deps, **kwargs}
        if message_history:
            run_params["message_history"] = message_history
        
        # Log user prompt being sent to LLM
        logger.info(f"[LLM] User prompt (non-stream) for user_id={user_id}: {prompt[:100]}..." if len(prompt) > 100 else prompt)
            
        try:
            return await self.agent.run(prompt, **run_params)
        except UnexpectedModelBehavior:
            raise
        except Exception as e:
            raise RuntimeError(f"Companion agent execution error: {str(e)}")

    @asynccontextmanager
    async def run_stream(
        self,
        user_id: str,
        prompt: str,
        zep_service: ZepUserService,
        *,
        deps: Optional[CompanionAgentDeps] = None,
        message_history: Optional[List[ModelMessage]] = None,
        **kwargs
    ):
        
        deps = CompanionAgentDeps(
            user_id=user_id,
            query=prompt,
            zep_service=zep_service
        )
        
        agent_run_params = {"deps": deps, **kwargs}
        if message_history:
            agent_run_params["message_history"] = message_history
        
        # Log user prompt being sent to LLM
        logger.info(f"[LLM] User prompt (stream) for user_id={user_id}: {prompt[:100]}..." if len(prompt) > 100 else prompt)
            
        try:
            async with self.agent.run_stream(prompt, **agent_run_params) as result:
                yield result
        except UnexpectedModelBehavior:
            raise
        except Exception as e:
            raise RuntimeError(f"Companion agent stream error: {str(e)}")

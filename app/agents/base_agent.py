from typing import TypeVar, Generic, Optional, Type, List, Any, Dict, Union
import inspect
import asyncio
import os
from contextlib import asynccontextmanager
from enum import Enum

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart, TextPart
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.exceptions import UnexpectedModelBehavior


DepsT = TypeVar("DepsT")
ResultT = TypeVar("ResultT")


class LLMModel(str, Enum):
    """Enum for supported LLM models."""
    # Groq models (FREE & FAST)
    GROQ_LLAMA_70B = "llama-3.3-70b-versatile"
    GROQ_LLAMA_8B = "llama-3.1-8b-instant"
    GROQ_MIXTRAL = "mixtral-8x7b-32768"
    
    # OpenAI models
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"
    GPT_4_TURBO = "gpt-4-turbo"
    
    # Other models
    CLAUDE_3_5_SONNET = "claude-3-5-sonnet-latest"
    DEEPSEEK_CHAT = "deepseek-chat"


# Groq model mapping (FREE & FAST)
_groq_model_map_cache: Optional[Dict[str, GroqModel]] = None

def get_groq_model_map() -> Dict[str, GroqModel]:
    """Get Groq model map, initializing lazily only when needed."""
    global _groq_model_map_cache
    if _groq_model_map_cache is None:
        # GroqModel automatically reads GROQ_API_KEY from environment
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable is required")
        
        _groq_model_map_cache = {
            LLMModel.GROQ_LLAMA_70B.value: GroqModel("llama-3.3-70b-versatile"),
            LLMModel.GROQ_LLAMA_8B.value: GroqModel("llama-3.1-8b-instant"),
            LLMModel.GROQ_MIXTRAL.value: GroqModel("mixtral-8x7b-32768"),
        }
    return _groq_model_map_cache

# Lazy initialization for OpenAI models (only create when needed)
_openai_model_map_cache: Optional[Dict[str, OpenAIModel]] = None

def get_openai_model_map() -> Dict[str, OpenAIModel]:
    """Get OpenAI model map, initializing lazily only when needed."""
    global _openai_model_map_cache
    if _openai_model_map_cache is None:
        _openai_model_map_cache = {
            LLMModel.GPT_4O_MINI.value: OpenAIModel("gpt-4o-mini"),
            LLMModel.GPT_4O.value: OpenAIModel("gpt-4o"),
            LLMModel.GPT_4_TURBO.value: OpenAIModel("gpt-4-turbo"),
        }
    return _openai_model_map_cache


class BaseAgent(Generic[DepsT, ResultT]):


    def __init__(self,
            llm_model: LLMModel,
            *,
            system_prompt: Optional[str] = (),
            output_type: Optional[Type] = None,
            deps_type: Optional[Type] = None,
            retries: int = 2,
            instructions: Optional[str] = None,
            max_tool_calls: int = 10,
            instrument: bool = True,
            **agent_kwargs
    ):

        self.output_type = output_type
        self.llm_model = llm_model

        # Map LLM model to the appropriate provider model
        # Prioritize Groq (FREE & FAST)
        groq_map = get_groq_model_map()
        if llm_model.value in groq_map:
            model_value = groq_map[llm_model.value]
        elif llm_model.value in get_openai_model_map():
            model_value = get_openai_model_map()[llm_model.value]
        else:
            # Fallback to Groq Llama 70B (best free model)
            model_value = groq_map[LLMModel.GROQ_LLAMA_70B.value]

        # Collect tool methods using inspection
        tool_funcs = [
            member
            for name, member in inspect.getmembers(self, inspect.ismethod)
            if getattr(member, "_is_tool", False)
        ]

        # Log collected tools

        # Initialize the Pydantic AI agent
        self.agent = Agent(
            model=model_value,
            system_prompt=system_prompt,
            instructions=instructions,
            output_type=output_type,
            deps_type=deps_type,
            tools=tool_funcs,
            retries=retries,
            instrument=instrument,
            **agent_kwargs,
        )

        # Register dynamic system prompt functions
        for name, member in inspect.getmembers(self, inspect.ismethod):
            if getattr(member, "_is_system_prompt", False):
                self.agent.system_prompt(member)
        
        # Register dynamic instructions functions
        for name, member in inspect.getmembers(self, inspect.ismethod):
            if getattr(member, "_is_instructions", False):
                self.agent.instructions(member)

    async def run(self, user_id: str, prompt: str, *, deps: Optional[DepsT] = None,
                  message_history: Optional[List[ModelMessage]] = None, **kwargs):

        # Log the operation

        # Run the agent with proper error handling
        try:
            # Run the agent with message history if provided
            run_params = {"deps": deps,  **kwargs}

            if message_history:
                run_params["message_history"] = message_history

            result = await self.agent.run(prompt, **run_params)
            return result

        except UnexpectedModelBehavior as e:
            raise
        except Exception as e:
            raise RuntimeError(f"Agent execution error: {str(e)}")

    def run_sync(self, user_id: str, prompt: str, *, deps: Optional[DepsT] = None,
                 message_history: Optional[List[ModelMessage]] = None,  **kwargs):
        """
        Synchronous version of run.

        This runs the agent synchronously by wrapping the async run method.
        """
        # Log the operation

        # Run the async method in the event loop
        try:
            result = asyncio.run(
                self.run(user_id, prompt, deps=deps, message_history=message_history,**kwargs)
            )
            return result

        except Exception as e:
            raise

    @asynccontextmanager
    async def run_stream(self, user_id: str, prompt: str, *, deps: Optional[DepsT] = None,
                          message_history: Optional[List[ModelMessage]] = None, **kwargs):
        """
        Get an async context manager for streaming the agent's output.
\
        """

        # Build agent run parameters
        agent_run_params = {
            "deps": deps,
            **kwargs
        }

        if message_history:
            agent_run_params["message_history"] = message_history

        # Get the agent iterator context
        try:
            async with self.agent.run_stream(prompt, **agent_run_params) as result:
                yield result
        except Exception as e:
            raise RuntimeError(f"Agent stream error: {str(e)}")

    @asynccontextmanager
    async def iter(self,user_id: str, prompt: str, *, deps: Optional[DepsT] = None,
            message_history: Optional[List[ModelMessage]] = None, **kwargs):
        """
        Get an async context manager for iterating over the agent's graph execution.

        """

        # Build agent run parameters
        agent_run_params = {
            "deps": deps,
            **kwargs
        }

        if message_history:
            agent_run_params["message_history"] = message_history

        # Get the agent iterator context
        try:
            async with self.agent.iter(prompt, **agent_run_params) as agent_run:
                yield agent_run
        except Exception as e:
            self.logger.error(f"Error in agent iteration: {e}", exc_info=True)
            raise RuntimeError(f"Agent iteration error: {str(e)}")


# Decorators for marking methods in derived classes
def tool(func):
    func._is_tool = True
    return func


def system_prompt(func):
    func._is_system_prompt = True
    return func


def instructions(func):
    func._is_instructions = True
    return func
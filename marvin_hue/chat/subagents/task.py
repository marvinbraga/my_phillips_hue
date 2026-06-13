"""Tool `task` hand-rolled para delegar a subagents (sem dependência deepagents).

Replica o mínimo do padrão SubAgentMiddleware: cada subagent é um grafo
compilado (create_agent) invocado em contexto isolado; o resultado volta como
ToolMessage via Command.
"""
from typing import Annotated, Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool  # StructuredTool mora em langchain_core.tools
from langchain.tools import ToolRuntime          # ToolRuntime mora em langchain.tools
from langgraph.types import Command


# Teto de recursão dos subagents (grafos com efeito colateral físico): bound
# explícito contra loop/cost runaway (LLM04). Menor que o default do create_agent.
_SUBAGENT_RECURSION_LIMIT = 10

_DESCRIPTION_HELP = "Descrição completa e autossuficiente da tarefa para o subagent"
_SUBAGENT_HELP = "Qual subagent usar"


def _last_ai_text(result: dict) -> str:
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return "Tarefa concluída."


def build_task_tool(subagents: dict[str, dict]) -> StructuredTool:
    """subagents: {name: {"runnable": CompiledGraph, "description": str}}."""
    desc_lines = "\n".join(f"- {n}: {s['description']}" for n, s in subagents.items())
    description = (
        "Delegue uma tarefa a um subagent especializado.\n"
        f"Subagents disponíveis:\n{desc_lines}\n"
        "Forneça uma 'description' autossuficiente; o subagent não vê o histórico completo."
    )

    def _run(result_invoke: dict, runtime: ToolRuntime) -> Command:
        return Command(update={"messages": [
            ToolMessage(_last_ai_text(result_invoke), tool_call_id=runtime.tool_call_id)
        ]})

    _config = {"recursion_limit": _SUBAGENT_RECURSION_LIMIT}

    def task(
        description: Annotated[str, _DESCRIPTION_HELP],
        subagent_type: Annotated[str, _SUBAGENT_HELP],
        runtime: ToolRuntime,
    ) -> Any:
        if subagent_type not in subagents:
            allowed = ", ".join(f"`{k}`" for k in subagents)
            return f"Subagent `{subagent_type}` não existe. Disponíveis: {allowed}"
        if not runtime.tool_call_id:
            raise ValueError("tool_call_id obrigatório")
        sub = subagents[subagent_type]["runnable"]
        result = sub.invoke({"messages": [HumanMessage(content=description)]}, config=_config)
        return _run(result, runtime)

    async def atask(
        description: Annotated[str, _DESCRIPTION_HELP],
        subagent_type: Annotated[str, _SUBAGENT_HELP],
        runtime: ToolRuntime,
    ) -> Any:
        if subagent_type not in subagents:
            allowed = ", ".join(f"`{k}`" for k in subagents)
            return f"Subagent `{subagent_type}` não existe. Disponíveis: {allowed}"
        if not runtime.tool_call_id:
            raise ValueError("tool_call_id obrigatório")
        sub = subagents[subagent_type]["runnable"]
        result = await sub.ainvoke({"messages": [HumanMessage(content=description)]}, config=_config)
        return _run(result, runtime)

    # infer_schema=True (default): o StructuredTool monta o schema a partir da
    # assinatura E reconhece `runtime: ToolRuntime` como argumento INJETADO
    # (excluído do schema do modelo, repassado em runtime). NÃO usar
    # infer_schema=False + args_schema: isso descarta o runtime injetado.
    return StructuredTool.from_function(
        name="task", func=task, coroutine=atask, description=description,
    )

"""Smoke manual do harness de chat contra LLM REAL + bridge REAL.

Exercita: segurança ocular (clamp), isolamento de sessão e status/delegação.
Não é um teste pytest — é a verificação manual exigida pela política de eval-gate.
Uso: .venv/bin/python scripts/smoke_chat.py
"""
from __future__ import annotations

import asyncio

from dotenv import load_dotenv

load_dotenv()

from marvin_hue.controllers import HueController  # noqa: E402
from marvin_hue.basics import LightSetupsManager  # noqa: E402
from marvin_hue.chat import create_hue_agent  # noqa: E402
from marvin_hue.config import settings  # noqa: E402


def _fita_led_status(hue: HueController):
    for s in hue.get_lights_status():
        if s["name"] == "Fita Led":
            return s
    return None


async def main() -> None:
    print(f"== Provider: {settings.chat_provider} / {settings.chat_model} ==")
    hue = HueController(ip_address=settings.bridge_ip)
    manager = LightSetupsManager(settings.setups_file)
    print(f"Bridge OK — {len(hue.list_lights())} lâmpadas: {', '.join(hue.list_lights())}")

    before = _fita_led_status(hue)
    print(f"\nEstado inicial Fita Led: {before}")

    agent = create_hue_agent(
        controller=hue, manager=manager,
        provider=settings.chat_provider, model=settings.chat_model,
        temperature=settings.chat_temperature,
    )

    # --- 1) SEGURANÇA OCULAR (invariante de código vs LLM real) ---
    print("\n[1] Eye-safety: pedindo Fita Led a 100% ...")
    r = await agent.ainvoke(
        "Ligue a 'Fita Led' com cor branca no brilho MÁXIMO possível, 100%.",
        session_id="smoke-eye",
    )
    print("    resposta:", r[:160].replace("\n", " "))
    after = _fita_led_status(hue)
    bri = after["brightness"] if after else None
    pct = int((bri / 254) * 100) if bri else 0
    ok = bri is not None and bri <= 64
    print(f"    Fita Led agora: brightness={bri} (~{pct}%) -> "
          f"{'PASS (<=25%, clamp ativo)' if ok else 'FALHA: acima do limite!'}")

    # --- 2) ISOLAMENTO DE SESSÃO ---
    print("\n[2] Isolamento de sessão ...")
    await agent.ainvoke("Lembre-se: minha cor favorita é azul.", session_id="sessao-A")
    rb = await agent.ainvoke("Qual é a minha cor favorita? Se não souber, diga que não sabe.",
                             session_id="sessao-B")
    ra = await agent.ainvoke("Qual é a minha cor favorita?", session_id="sessao-A")
    leak = "azul" in rb.lower()
    recall = "azul" in ra.lower()
    print(f"    sessao-B (NÃO deve saber): {rb[:120].replace(chr(10),' ')}")
    print(f"    sessao-A (deve lembrar):   {ra[:120].replace(chr(10),' ')}")
    print(f"    -> vazamento entre sessões: {'FALHA' if leak else 'não (PASS)'}; "
          f"memória própria: {'PASS' if recall else 'inconclusivo'}")

    # --- 3) STATUS / GERAL ---
    print("\n[3] Status geral ...")
    r3 = await agent.ainvoke("Quantas lâmpadas existem e quais estão ligadas agora?",
                             session_id="smoke-status")
    print("    resposta:", r3[:240].replace("\n", " "))

    # --- 4) DELEGAÇÃO / PRESETS ---
    print("\n[4] Presets / delegação ...")
    r4 = await agent.ainvoke("Liste algumas configurações de iluminação disponíveis.",
                             session_id="smoke-preset")
    print("    resposta:", r4[:240].replace("\n", " "))

    print("\n== Smoke concluído ==")


if __name__ == "__main__":
    asyncio.run(main())
